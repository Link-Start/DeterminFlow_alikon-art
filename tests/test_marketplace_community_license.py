from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from src.skill_marketplace.drafts import DRAFT_FIELD_LIMITS
from src.skill_marketplace.local_skills import (
    ALLOWED_PUBLISH_LICENSES,
    COMMUNITY_USE_LICENSE,
    declared_skill_license,
    prepare_skill_upload,
)
from src.skill_marketplace.service import LocalSkillError
from marketplace_fixtures import (
    FakeAccount,
    FakeMarketplace,
    SKILL_TEXT,
    _empty_manager,
    _service,
)

STANDARD_LICENSES = ("MIT", "Apache-2.0", "CC-BY-4.0", "CC0-1.0")
OTHER_TEXT = """---
name: other-skill
description: Another shareable Skill
metadata:
  version: 0.9.0
---

# Other

Different body.
"""
DRAFT_FIELDS = {
    "license": COMMUNITY_USE_LICENSE,
    "display_name": "共享技能",
    "author_name": "北辰",
    "summary": "",
    "functional_category": "novel",
    "primary_locale": "zh-CN",
    "tags_csv": "writing",
    "release_notes": "",
}


def _signed_in(tmp_path: Path, **kwargs):
    return _service(
        tmp_path,
        account=kwargs.pop("account", FakeAccount("access")),
        **kwargs,
    )


def _skill_text(*, license_id: str | None = None, name: str = "shared-skill") -> str:
    license_line = f"license: {license_id}\n" if license_id is not None else ""
    return (
        "---\n"
        f"name: {name}\n"
        "description: A shareable test Skill\n"
        f"{license_line}"
        "metadata:\n"
        "  version: 1.2.3\n"
        "---\n\n"
        "# Instructions\n\n"
        "Do the useful thing.\n"
    )


