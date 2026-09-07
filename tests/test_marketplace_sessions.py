import asyncio
import json
from pathlib import Path

import pytest

from src.account.portal import AccountRequestError
from src.account.service import CoreAccountService
from src.skill_marketplace.portal import MarketplaceRequestError
from src.skill_marketplace.service import LocalSkillError, SkillMarketplaceService
from src.skills.config_manager import SkillConfigManager
from src.skills.manager import SkillManager


class BrowserLogin:
    async def authorize(self, *_args):
        return {"access_token": "new-user", "refresh_token": "new-user-refresh"}


class AccountPortal:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.refresh_count = 0
        self.refresh_fails = False

    async def refresh(self, _token):
        self.refresh_count += 1
        self.started.set()
        await self.release.wait()
        if self.refresh_fails:
            raise AccountRequestError(
                "authentication_failed", "old refresh revoked", status_code=401,
            )
        return {"access_token": "renewed", "refresh_token": "rotated"}

    async def logout(self, _token):
        return None


class Marketplace:
    base_url = "https://marketplace.example"


def _services(tmp_path: Path, portal: AccountPortal):
    account = CoreAccountService(
        data_dir=tmp_path / "data",
        portal=portal,  # type: ignore[arg-type]
        browser_auth=BrowserLogin(),  # type: ignore[arg-type]
    )
    account._replace_session({
        "access_token": "expired",
        "refresh_token": "refresh",
    })
    marketplace = SkillMarketplaceService(
        data_dir=tmp_path / "data",
        skill_manager=SkillManager(
            tmp_path / "skills", SkillConfigManager(tmp_path / "config.json"),
        ),
        marketplace=Marketplace(),  # type: ignore[arg-type]
        account_session=account,
    )
    return account, marketplace


def test_logout_cannot_be_undone_by_inflight_token_refresh(tmp_path: Path):
    async def run():
        portal = AccountPortal()
        account, marketplace = _services(tmp_path, portal)

        async def operation(access_token: str):
            if access_token == "expired":
                portal.started.set()
                await portal.release.wait()
                raise MarketplaceRequestError(
                    "authentication_failed", "expired", status_code=401,
                )
            return {"private": "old account data"}

        pending = asyncio.create_task(marketplace._authenticated_request(operation))
        await portal.started.wait()
        await account.logout()
        portal.release.set()
        result = await asyncio.gather(pending, return_exceptions=True)
        assert account.status()["signed_in"] is False
        assert isinstance(result[0], LocalSkillError)

    asyncio.run(run())


@pytest.mark.parametrize("refresh_fails", [False, True])
def test_old_refresh_cannot_overwrite_or_clear_new_login(
    tmp_path: Path,
    refresh_fails: bool,
):
    async def run():
        portal = AccountPortal()
        portal.refresh_fails = refresh_fails
        account, marketplace = _services(tmp_path, portal)

        async def operation(access_token: str):
            if access_token == "expired":
                raise MarketplaceRequestError(
                    "authentication_failed", "expired", status_code=401,
                )
            return access_token

        pending = asyncio.create_task(marketplace._authenticated_request(operation))
        await portal.started.wait()
        await account.login()
        portal.release.set()

        result = await asyncio.gather(pending, return_exceptions=True)
        assert isinstance(result[0], LocalSkillError)
        assert result[0].code == "login_required"
        assert account.access_token() == "new-user"

    asyncio.run(run())


def test_same_session_rotation_does_not_reject_successful_request(tmp_path: Path):
    async def run():
        portal = AccountPortal()
        portal.release.set()
        account, marketplace = _services(tmp_path, portal)
        started = asyncio.Event()
        release = asyncio.Event()

        async def operation(access_token: str):
            started.set()
            await release.wait()
            return f"ok:{access_token}"

        pending = asyncio.create_task(marketplace._authenticated_request(operation))
        await started.wait()
        assert await account.refresh_access_token("expired") == "renewed"
        release.set()
        assert await pending == "ok:expired"
        assert account.access_token() == "renewed"
        assert portal.refresh_count == 1

    asyncio.run(run())


def test_parallel_expired_requests_share_one_rotating_refresh(tmp_path: Path):
    async def run():
        portal = AccountPortal()
        account, marketplace = _services(tmp_path, portal)
        expired_calls = 0
        both_expired = asyncio.Event()

        async def operation(access_token: str):
            nonlocal expired_calls
            if access_token == "expired":
                expired_calls += 1
                if expired_calls == 2:
                    both_expired.set()
                await both_expired.wait()
                raise MarketplaceRequestError(
                    "authentication_failed", "expired", status_code=401,
                )
            return "success"

        pending = asyncio.gather(
            marketplace._authenticated_request(operation),
            marketplace._authenticated_request(operation),
        )
        await portal.started.wait()
        portal.release.set()
        assert await pending == ["success", "success"]
        assert portal.refresh_count == 1
        assert account.status()["signed_in"] is True

    asyncio.run(run())


def test_marketplace_migration_removes_legacy_tokens(tmp_path: Path):
    state_path = tmp_path / "data" / "resource-marketplace" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "schema_version": 2,
        "installation_id": "desktop:legacy",
        "marketplace_session": {
            "access_token": "legacy-access",
            "refresh_token": "legacy-refresh",
        },
    }), encoding="utf-8")

    SkillMarketplaceService(
        data_dir=tmp_path / "data",
        skill_manager=SkillManager(
            tmp_path / "skills", SkillConfigManager(tmp_path / "config.json"),
        ),
        marketplace=Marketplace(),  # type: ignore[arg-type]
    )

    migrated = json.loads(state_path.read_text(encoding="utf-8"))
    assert migrated["installation_id"] == "desktop:legacy"
    assert migrated["marketplace_session"] is None
