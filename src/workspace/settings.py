"""Durable Core switches, separate from plugin-owned storage configuration."""
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from src.plugin_system.models import validate_plugin_id


@dataclass(frozen=True)
class WorkspaceSettings:
    enabled: bool = False
    provider_id: str = ""
    context_enabled: bool = True
    context_token_budget: int = 2000
    timeout_seconds: float = 15
    local_main_enabled: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def parse_workspace_settings(raw: dict) -> WorkspaceSettings:
    if not isinstance(raw, dict) or set(raw) - WorkspaceSettings.__dataclass_fields__.keys():
        raise ValueError("工作区配置包含未知字段")
    values = {**WorkspaceSettings().to_dict(), **raw}
    for key in ("enabled", "context_enabled", "local_main_enabled"):
        if type(values[key]) is not bool:
            raise ValueError("工作区开关必须是布尔值")
    provider = values["provider_id"]
    if not isinstance(provider, str):
        raise ValueError("工作区提供者无效")
    if provider:
        validate_plugin_id(provider)
    tokens = values["context_token_budget"]
    if type(tokens) is not int or not 256 <= tokens <= 8000:
        raise ValueError("上下文预算必须为 256 至 8000 token")
    timeout = values["timeout_seconds"]
    if type(timeout) not in (float, int) or not 1 <= timeout <= 120:
        raise ValueError("工作区超时必须为 1 至 120 秒")
    return WorkspaceSettings(**values)


class WorkspaceSettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path
        self._settings = None
        self.read_error = False

    def load(self) -> WorkspaceSettings:
        if self._settings is not None:
            return self._settings
        if self.path is None or not self.path.exists():
            return WorkspaceSettings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._settings = parse_workspace_settings(raw["settings"])
        except (OSError, ValueError, KeyError, TypeError):
            self.read_error = True
            return WorkspaceSettings()
        return self._settings

    def save(self, settings: WorkspaceSettings) -> None:
        settings = parse_workspace_settings(settings.to_dict())
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(prefix=".workspace-settings-", dir=self.path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump({"version": 1, "settings": settings.to_dict()}, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(name, self.path)
            finally:
                Path(name).unlink(missing_ok=True)
        self._settings = settings
        self.read_error = False
