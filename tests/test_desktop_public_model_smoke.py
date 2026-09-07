import pytest
from desktop.scripts.smoke_backend import _assert_public_model_status


def test_first_run_public_model_can_wait_for_explicit_activation():
    _assert_public_model_status({"state": "unavailable", "ui": {"service_enabled": True}, "header_status": {"visible": True}})


def test_packaging_rejects_platform_disabled_public_plugin():
    with pytest.raises(RuntimeError, match="桌面平台不可用"):
        _assert_public_model_status({"state": "disabled", "last_error": "unsupported platform", "ui": {"service_enabled": True}, "header_status": {"visible": True}})


def test_packaging_rejects_missing_public_header():
    with pytest.raises(RuntimeError, match="状态入口"):
        _assert_public_model_status({"state": "unavailable", "header_status": None})
