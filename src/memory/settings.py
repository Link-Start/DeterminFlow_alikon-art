"""Durable provider-neutral Core memory settings."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from src.memory.contracts import MemoryRuntimePolicy, RECALL_EVERY, RECALL_FIRST
from src.plugin_system.models import validate_plugin_id

logger = logging.getLogger(__name__)

MEMORY_SETTINGS_VERSION = 2
GENERIC_SETTING_KEYS: tuple[str, ...] = (
    "auto_recall_enabled",
    "recall_mode",
    "recall_timeout_seconds",
    "recall_max_chars",
    "recall_max_bytes",
    "auto_consolidate_enabled",
    "consolidate_idle_seconds",
    "consolidate_length_tokens",
    "max_batch_turns",
    "max_concurrent_jobs",
    "max_retries",
    "lease_seconds",
    "extract_timeout_seconds",
    "extract_model",
)
SELECTION_SETTING_KEYS: tuple[str, ...] = (
    "enabled",
    "external_enabled",
    "provider_id",
)
MEMORY_SETTING_KEYS: tuple[str, ...] = SELECTION_SETTING_KEYS + GENERIC_SETTING_KEYS
MEMORY_SETTING_KEY_SET = frozenset(MEMORY_SETTING_KEYS)
GENERIC_SETTING_KEY_SET = frozenset(GENERIC_SETTING_KEYS)

MEMORY_SETTINGS_SCHEMA: dict[str, dict[str, Any]] = {
    "enabled": {
        "type": "boolean",
        "default": True,
        "title": "启用记忆",
        "description": "关闭后停止自动召回、记忆工具和后台整理。",
    },
    "external_enabled": {
        "type": "boolean",
        "default": False,
        "title": "启用外部记忆",
        "description": "允许使用已注册的外部记忆提供者。",
    },
    "provider_id": {
        "type": "string",
        "default": "",
        "title": "记忆提供者",
        "description": "当前选中的记忆提供者 Plugin ID。",
    },
    "auto_recall_enabled": {
        "type": "boolean",
        "default": True,
        "title": "自动召回",
        "description": "把召回结果写入当前轮模型上下文。",
    },
    "recall_mode": {
        "type": "string",
        "enum": [RECALL_FIRST, RECALL_EVERY],
        "default": RECALL_EVERY,
        "title": "召回时机",
        "description": "first 只在首次有效输入召回，every 每个有效回合召回。",
    },
    "recall_timeout_seconds": {
        "type": "number",
        "minimum": 0.1,
        "maximum": 30,
        "default": 5,
        "title": "召回超时（秒）",
        "description": "单次自动召回总超时，超时前台 fail-open。",
    },
    "recall_max_chars": {
        "type": "integer",
        "minimum": 500,
        "maximum": 50000,
        "default": 4000,
        "title": "召回最大字符",
        "description": "写入模型上下文的记忆正文总字符预算。",
    },
    "recall_max_bytes": {
        "type": "integer",
        "minimum": 1000,
        "maximum": 64000,
        "default": 8000,
        "title": "召回最大字节",
        "description": "写入模型上下文的记忆 JSON 总字节预算。",
    },
    "auto_consolidate_enabled": {
        "type": "boolean",
        "default": True,
        "title": "自动整理",
        "description": "空闲或未处理长度触发异步抽取。仍需 Agent 选择加入。",
    },
    "consolidate_idle_seconds": {
        "type": "integer",
        "minimum": 60,
        "maximum": 86400,
        "default": 1800,
        "title": "整理空闲（秒）",
        "description": "会话沉寂多少秒后触发抽取。",
    },
    "consolidate_length_tokens": {
        "type": "integer",
        "minimum": 1000,
        "maximum": 500000,
        "default": 20000,
        "title": "整理长度（估算 token）",
        "description": "未处理完整轮次的估算 token 达到该值时触发抽取。",
    },
    "max_batch_turns": {
        "type": "integer",
        "minimum": 1,
        "maximum": 50,
        "default": 8,
        "title": "单批最大轮次",
        "description": "单次抽取最多处理的完整轮次数。",
    },
    "max_concurrent_jobs": {
        "type": "integer",
        "minimum": 1,
        "maximum": 8,
        "default": 2,
        "title": "最大并发任务",
        "description": "同时进行的抽取任务上限。",
    },
    "max_retries": {
        "type": "integer",
        "minimum": 1,
        "maximum": 10,
        "default": 3,
        "title": "最大重试次数",
        "description": "抽取或写入失败后的有界重试次数。",
    },
    "lease_seconds": {
        "type": "integer",
        "minimum": 30,
        "maximum": 3600,
        "default": 120,
        "title": "任务租约（秒）",
        "description": "抽取任务租约，超时后可被重启恢复。",
    },
    "extract_timeout_seconds": {
        "type": "number",
        "minimum": 5,
        "maximum": 300,
        "default": 60,
        "title": "抽取超时（秒）",
        "description": "抽取 Agent 单次调用超时。",
    },
    "extract_model": {
        "type": "string",
        "default": "",
        "title": "抽取模型",
        "description": "可选抽取模型覆盖；空则跟随 Agent 或默认模型。",
    },
}


@dataclass(frozen=True)
class MemorySettings:
    enabled: bool
    external_enabled: bool
    provider_id: str
    auto_recall_enabled: bool
    recall_mode: str
    recall_timeout_seconds: float
    recall_max_chars: int
    recall_max_bytes: int
    auto_consolidate_enabled: bool
    consolidate_idle_seconds: int
    consolidate_length_tokens: int
    max_batch_turns: int
    max_concurrent_jobs: int
    max_retries: int
    lease_seconds: int
    extract_timeout_seconds: float
    extract_model: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "external_enabled": self.external_enabled,
            "provider_id": self.provider_id,
            "auto_recall_enabled": self.auto_recall_enabled,
            "recall_mode": self.recall_mode,
            "recall_timeout_seconds": self.recall_timeout_seconds,
            "recall_max_chars": self.recall_max_chars,
            "recall_max_bytes": self.recall_max_bytes,
            "auto_consolidate_enabled": self.auto_consolidate_enabled,
            "consolidate_idle_seconds": self.consolidate_idle_seconds,
            "consolidate_length_tokens": self.consolidate_length_tokens,
            "max_batch_turns": self.max_batch_turns,
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "max_retries": self.max_retries,
            "lease_seconds": self.lease_seconds,
            "extract_timeout_seconds": self.extract_timeout_seconds,
            "extract_model": self.extract_model,
        }

    def enables_external(self) -> bool:
        return bool(self.enabled and self.external_enabled)


def default_memory_settings() -> MemorySettings:
    return MemorySettings(
        enabled=True,
        external_enabled=False,
        provider_id="",
        auto_recall_enabled=True,
        recall_mode=RECALL_EVERY,
        recall_timeout_seconds=5.0,
        recall_max_chars=4000,
        recall_max_bytes=8000,
        auto_consolidate_enabled=True,
        consolidate_idle_seconds=1800,
        consolidate_length_tokens=20000,
        max_batch_turns=8,
        max_concurrent_jobs=2,
        max_retries=3,
        lease_seconds=120,
        extract_timeout_seconds=60.0,
        extract_model="",
    )


def _boolean(name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{name} 必须是 boolean")


def _number(name: str, value: Any, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是 number")
    parsed = float(value)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} 必须在 {minimum} 到 {maximum} 之间")
    return parsed


def _integer(name: str, value: Any, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是 integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float) and value.is_integer():
        parsed = int(value)
    else:
        raise ValueError(f"{name} 必须是 integer")
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} 必须在 {minimum} 到 {maximum} 之间")
    return parsed


def _string(name: str, value: Any, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} 必须是 string")
    text = value.strip()
    if not text and not allow_empty:
        raise ValueError(f"{name} 不能为空")
    return text


def parse_memory_settings(
    values: Mapping[str, Any] | None,
    *,
    unknown: str = "reject",
) -> MemorySettings:
    if values is None:
        source: dict[str, Any] = {}
    elif isinstance(values, Mapping):
        source = dict(values)
    else:
        raise ValueError("memory settings 必须是 object")
    extra = sorted(set(source) - MEMORY_SETTING_KEY_SET)
    if extra and unknown == "reject":
        raise ValueError("memory settings 包含未知字段: " + ", ".join(extra))
    defaults = default_memory_settings()
    recall_mode = _string(
        "recall_mode",
        source.get("recall_mode", defaults.recall_mode),
    )
    if recall_mode not in {RECALL_FIRST, RECALL_EVERY}:
        raise ValueError("recall_mode 必须是 first 或 every")
    provider_id = _string(
        "provider_id",
        source.get("provider_id", defaults.provider_id),
        allow_empty=True,
    )
    if provider_id:
        try:
            provider_id = validate_plugin_id(provider_id)
        except ValueError as exc:
            raise ValueError("provider_id 必须是小写 kebab-case Plugin ID") from exc
    return MemorySettings(
        enabled=_boolean("enabled", source.get("enabled", defaults.enabled)),
        external_enabled=_boolean(
            "external_enabled",
            source.get("external_enabled", defaults.external_enabled),
        ),
        provider_id=provider_id,
        auto_recall_enabled=_boolean(
            "auto_recall_enabled",
            source.get("auto_recall_enabled", defaults.auto_recall_enabled),
        ),
        recall_mode=recall_mode,
        recall_timeout_seconds=_number(
            "recall_timeout_seconds",
            source.get("recall_timeout_seconds", defaults.recall_timeout_seconds),
            minimum=0.1,
            maximum=30,
        ),
        recall_max_chars=_integer(
            "recall_max_chars",
            source.get("recall_max_chars", defaults.recall_max_chars),
            minimum=500,
            maximum=50000,
        ),
        recall_max_bytes=_integer(
            "recall_max_bytes",
            source.get("recall_max_bytes", defaults.recall_max_bytes),
            minimum=1000,
            maximum=64000,
        ),
        auto_consolidate_enabled=_boolean(
            "auto_consolidate_enabled",
            source.get("auto_consolidate_enabled", defaults.auto_consolidate_enabled),
        ),
        consolidate_idle_seconds=_integer(
            "consolidate_idle_seconds",
            source.get("consolidate_idle_seconds", defaults.consolidate_idle_seconds),
            minimum=60,
            maximum=86400,
        ),
        consolidate_length_tokens=_integer(
            "consolidate_length_tokens",
            source.get("consolidate_length_tokens", defaults.consolidate_length_tokens),
            minimum=1000,
            maximum=500000,
        ),
        max_batch_turns=_integer(
            "max_batch_turns",
            source.get("max_batch_turns", defaults.max_batch_turns),
            minimum=1,
            maximum=50,
        ),
        max_concurrent_jobs=_integer(
            "max_concurrent_jobs",
            source.get("max_concurrent_jobs", defaults.max_concurrent_jobs),
            minimum=1,
            maximum=8,
        ),
        max_retries=_integer(
            "max_retries",
            source.get("max_retries", defaults.max_retries),
            minimum=1,
            maximum=10,
        ),
        lease_seconds=_integer(
            "lease_seconds",
            source.get("lease_seconds", defaults.lease_seconds),
            minimum=30,
            maximum=3600,
        ),
        extract_timeout_seconds=_number(
            "extract_timeout_seconds",
            source.get("extract_timeout_seconds", defaults.extract_timeout_seconds),
            minimum=5,
            maximum=300,
        ),
        extract_model=_string(
            "extract_model",
            source.get("extract_model", defaults.extract_model),
            allow_empty=True,
        ),
    )


def overlay_memory_policy(
    policy: MemoryRuntimePolicy,
    settings: MemorySettings,
) -> MemoryRuntimePolicy:
    """Replace generic Core-owned fields; leave provider-owned fields intact."""

    return replace(
        policy,
        auto_recall_enabled=settings.auto_recall_enabled,
        recall_mode=settings.recall_mode,  # type: ignore[arg-type]
        recall_timeout_seconds=settings.recall_timeout_seconds,
        recall_max_chars=settings.recall_max_chars,
        recall_max_bytes=settings.recall_max_bytes,
        auto_consolidate_enabled=settings.auto_consolidate_enabled,
        consolidate_idle_seconds=settings.consolidate_idle_seconds,
        consolidate_length_tokens=settings.consolidate_length_tokens,
        max_batch_turns=settings.max_batch_turns,
        max_concurrent_jobs=settings.max_concurrent_jobs,
        max_retries=settings.max_retries,
        lease_seconds=settings.lease_seconds,
        extract_timeout_seconds=settings.extract_timeout_seconds,
        extract_model=settings.extract_model,
    )


def safe_disabled_memory_settings() -> MemorySettings:
    defaults = default_memory_settings()
    return replace(defaults, enabled=True, external_enabled=False, provider_id="")


def migrate_legacy_length_setting(values: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the configured threshold number, explicitly changing its unit to tokens."""
    result = dict(values)
    had_legacy = "consolidate_length_chars" in result
    old = result.pop("consolidate_length_chars", None)
    if had_legacy and "consolidate_length_tokens" not in result:
        result["consolidate_length_tokens"] = old
    return result


