"""Isolated Stage 5 route/service lifecycle for install, account recovery, and authoring."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marketplace_fixtures import (
    FakeAccount,
    FakeMarketplace,
    SAMPLE_SUBMISSION,
    SKILL_TEXT,
    _empty_manager,
    _service,
)
from src.skill_marketplace.operation_log import LOG_FIELDS, emit_marketplace_operation, logged_payload
from src.skill_marketplace.routes import router
from src.skill_marketplace.service import LocalSkillError
from src.skills.config_manager import SkillConfigManager
from src.skills.manager import SkillManager
from test_marketplace_installation import _pin

DIGEST = hashlib.sha256(SKILL_TEXT.encode()).hexdigest()
DRAFT_FIELDS = {
    "license": "MIT",
    "display_name": "共享技能",
    "author_name": "北辰",
    "summary": "",
    "functional_category": "novel",
    "primary_locale": "zh-CN",
    "tags_csv": "writing",
    "release_notes": "",
}
LOGGER_NAME = "determinflow.marketplace.operations"


def _desktop(tmp_path: Path, service, monkeypatch) -> TestClient:
    monkeypatch.setenv("DETERMINFLOW_DESKTOP", "1")
    app = FastAPI()
    app.state.resource_marketplace_service = service
    app.include_router(router)
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def _reload_manager(tmp_path: Path) -> SkillManager:
    return SkillManager(
        tmp_path / "skills" / "local",
        SkillConfigManager(tmp_path / "config" / "skills.json"),
        builtin_skills_dir=tmp_path / "skills" / "builtin",
        marketplace_skills_dir=tmp_path / "skills" / "marketplace",
        provenance_path=tmp_path / "resource-provenance.json",
    )


def _operation_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == LOGGER_NAME]


def _serialized(record: logging.LogRecord) -> str:
    payload = logged_payload(record)
    return " ".join(
        [
            record.getMessage(),
            json.dumps(payload, ensure_ascii=False, default=str),
            str(record.exc_info),
            str(getattr(record, "exc_text", "") or ""),
        ]
    )


def test_install_route_persists_enabled_skill_across_manager_reload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    with _desktop(tmp_path, service, monkeypatch) as client:
        response = client.post(
            "/api/resource-marketplace/skills/shared-skill/install",
            json=_pin(service),
        )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
        assert body["installed"] is True
        assert body["enabled"] is True
        opened = client.post("/api/resource-marketplace/skills/shared-skill/open-installed")
        assert opened.status_code == 200
        assert opened.headers["cache-control"] == "no-store"
        assert opened.json() == {"opened": True, "skill_id": "shared-skill"}

    installed_path = tmp_path / "skills" / "marketplace" / "shared-skill" / "SKILL.md"
    assert installed_path.read_text(encoding="utf-8") == SKILL_TEXT
    saved = json.loads((tmp_path / "config" / "skills.json").read_text(encoding="utf-8"))
    assert saved["skill_configs"]["shared-skill"]["enabled"] is True
    assert saved["skill_configs"]["shared-skill"]["auto_inject"] is True
    reloaded = _reload_manager(tmp_path)
    skill = reloaded.get_skill("shared-skill")
    assert skill is not None
    assert skill.enabled is True
    assert reloaded.config_manager.get_enabled("shared-skill") is True
    assert reloaded.config_manager.should_auto_inject("shared-skill") is True
    assert skill.metadata["provenance"]["source"]["kind"] == "marketplace"
    payloads = [logged_payload(record) for record in _operation_records(caplog)]
    assert payloads[-1]["operation"] == "install"
    assert payloads[-1]["result"] == "success"
    assert "error_code" not in payloads[-1]
    assert set(payloads[-1]) <= LOG_FIELDS


def test_download_success_is_not_an_install_and_logs_failure(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    class ChangedDownload(FakeMarketplace):
        async def download_skill(self, slug: str):
            self.content = SKILL_TEXT.replace("1.2.3", "1.2.4").encode()
            return await super().download_skill(slug)

    marketplace = ChangedDownload()
    service = _service(tmp_path, manager=_empty_manager(tmp_path), marketplace=marketplace)
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(service.install("shared-skill", **_pin(service)))
    assert error.value.code == "integrity_mismatch"
    assert marketplace.download_calls == ["shared-skill"]
    assert not (tmp_path / "skills" / "marketplace" / "shared-skill").exists()
    assert _reload_manager(tmp_path).get_skill("shared-skill") is None
    payloads = [logged_payload(record) for record in _operation_records(caplog)]
    assert payloads == [
        {
            "operation": "install",
            "result": "failure",
            "error_code": "integrity_mismatch",
            "duration_ms": payloads[0]["duration_ms"],
        }
    ]
    assert payloads[0]["duration_ms"] >= 0


def test_leaky_install_exception_is_not_written_to_operation_logs(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    secret = "token=secret-access-token https://evil.example/user/acct_alice"

    class LeakyMarketplace(FakeMarketplace):
        async def download_skill(self, slug: str):
            raise RuntimeError(secret)

    service = _service(
        tmp_path,
        manager=_empty_manager(tmp_path),
        marketplace=LeakyMarketplace(),
    )
    with pytest.raises(RuntimeError, match="secret-access-token"):
        asyncio.run(service.install("shared-skill", **_pin(service)))
    records = _operation_records(caplog)
    assert len(records) == 1
    blob = _serialized(records[0])
    assert "marketplace_operation" in blob
    assert "secret-access-token" not in blob
    assert "evil.example" not in blob
    assert "acct_alice" not in blob
    assert records[0].exc_info is None
    assert logged_payload(records[0])["error_code"] == "internal_error"


def test_publish_route_recovers_from_expired_access_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    account = FakeAccount("expired")
    marketplace = FakeMarketplace()
    service = _service(tmp_path, account=account, marketplace=marketplace)
    with _desktop(tmp_path, service, monkeypatch) as client:
        response = client.post(
            "/api/resource-marketplace/publish",
            json={
                "skill_id": "shared-skill",
                "resource_type": "skill",
                "license": "MIT",
                "rights_confirmed": True,
                "terms_confirmed": True,
                "terms_version": "2026-09-06",
                "expected_sha256": DIGEST,
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "pending_review"
    assert account.refresh_count == 1
    assert account.access_token() == "renewed"
    assert marketplace.published[-1]["access_token"] == "renewed"
    payloads = [logged_payload(record) for record in _operation_records(caplog)]
    assert payloads[-1]["operation"] == "publish"
    assert payloads[-1]["result"] == "success"


def test_unrecoverable_expiry_keeps_partitioned_draft_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnrecoverableAccount(FakeAccount):
        async def refresh_access_token(self, stale_access_token: str) -> str | None:
            if self._access_token != stale_access_token:
                return self._access_token
            self.refresh_count += 1
            self._access_token = None
            return None

    account = UnrecoverableAccount("expired")
    service = _service(tmp_path, account=account)
    asyncio.run(
        service.save_publish_draft(
            "shared-skill",
            expected_revision=None,
            base_version="1.2.3",
            base_sha256=DIGEST,
            fields=DRAFT_FIELDS,
        )
    )
    with _desktop(tmp_path, service, monkeypatch) as client:
        failed = client.post(
            "/api/resource-marketplace/publish",
            json={
                "skill_id": "shared-skill",
                "resource_type": "skill",
                "license": "MIT",
                "rights_confirmed": True,
                "terms_confirmed": True,
                "terms_version": "2026-09-06",
                "expected_sha256": DIGEST,
            },
        )
        assert failed.status_code == 401
        assert failed.json()["detail"]["code"] == "login_required"
        account._access_token = "access"
        draft = client.get("/api/resource-marketplace/publish-drafts/shared-skill")
        assert draft.status_code == 200
        assert draft.json()["draft"]["revision"] == 1
        retry = client.post(
            "/api/resource-marketplace/publish",
            json={
                "skill_id": "shared-skill",
                "resource_type": "skill",
                "license": "MIT",
                "rights_confirmed": True,
                "terms_confirmed": True,
                "terms_version": "2026-09-06",
                "expected_sha256": DIGEST,
            },
        )
        assert retry.status_code == 200
        assert retry.json()["status"] == "pending_review"


def test_author_draft_preview_publish_reject_retry_through_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marketplace = FakeMarketplace()
    service = _service(tmp_path, account=FakeAccount("access"), marketplace=marketplace)
    with _desktop(tmp_path, service, monkeypatch) as client:
        preview = client.get("/api/resource-marketplace/local-skills/shared-skill/preview")
        assert preview.status_code == 200
        assert preview.json()["sha256"] == DIGEST
        saved = client.put(
            "/api/resource-marketplace/publish-drafts/shared-skill",
            json={
                "expected_revision": None,
                "base_version": "1.2.3",
                "base_sha256": DIGEST,
                "fields": DRAFT_FIELDS,
            },
        )
        assert saved.status_code == 200
        published = client.post(
            "/api/resource-marketplace/publish",
            json={
                "skill_id": "shared-skill",
                "resource_type": "skill",
                "license": "MIT",
                "rights_confirmed": True,
                "terms_confirmed": True,
                "terms_version": "2026-09-06",
                "expected_sha256": DIGEST,
            },
        )
        assert published.status_code == 200
        rejected = client.post(
            f"/api/resource-marketplace/reviews/{SAMPLE_SUBMISSION['id']}",
            json={
                "decision": "reject",
                "expected_sha256": "a" * 64,
                "reason": "缺少来源说明",
            },
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"
        skill = service.skill_manager.get_skill("shared-skill")
        assert skill is not None
        skill_path = Path(skill.metadata["skill_dir"]) / "SKILL.md"
        retried = SKILL_TEXT.replace("1.2.3", "1.2.4")
        skill_path.write_text(retried, encoding="utf-8")
        service.skill_manager.reload()
        next_preview = client.get("/api/resource-marketplace/local-skills/shared-skill/preview")
        next_digest = next_preview.json()["sha256"]
        assert next_preview.json()["version"] == "1.2.4"
        retry = client.post(
            "/api/resource-marketplace/publish",
            json={
                "skill_id": "shared-skill",
                "resource_type": "skill",
                "license": "MIT",
                "rights_confirmed": True,
                "terms_confirmed": True,
                "terms_version": "2026-09-06",
                "expected_sha256": next_digest,
            },
        )
        assert retry.status_code == 200
        assert len(marketplace.published) == 2
        assert marketplace.review_calls[-1]["decision"] == "reject"


def test_unknown_operation_fields_are_dropped(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    emit_marketplace_operation(
        operation="download",
        result="success",
        duration_ms=12,
        error_code="token=secret",
    )
    emit_marketplace_operation(
        operation="install",
        result="maybe",
        duration_ms=12,
    )
    assert _operation_records(caplog) == []


def test_default_server_formatter_keeps_actionable_operation_fields(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    emit_marketplace_operation(operation="publish", result="failure", duration_ms=12, error_code="network_unavailable")
    record = _operation_records(caplog)[-1]
    rendered = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s").format(record)
    payload = json.loads(rendered.split("marketplace_operation ", 1)[1])
    assert payload == {"operation": "publish", "result": "failure", "duration_ms": 12, "error_code": "network_unavailable"}


def test_install_requires_persistent_activation_configuration(tmp_path: Path) -> None:
    manager = _empty_manager(tmp_path)
    manager.config_manager = None
    marketplace = FakeMarketplace()
    service = _service(tmp_path, manager=manager, marketplace=marketplace)
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(service.install("shared-skill", **_pin(service)))
    assert error.value.code == "config_unavailable"
    assert error.value.status_code == 503
    assert marketplace.download_calls == []
    assert not (tmp_path / "skills" / "marketplace" / "shared-skill").exists()
