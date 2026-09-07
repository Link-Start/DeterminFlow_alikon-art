import io

import httpx
import pytest

from src.plugin_system import registry
from desktop.scripts.publish_r2_release import R2Publisher
from src.plugin_system.registry_release import (
    PluginRegistryReleaseError,
    S3CompatibleRegistryPublisher,
)


def test_download_identifies_the_registry_client(monkeypatch):
    def respond(request):
        assert request.headers["user-agent"] == registry.REGISTRY_USER_AGENT
        return httpx.Response(200, content=b"package")

    client = httpx.Client
    monkeypatch.setattr(
        registry.httpx, "Client",
        lambda **options: client(transport=httpx.MockTransport(respond), **options),
    )
    assert registry.https_get(
        "https://downloads.example.invalid/package.zip", max_bytes=20, timeout=1,
    ) == b"package"


def test_published_download_has_client_identity_and_checks_actual_bytes(tmp_path):
    package = tmp_path / "package.zip"
    package.write_bytes(b"package")
    payload = b"package"

    def fetch(request, **options):
        assert request.get_header("User-agent") == registry.REGISTRY_USER_AGENT
        assert request.get_header("Cache-control") == "no-cache"
        return io.BytesIO(payload)

    publisher = S3CompatibleRegistryPublisher(
        bucket="test", endpoint_url="https://storage.example.invalid",
        public_base_url="https://downloads.example.invalid", fetcher=fetch,
    )
    publisher._verify(package, "plugins/v1/package.zip")
    payload = b"stale-or-corrupt-package"
    with pytest.raises(PluginRegistryReleaseError, match="checksum mismatch"):
        publisher._verify(package, "plugins/v1/package.zip")


def test_desktop_distribution_verifies_bytes_with_client_identity(tmp_path):
    package = tmp_path / "installer.exe"
    package.write_bytes(b"installer")
    payload = b"installer"

    def fetch(request, **options):
        assert request.get_header("User-agent") == "DeterminFlow-Desktop-Release/1.0"
        return io.BytesIO(payload)

    publisher = R2Publisher(
        bucket="test", endpoint_url="https://storage.example.invalid",
        public_base_url="https://downloads.example.invalid", fetcher=fetch,
    )
    publisher._verify_public(package, "desktop/installer.exe")
    payload = b"corrupt"
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        publisher._verify_public(package, "desktop/installer.exe")