def _write_skill(tmp_path: Path, skill_id: str, text: str) -> Path:
    path = tmp_path / "skills" / "local" / skill_id / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _publish_kwargs(**overrides):
    payload = {
        "skill_id": "shared-skill",
        "resource_type": "skill",
        "license_id": COMMUNITY_USE_LICENSE,
        "rights_confirmed": True,
        "terms_confirmed": True,
        "terms_version": "2026-09-06",
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def _pin(service) -> dict[str, str]:
    detail = asyncio.run(service.marketplace.get_skill("shared-skill"))
    return {
        "expected_version_id": detail.get("resource", {}).get("version_id")
        or detail["version_id"],
        "expected_sha256": detail.get("payload", {}).get("sha256") or detail["sha256"],
    }


def test_community_license_fits_publish_and_draft_limits() -> None:
    assert COMMUNITY_USE_LICENSE == "LicenseRef-DF-Community-1.0"
    assert len(COMMUNITY_USE_LICENSE) < 32
    assert len(COMMUNITY_USE_LICENSE) <= DRAFT_FIELD_LIMITS["license"]
    assert ALLOWED_PUBLISH_LICENSES == frozenset((*STANDARD_LICENSES, COMMUNITY_USE_LICENSE))


@pytest.mark.parametrize("license_id", [*STANDARD_LICENSES, COMMUNITY_USE_LICENSE])
def test_undeclared_skill_can_publish_supported_licenses(
    tmp_path: Path, license_id: str
) -> None:
    marketplace = FakeMarketplace()
    service = _signed_in(tmp_path, marketplace=marketplace)
    source_path = tmp_path / "skills" / "local" / "shared-skill" / "SKILL.md"
    original = source_path.read_bytes()
    result = asyncio.run(service.publish(**_publish_kwargs(license_id=license_id)))
    assert result["status"] == "pending_review"
    uploaded = marketplace.published[-1]
    assert uploaded["license_id"] == license_id
    assert uploaded["content"] == original == SKILL_TEXT.encode()
    assert uploaded["rights_confirmed"] is True
    assert uploaded["terms_confirmed"] is True
    assert uploaded["terms_version"] == "2026-09-06"
    assert source_path.read_bytes() == original
    assert declared_skill_license(uploaded["content"]) == ""


def test_community_license_prepared_publish_keeps_source_bytes(tmp_path: Path) -> None:
    marketplace = FakeMarketplace()
    service = _signed_in(tmp_path, marketplace=marketplace)
    source_path = _write_skill(tmp_path, "other-skill", OTHER_TEXT)
    service.skill_manager.reload()
    original = source_path.read_bytes()
    preview = asyncio.run(
        service.preview_local_skill(
            "other-skill",
            target_slug="shared-skill",
            publication_version="1.3.0",
        )
    )
    result = asyncio.run(
        service.publish(
            **_publish_kwargs(
                skill_id="other-skill",
                expected_sha256=preview["sha256"],
                target_slug="shared-skill",
                publication_version="1.3.0",
            )
        )
    )
    uploaded = marketplace.published[-1]
    prepared = prepare_skill_upload(original, name="shared-skill", version="1.3.0")
    assert result["status"] == "pending_review"
    assert uploaded["license_id"] == COMMUNITY_USE_LICENSE
    assert uploaded["content"] == prepared == preview["content"].encode()
    assert hashlib.sha256(uploaded["content"]).hexdigest() == preview["sha256"]
    assert source_path.read_bytes() == original
    assert declared_skill_license(uploaded["content"]) == ""
    assert b"license:" not in uploaded["content"]


def test_matching_community_declaration_uploads_original_bytes(tmp_path: Path) -> None:
    text = _skill_text(license_id=COMMUNITY_USE_LICENSE)
    service = _signed_in(tmp_path)
    source_path = _write_skill(tmp_path, "shared-skill", text)
    service.skill_manager.reload()
    original = source_path.read_bytes()
    asyncio.run(
        service.publish(
            **_publish_kwargs(expected_sha256=hashlib.sha256(original).hexdigest())
        )
    )
    uploaded = service.marketplace.published[-1]
    assert uploaded["content"] == original
    assert uploaded["license_id"] == COMMUNITY_USE_LICENSE
    assert declared_skill_license(uploaded["content"]) == COMMUNITY_USE_LICENSE
    assert source_path.read_bytes() == original


@pytest.mark.parametrize(
    ("rights_confirmed", "terms_confirmed", "terms_version", "code"),
    [
        (False, True, "2026-09-06", "rights_required"),
        (True, False, "2026-09-06", "terms_required"),
        (True, True, "2026-09-05", "terms_required"),
        (True, True, None, "terms_required"),
    ],
)
def test_community_license_still_requires_explicit_confirmations(
    tmp_path: Path,
    rights_confirmed: bool,
    terms_confirmed: bool,
    terms_version: str | None,
    code: str,
) -> None:
    service = _signed_in(tmp_path)
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(
            service.publish(
                **_publish_kwargs(
                    rights_confirmed=rights_confirmed,
                    terms_confirmed=terms_confirmed,
                    terms_version=terms_version,
                )
            )
        )
    assert error.value.code == code
    assert service.marketplace.published == []


@pytest.mark.parametrize(
    ("declared", "selected"),
    [
        ("MIT", COMMUNITY_USE_LICENSE),
        (COMMUNITY_USE_LICENSE, "MIT"),
        ("GPL-3.0", COMMUNITY_USE_LICENSE),
        ("GPL-3.0", "MIT"),
        ("Apache-2.0", "CC-BY-4.0"),
        ("LicenseRef-Other-1.0", COMMUNITY_USE_LICENSE),
    ],
)
def test_declared_license_conflict_rejects_without_upload_or_rewrite(
    tmp_path: Path, declared: str, selected: str
) -> None:
    text = _skill_text(license_id=declared)
    service = _signed_in(tmp_path)
    source_path = _write_skill(tmp_path, "shared-skill", text)
    service.skill_manager.reload()
    original = source_path.read_bytes()
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(service.publish(**_publish_kwargs(license_id=selected)))
    assert error.value.code == "invalid_license"
    assert "不一致" in error.value.message
    assert service.marketplace.published == []
    assert source_path.read_bytes() == original


def test_prepared_publish_rejects_declaration_conflict_without_rewriting_source(
    tmp_path: Path,
) -> None:
    text = OTHER_TEXT.replace(
        "metadata:\n",
        "license: MIT\nmetadata:\n",
    )
    service = _signed_in(tmp_path)
    source_path = _write_skill(tmp_path, "other-skill", text)
    service.skill_manager.reload()
    original = source_path.read_bytes()
    preview = asyncio.run(
        service.preview_local_skill(
            "other-skill",
            target_slug="shared-skill",
            publication_version="1.3.0",
        )
    )
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(
            service.publish(
                **_publish_kwargs(
                    skill_id="other-skill",
                    expected_sha256=preview["sha256"],
                    target_slug="shared-skill",
                    publication_version="1.3.0",
                )
            )
        )
    assert error.value.code == "invalid_license"
    assert service.marketplace.published == []
    assert source_path.read_bytes() == original
    assert declared_skill_license(preview["content"].encode()) == "MIT"


def test_unsupported_license_is_rejected_before_upload(tmp_path: Path) -> None:
    service = _signed_in(tmp_path)
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(service.publish(**_publish_kwargs(license_id="GPL-3.0")))
    assert error.value.code == "invalid_license"
    assert "支持" in error.value.message
    assert service.marketplace.published == []


def test_publish_draft_round_trips_community_license(tmp_path: Path) -> None:
    service = _signed_in(tmp_path)
    digest = hashlib.sha256(SKILL_TEXT.encode()).hexdigest()
    saved = asyncio.run(
        service.save_publish_draft(
            "shared-skill",
            expected_revision=None,
            base_version="1.2.3",
            base_sha256=digest,
            fields=DRAFT_FIELDS,
        )
    )["draft"]
    loaded = asyncio.run(service.get_publish_draft("shared-skill"))
    assert saved["fields"]["license"] == COMMUNITY_USE_LICENSE
    assert loaded["draft"]["fields"]["license"] == COMMUNITY_USE_LICENSE
    # Drafts retain unknown/upstream declarations without silently relicensing.
    # Publication, rather than draft storage, is the enforcement boundary.
    asyncio.run(service.save_publish_draft(
        "shared-skill", expected_revision=saved["revision"],
        base_version="1.2.3", base_sha256=digest,
        fields={**DRAFT_FIELDS, "license": "GPL-3.0"},
    ))
    assert asyncio.run(service.get_publish_draft("shared-skill"))["draft"]["fields"]["license"] == "GPL-3.0"


def test_install_provenance_keeps_community_license(tmp_path: Path) -> None:
    class CommunityLicenseMarketplace(FakeMarketplace):
        async def get_skill(self, slug: str) -> dict:
            detail = await super().get_skill(slug)
            detail["license"] = COMMUNITY_USE_LICENSE
            return detail

    manager = _empty_manager(tmp_path)
    marketplace = CommunityLicenseMarketplace()
    service = _service(tmp_path, manager=manager, marketplace=marketplace)
    result = asyncio.run(service.install("shared-skill", **_pin(service)))
    assert result["provenance"]["package"]["license"] == COMMUNITY_USE_LICENSE
    stored = manager.provenance_store.get("skill", "shared-skill")
    assert stored is not None
    assert stored["package"]["license"] == COMMUNITY_USE_LICENSE


def test_install_provenance_keeps_community_license_from_release_envelope(
    tmp_path: Path,
) -> None:
    class EnvelopeMarketplace(FakeMarketplace):
        async def get_skill(self, slug: str) -> dict:
            digest = hashlib.sha256(self.content).hexdigest()
            return {
                "resource": {
                    "id": "resource-envelope",
                    "version_id": "version-envelope",
                    "resource_type": "skill",
                    "functional_category": "novel",
                    "author": {"id": "pub_0123456789abcdef01234567", "name": "北辰"},
                    "release": {
                        "version": "1.2.3",
                        "license": COMMUNITY_USE_LICENSE,
                    },
                },
                "payload": {"type": "skill", "name": slug, "sha256": digest},
            }

    manager = _empty_manager(tmp_path)
    service = _service(
        tmp_path,
        manager=manager,
        marketplace=EnvelopeMarketplace(),
    )
    result = asyncio.run(service.install("shared-skill", **_pin(service)))
    assert result["provenance"]["package"]["license"] == COMMUNITY_USE_LICENSE
