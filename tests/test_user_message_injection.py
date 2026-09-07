from typing import Any

import pytest

from src import config
from src.agent import session
from src.agent.message_context import compose_user_model_content


def test_injection_builder_returns_enabled_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "USER_MESSAGE_INJECTION_ENABLED", True)
    monkeypatch.setattr(
        session,
        "_load_user_injection_config",
        lambda: {
            "sections": [
                {
                    "name": "request-time",
                    "content": "date={{date}}",
                    "enabled": True,
                    "order": 0,
                    "token_estimate": 3,
                }
            ]
        },
    )

    content, metadata = session._build_injection_content()

    assert content.startswith("date=")
    assert metadata == [
        {
            "name": "request-time",
            "content": content,
            "token_estimate": 3,
        }
    ]


def test_injection_builder_skips_all_sections_when_master_switch_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "USER_MESSAGE_INJECTION_ENABLED", False)

    def fail_if_loaded() -> dict[str, Any]:
        raise AssertionError("disabled injection must not load section configuration")

    monkeypatch.setattr(session, "_load_user_injection_config", fail_if_loaded)

    assert session._build_injection_content() == ("", [])


def test_disabled_injection_still_composes_product_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "USER_MESSAGE_INJECTION_ENABLED", False)
    model_context = {
        "locale": "zh-CN",
        "page_context": {"surface": "workbench", "resource_key": None},
        "confirmed_action_observation": None,
    }

    injection_content, injection_meta = session._build_injection_content()
    model_content = compose_user_model_content(
        "查看当前作品",
        model_context=model_context,
        injection_meta=injection_meta,
    )

    assert injection_content == ""
    assert injection_meta == []
    assert "<SYSTEM_INJECTION>" not in model_content
    assert model_content.startswith("<PRODUCT_CONTEXT>\n")
    assert '"resource_key":null' in model_content
    assert model_content.endswith(
        "<USER_MESSAGE>\n查看当前作品\n</USER_MESSAGE>"
    )


def test_product_context_is_composed_for_model_without_replacing_display_content() -> None:
    model_context = {
        "locale": "zh-CN",
        "page_context": {"surface": "workbench", "resource_key": None},
        "confirmed_action_observation": None,
    }

    model_content = compose_user_model_content(
        "查看当前作品",
        model_context=model_context,
    )

    assert model_content.startswith("<PRODUCT_CONTEXT>\n")
    assert '"resource_key":null' in model_content
    assert '"confirmed_action_observation":null' in model_content
    assert model_content.endswith(
        "<USER_MESSAGE>\n查看当前作品\n</USER_MESSAGE>"
    )


def test_record_restore_rebuilds_identical_model_input_from_structured_snapshot() -> None:
    model_context = {
        "locale": "zh-CN",
        "page_context": {"surface": "workbench", "resource_key": None},
    }
    original = session.AgentSession(session_type="sub", agent_type="test")
    original.record = [
        {
            "id": "msg_00001",
            "type": "user",
            "content": "查看当前作品",
            "model_context": model_context,
        }
    ]

    original._restore_lc_from_record()
    first_model_input = original.lc_messages[-1].content
    serialized = original._serialize_lc_messages(original.lc_messages)

    assert original.record[0]["content"] == "查看当前作品"
    assert serialized[-1]["content"] == "查看当前作品"
    assert serialized[-1]["model_context"] == model_context

    restored = session.AgentSession(session_type="sub", agent_type="test")
    restored.context = {"messages": serialized}
    restored._restore_lc_from_context()
    assert restored.lc_messages[-1].content == first_model_input
