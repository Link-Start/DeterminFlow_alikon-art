import json

from src.core.utils import estimate_tokens
from src.memory.contracts import MemoryRuntimePolicy
from src.memory.settings import MemorySettingsStore, default_memory_settings, read_legacy_runtime_settings
from src.memory.turns import snapshot_token_count, turn_token_count
from tests.test_memory_runtime import FakeProvider, _policy, _runtime


def test_estimate_accounts_for_language_and_tool_arguments():
    chinese = [{"content": "中文" * 100}]
    english = [{"content": "ab" * 100}]
    assert turn_token_count(chinese) > turn_token_count(english)
    calls = [{"name": "lookup", "args": {"query": "历史资料" * 50}}]
    assert turn_token_count([{**english[0], "tool_calls": calls}]) == (
        estimate_tokens(english[0]["content"]) + estimate_tokens(json.dumps(calls, ensure_ascii=False))
    )


def test_legacy_snapshot_recounts_messages_not_char_count():
    snapshot = {"char_count": 999999, "messages": [{"content": "hello"}]}
    assert snapshot_token_count(snapshot) == estimate_tokens("hello")
    assert snapshot_token_count({**snapshot, "estimated_tokens": 10}) == 10


def test_migrate_old_settings_once_without_losing_other_values(tmp_path):
    path = tmp_path / "settings.json"
    values = default_memory_settings().to_dict()
    values.pop("consolidate_length_tokens")
    values.update(consolidate_length_chars=12345, extract_model="custom:model", enabled=False)
    path.write_text(json.dumps({"version": 1, "settings": values}))
    saved = MemorySettingsStore(path).persisted_settings()
    assert saved.consolidate_length_tokens == 12345
    assert saved.extract_model == "custom:model"
    assert not saved.enabled
    persisted = json.loads(path.read_text())
    assert persisted["version"] == 2
    assert "consolidate_length_chars" not in persisted["settings"]
    assert MemorySettingsStore(path).persisted_settings() == saved


def test_new_token_setting_wins_over_legacy():
    provider = FakeProvider()
    provider.legacy_runtime_settings = lambda: {"consolidate_length_chars": 9000, "consolidate_length_tokens": 8000}
    assert read_legacy_runtime_settings(provider)["consolidate_length_tokens"] == 8000


def test_trigger_uses_all_pending_tokens_and_recomputes_old_snapshots(tmp_path):
    policy = _policy(consolidate_length_tokens=100, consolidate_idle_seconds=86400)
    runtime = _runtime(tmp_path, FakeProvider(policy))
    from src.memory.store import utc_now_iso
    turns = [
        {"partition": "p", "char_count": 999999, "messages": [{"content": "ab" * 100}]},
        {"partition": "p", "messages": [{"content": "ab" * 100}]},
    ]
    ledger = {"activity_at": utc_now_iso(), "turns": turns}
    assert runtime._trigger_met(ledger, turns[:1], policy)
    ledger["turns"] = turns[:1]
    assert not runtime._trigger_met(ledger, turns[:1], policy)
    ledger["turns"] = [dict(turns[0], messages=[{"content": "中文" * 100}])]
    assert runtime._trigger_met(ledger, ledger["turns"], policy)


def test_invalid_legacy_threshold_fails_closed(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"settings": {"enabled": True, "external_enabled": True,
                                           "consolidate_length_chars": None}}))
    store = MemorySettingsStore(path)
    assert not store.persisted_settings().external_enabled
    assert store.read_error
