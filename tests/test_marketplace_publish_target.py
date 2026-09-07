from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from src.skill_marketplace.local_skills import prepare_skill_upload, skill_identity
from src.skill_marketplace.service import LocalSkillError
from marketplace_fixtures import (
    FakeAccount,
    SKILL_TEXT,
    _empty_manager,
    _service,
)

DIGEST = hashlib.sha256(SKILL_TEXT.encode()).hexdigest()
OTHER_TEXT = """---
name: other-skill
description: Another shareable Skill
metadata:
  version: 0.9.0
---

# Other

Different body.
"""


def _signed_in(tmp_path: Path, **kwargs):
    return _service(
        tmp_path,
        account=kwargs.pop("account", FakeAccount("access")),
        **kwargs,
    )


def _write_skill(tmp_path: Path, skill_id: str, text: str) -> None:
    skill_dir = tmp_path / "skills" / "local" / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")


def test_prepare_upload_rewrites_identity_and_leaves_source_file(tmp_path: Path) -> None:
    original = OTHER_TEXT.encode()
    prepared = prepare_skill_upload(original, name="shared-skill", version="1.3.0")
    name, version = skill_identity(prepared)
    assert name == "shared-skill"
    assert version == "1.3.0"
    assert b"Different body." in prepared
    assert original == OTHER_TEXT.encode()
    assert hashlib.sha256(prepared).hexdigest() != hashlib.sha256(original).hexdigest()


