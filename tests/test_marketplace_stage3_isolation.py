"""Independent regressions for account changes and local draft path isolation."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from marketplace_fixtures import FakeAccount, _service
from src.skill_marketplace.drafts import PublishDraftStore, partition_key
from src.skill_marketplace.errors import LocalSkillError

FIELDS = {"license": "MIT", "display_name": "Example", "author_name": "Owner", "summary": "Private draft"}
SCOPE = {"issuer": "https://accounts.example", "subject": "owner-a", "marketplace_origin": "https://marketplace.example", "skill_id": "shared-skill"}


async def _assert_symlink_isolation(tmp_path: Path) -> None:
    store = PublishDraftStore(tmp_path / "drafts")
    draft = await store.save(**SCOPE, expected_revision=None, base_version="1.0.0", base_sha256="a" * 64, fields=FIELDS)
    other = {**SCOPE, "subject": "owner-b"}
    owner_path = store.root / partition_key(SCOPE["issuer"], SCOPE["subject"], SCOPE["marketplace_origin"])
    other_path = store.root / partition_key(other["issuer"], other["subject"], other["marketplace_origin"])
    other_path.symlink_to(owner_path, target_is_directory=True)
    for operation in (lambda: store.get(**other), lambda: store.delete(**other, expected_revision=draft["revision"])):
        with pytest.raises(LocalSkillError):
            await operation()
    draft_row, _last_source = await store.get(**SCOPE)
    assert draft_row is not None
    assert draft_row["revision"] == 1


class ChangingAccount(FakeAccount):
    subject = "owner-a"

    def local_identity_claims(self) -> tuple[str, str]:
        return SCOPE["issuer"], self.subject


async def _assert_account_switch(tmp_path: Path, operation: str) -> None:
    account = ChangingAccount("owner-a-token")
    account.subject = "owner-a"
    service = _service(tmp_path, account=account)
    await service.save_publish_draft("shared-skill", expected_revision=None, base_version="1.0.0", base_sha256="a" * 64, fields=FIELDS)
    await service._drafts._lock.acquire()
    task = None
    try:
        if operation == "get":
            task = asyncio.create_task(service.get_publish_draft("shared-skill"))
        elif operation == "save":
            task = asyncio.create_task(service.save_publish_draft("shared-skill", expected_revision=1, base_version="1.0.1", base_sha256="b" * 64, fields=FIELDS))
        else:
            task = asyncio.create_task(service.delete_publish_draft("shared-skill", expected_revision=1))
        await asyncio.sleep(0)
        assert not task.done()
        account.subject = "owner-b"
        account._access_token = "owner-b-token"
    finally:
        service._drafts._lock.release()
    assert task is not None
    with pytest.raises(LocalSkillError) as caught:
        await task
    assert caught.value.status_code == 401
    account.subject = "owner-a"
    account._access_token = "owner-a-token"
    restored = await service.get_publish_draft("shared-skill")
    assert restored["draft"]["revision"] == 1


def test_draft_partition_symlink_cannot_read_or_delete_another_accounts_file(tmp_path: Path) -> None:
    asyncio.run(_assert_symlink_isolation(tmp_path))


@pytest.mark.parametrize("operation", ["get", "save", "delete"])
def test_queued_draft_operation_fails_after_account_switch(tmp_path: Path, operation: str) -> None:
    asyncio.run(_assert_account_switch(tmp_path, operation))


def test_preview_uses_the_version_in_the_exact_file_bytes(tmp_path: Path) -> None:
    from marketplace_fixtures import SKILL_TEXT
    service = _service(tmp_path, account=FakeAccount("access"))
    skill = service.skill_manager.get_skill("shared-skill")
    assert skill is not None and skill.version == "1.2.3"
    path = Path(skill.metadata["skill_dir"]) / "SKILL.md"
    path.write_text(SKILL_TEXT.replace("1.2.3", "1.2.4"), encoding="utf-8")
    preview = asyncio.run(service.preview_local_skill("shared-skill"))
    assert preview["version"] == "1.2.4"
    assert "1.2.4" in preview["content"]
    eligible = asyncio.run(service.eligible_local_skills())
    assert eligible[0]["version"] == "1.2.4"
    assert eligible[0]["sha256"] == preview["sha256"]


def test_review_proxy_preserves_explicit_null_current_pin() -> None:
    import json
    import httpx
    from src.skill_marketplace.portal import ResourceMarketplaceClient
    bodies = []
    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "published"})
    client = ResourceMarketplaceClient("https://marketplace.example", app_version="test", transport=httpx.MockTransport(handle))
    args = {"decision": "approve", "expected_sha256": "a" * 64, "reason": None, "access_token": "test-access"}
    asyncio.run(client.review_version("11111111-1111-4111-8111-111111111111", **args))
    asyncio.run(client.review_version("11111111-1111-4111-8111-111111111111", **args, expected_current_version_provided=True))
    assert "expected_current_version_id" not in bodies[0]
    assert bodies[1]["expected_current_version_id"] is None
