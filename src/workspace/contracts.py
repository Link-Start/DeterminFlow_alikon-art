"""Provider contract. A committed write survives disposal of application disks."""
from dataclasses import dataclass
from typing import Any, Protocol


class WorkspaceError(RuntimeError):
    def __init__(self, message: str, *, code: str = "workspace_unavailable", status_code: int = 503):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class WorkspaceRequest:
    scope: str
    operation: str
    path: str = ""
    content: bytes | None = None
    content_type: str = "application/octet-stream"
    expected_version: str | None = None
    idempotency_key: str = ""
    version: str | None = None
    offset: int = 0
    limit: int = 100
    query: str = ""


class WorkspaceProvider(Protocol):
    async def execute(self, request: WorkspaceRequest) -> dict[str, Any]: ...
    async def health(self) -> bool: ...


class WorkspaceScopeAuthorizer(Protocol):
    async def authorize(self, *, external_ref: str, workspace_scope: str,
                        operation: str, path: str, access: str) -> bool: ...