def test_preview_and_publish_use_the_same_prepared_bytes(tmp_path: Path) -> None:
    service = _signed_in(tmp_path)
    _write_skill(tmp_path, "other-skill", OTHER_TEXT)
    service.skill_manager.reload()
    preview = asyncio.run(
        service.preview_local_skill(
            "other-skill",
            target_slug="shared-skill",
            publication_version="1.3.0",
        )
    )
    assert preview["skill_id"] == "other-skill"
    assert preview["name"] == "shared-skill"
    assert preview["version"] == "1.3.0"
    assert preview["source_sha256"] == hashlib.sha256(OTHER_TEXT.encode()).hexdigest()
    assert preview["sha256"] == hashlib.sha256(preview["content"].encode()).hexdigest()
    assert (tmp_path / "skills" / "local" / "other-skill" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == OTHER_TEXT

    result = asyncio.run(
        service.publish(
            skill_id="other-skill",
            resource_type="skill",
            license_id="MIT",
            rights_confirmed=True,
            terms_confirmed=True,
            terms_version="2026-09-06",
            metadata={},
            expected_sha256=preview["sha256"],
            target_slug="shared-skill",
            publication_version="1.3.0",
        )
    )
    assert result["status"] == "pending_review"
    uploaded = service.marketplace.published[-1]
    assert uploaded["content"] == preview["content"].encode()
    assert uploaded["target_slug"] == "shared-skill"
    assert uploaded["publication_version"] == "1.3.0"
    assert hashlib.sha256(uploaded["content"]).hexdigest() == preview["sha256"]


def test_source_pin_detects_local_changes_before_prepared_submit(tmp_path: Path) -> None:
    service = _signed_in(tmp_path)
    _write_skill(tmp_path, "other-skill", OTHER_TEXT)
    service.skill_manager.reload()
    preview = asyncio.run(
        service.preview_local_skill(
            "other-skill",
            target_slug="shared-skill",
            publication_version="1.3.0",
        )
    )
    (tmp_path / "skills" / "local" / "other-skill" / "SKILL.md").write_text(
        OTHER_TEXT.replace("Different body.", "Changed body."),
        encoding="utf-8",
    )
    service.skill_manager.reload()
    with pytest.raises(LocalSkillError) as changed:
        asyncio.run(
            service.publish(
                skill_id="other-skill",
                resource_type="skill",
                license_id="MIT",
                rights_confirmed=True,
                terms_confirmed=True,
                terms_version="2026-09-06",
                metadata={},
                expected_sha256=preview["sha256"],
                target_slug="shared-skill",
                publication_version="1.3.0",
            )
        )
    assert changed.value.code == "local_skill_changed"
    assert service.marketplace.published == []


def test_missing_original_source_can_update_from_another_skill(tmp_path: Path) -> None:
    manager = _empty_manager_with_other(tmp_path)
    service = _signed_in(tmp_path, manager=manager)
    preview = asyncio.run(
        service.preview_local_skill(
            "other-skill",
            target_slug="shared-skill",
            publication_version="2.0.0",
        )
    )
    asyncio.run(
        service.publish(
            skill_id="other-skill",
            resource_type="skill",
            license_id="MIT",
            rights_confirmed=True,
            terms_confirmed=True,
            terms_version="2026-09-06",
            metadata={"display_name": "线上资源"},
            expected_sha256=preview["sha256"],
            target_slug="shared-skill",
            publication_version="2.0.0",
        )
    )
    assert skill_identity(service.marketplace.published[-1]["content"]) == (
        "shared-skill",
        "2.0.0",
    )


def test_drafts_are_scoped_to_target_and_remember_last_source(tmp_path: Path) -> None:
    alice = _signed_in(tmp_path)
    _write_skill(tmp_path, "other-skill", OTHER_TEXT)
    alice.skill_manager.reload()
    fields = {
        "license": "MIT",
        "display_name": "线上资源",
        "author_name": "北辰",
        "summary": "A 的简介",
        "functional_category": "novel",
        "primary_locale": "zh-CN",
        "tags_csv": "writing",
        "release_notes": "",
    }
    saved = asyncio.run(
        alice.save_publish_draft(
            "shared-skill",
            expected_revision=None,
            base_version="0.9.0",
            base_sha256=hashlib.sha256(OTHER_TEXT.encode()).hexdigest(),
            fields=fields,
            source_skill_id="other-skill",
            publication_version="1.3.0",
        )
    )["draft"]
    loaded = asyncio.run(alice.get_publish_draft("shared-skill"))
    assert loaded["last_source_skill_id"] == "other-skill"
    assert loaded["draft"]["source_skill_id"] == "other-skill"
    assert loaded["draft"]["publication_version"] == "1.3.0"
    assert loaded["draft"]["fields"]["display_name"] == "线上资源"
    other_draft = asyncio.run(alice.get_publish_draft("other-skill"))
    assert other_draft["draft"] is None
    asyncio.run(
        alice.delete_publish_draft("shared-skill", expected_revision=saved["revision"])
    )
    remembered = asyncio.run(alice.get_publish_draft("shared-skill"))
    assert remembered["draft"] is None
    assert remembered["last_source_skill_id"] == "other-skill"


def test_account_switch_does_not_see_previous_target_draft(tmp_path: Path) -> None:
    alice = _signed_in(tmp_path, account=FakeAccount("access", subject="acct_alice"))
    _write_skill(tmp_path, "other-skill", OTHER_TEXT)
    alice.skill_manager.reload()
    asyncio.run(
        alice.save_publish_draft(
            "shared-skill",
            expected_revision=None,
            base_version="0.9.0",
            base_sha256=hashlib.sha256(OTHER_TEXT.encode()).hexdigest(),
            fields={
                "license": "MIT",
                "display_name": "Alice 的稿",
                "author_name": "Alice",
                "summary": "",
                "functional_category": "novel",
                "primary_locale": "zh-CN",
                "tags_csv": "",
                "release_notes": "",
            },
            source_skill_id="other-skill",
            publication_version="1.3.0",
        )
    )
    bob = _service(
        tmp_path,
        manager=alice.skill_manager,
        marketplace=alice.marketplace,
        account=FakeAccount("access", subject="acct_bob"),
    )
    isolated = asyncio.run(bob.get_publish_draft("shared-skill"))
    assert isolated["draft"] is None
    assert isolated["last_source_skill_id"] is None


def test_invalid_publication_version_is_rejected(tmp_path: Path) -> None:
    service = _signed_in(tmp_path)
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(
            service.preview_local_skill(
                "shared-skill",
                publication_version="not-a-version",
            )
        )
    assert error.value.code == "invalid_version"
    with pytest.raises(LocalSkillError) as publish_error:
        asyncio.run(
            service.publish(
                skill_id="shared-skill",
                resource_type="skill",
                license_id="MIT",
                rights_confirmed=True,
                terms_confirmed=True,
                terms_version="2026-09-06",
                metadata={},
                target_slug="shared-skill",
                publication_version="1.0",
            )
        )
    assert publish_error.value.code == "invalid_version"


def test_unprepared_publish_still_uploads_original_bytes(tmp_path: Path) -> None:
    service = _signed_in(tmp_path)
    asyncio.run(
        service.publish(
            skill_id="shared-skill",
            resource_type="skill",
            license_id="MIT",
            rights_confirmed=True,
            terms_confirmed=True,
            terms_version="2026-09-06",
            metadata={},
            expected_sha256=DIGEST,
        )
    )
    uploaded = service.marketplace.published[-1]
    assert uploaded["content"] == SKILL_TEXT.encode()
    assert "target_slug" not in uploaded or uploaded["target_slug"] is None


def _empty_manager_with_other(tmp_path: Path):
    manager = _empty_manager(tmp_path)
    _write_skill(tmp_path, "other-skill", OTHER_TEXT)
    manager.reload()
    return manager