def read_legacy_runtime_settings(provider: Any) -> dict[str, Any]:
    getter = getattr(provider, "legacy_runtime_settings", None)
    try:
        if callable(getter):
            raw = getter()
        else:
            # Core may restart before the adapter is upgraded. The existing
            # protocol already exposes the old effective generic values.
            policy_getter = getattr(provider, "runtime_policy", None)
            policy = policy_getter() if callable(policy_getter) else None
            raw = {
                key: getattr(policy, key) for key in (*GENERIC_SETTING_KEYS, "consolidate_length_chars")
                if policy is not None and hasattr(policy, key)
            }
    except Exception:
        logger.warning("legacy_runtime_settings() failed", exc_info=True)
        return {}
    if not isinstance(raw, Mapping):
        return {}
    raw = migrate_legacy_length_setting(raw)
    defaults = default_memory_settings().to_dict()
    merged: dict[str, Any] = {}
    for key in GENERIC_SETTING_KEYS:
        if key not in raw:
            continue
        candidate = dict(defaults)
        candidate[key] = raw[key]
        try:
            parsed = parse_memory_settings(candidate, unknown="reject")
        except (TypeError, ValueError):
            continue
        merged[key] = parsed.to_dict()[key]
    return merged


class MemorySettingsStore:
    """Persist Core memory settings. Missing path keeps tests in compat mode."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else None
        self._cached: MemorySettings | None = None
        self._unreadable = False

    def persisted_settings(self) -> MemorySettings | None:
        if self._unreadable:
            return safe_disabled_memory_settings()
        if self._cached is not None:
            return self._cached
        loaded = self._read()
        if loaded is not None:
            self._cached = loaded
            return loaded
        if self._unreadable:
            return safe_disabled_memory_settings()
        return None

    def save(self, settings: MemorySettings) -> MemorySettings:
        if not isinstance(settings, MemorySettings):
            raise ValueError("memory settings 无效")
        if self.path is not None:
            self._write(settings)
        self._cached = settings
        self._unreadable = False
        return settings

    @property
    def read_error(self) -> bool:
        return self._unreadable

    def migrate_from_providers(
        self,
        providers: Mapping[str, Any],
    ) -> MemorySettings | None:
        existing = self.persisted_settings()
        if existing is not None:
            return existing
        if self.path is None:
            return None
        if len(providers) != 1:
            return None
        provider_id, provider = next(iter(providers.items()))
        values = default_memory_settings().to_dict()
        values.update(read_legacy_runtime_settings(provider))
        values["enabled"] = True
        values["external_enabled"] = True
        values["provider_id"] = str(provider_id)
        settings = parse_memory_settings(values, unknown="ignore")
        return self.save(settings)

    def _read(self) -> MemorySettings | None:
        if self.path is None or not self.path.is_file():
            return None
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise ValueError("memory settings 文件必须是 object")
            raw_settings = document.get("settings", document)
            if not isinstance(raw_settings, Mapping):
                raise ValueError("memory settings.settings 必须是 object")
            migrated = migrate_legacy_length_setting(raw_settings)
            settings = parse_memory_settings(migrated, unknown="ignore")
            if "consolidate_length_chars" in raw_settings:
                self._write(settings)
            return settings
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            logger.error("memory settings 文件无效，已拒绝启用外部记忆", exc_info=True)
            self._unreadable = True
            return None

    def _write(self, settings: MemorySettings) -> None:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": MEMORY_SETTINGS_VERSION,
            "settings": settings.to_dict(),
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".memory-settings.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
