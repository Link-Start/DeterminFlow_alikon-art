from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.skill_marketplace.errors import LocalSkillError
from src.skill_marketplace.publish_metadata import PUBLISH_TEXT_LIMITS
from src.skill_marketplace.routes import DraftFieldsBody, PublishMetadata
from marketplace_fixtures import FakeAccount, _service


@pytest.mark.parametrize("field,limit", PUBLISH_TEXT_LIMITS.items())
def test_publish_limits_count_unicode_and_preserve_legacy_drafts(field: str, limit: int):
    value = "𠮷" * limit
    assert PublishMetadata(**{field: value}).model_dump()[field] == value
    with pytest.raises(ValidationError):
        PublishMetadata(**{field: value + "字"})
    assert DraftFieldsBody(**{field: value + "字"}).model_dump()[field] == value + "字"


@pytest.mark.parametrize("field,limit", PUBLISH_TEXT_LIMITS.items())
def test_publish_service_rejects_overlong_text_before_upload(tmp_path: Path, field: str, limit: int):
    service = _service(tmp_path, account=FakeAccount("access"))
    payload = dict(skill_id="shared-skill", resource_type="skill", license_id="MIT",
                   rights_confirmed=True, terms_confirmed=True, terms_version="2026-09-06")
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(service.publish(**payload, metadata={field: "𠮷" * (limit + 1)}))
    assert error.value.code == "invalid_metadata"
    assert field in str(error.value)
    assert service.marketplace.published == []
    asyncio.run(service.publish(**payload, metadata={field: "𠮷" * limit}))
    assert service.marketplace.published[0]["metadata"][field] == "𠮷" * limit
