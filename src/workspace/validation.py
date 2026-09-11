"""Bounded logical paths; no host filesystem paths cross the provider boundary."""
import re
import unicodedata
from dataclasses import fields
from src.workspace.contracts import WorkspaceError, WorkspaceRequest

OPERATIONS = frozenset({"status", "list", "stat", "read", "read_text", "search", "write", "delete", "versions"})
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS = 12000


def invalid(message: str) -> WorkspaceError:
    return WorkspaceError(message, code="workspace_invalid", status_code=422)


def valid_scope(scope: object) -> bool:
    return isinstance(scope, str) and re.fullmatch(r"[0-9a-f]{64}", scope) is not None


def validate_request(scope: str, operation: str, values: dict) -> WorkspaceRequest:
    if not valid_scope(scope) or operation not in OPERATIONS:
        raise invalid("工作区或操作无效")
    allowed = {field.name for field in fields(WorkspaceRequest)} - {"scope", "operation"}
    if set(values) - allowed:
        raise invalid("工作区参数包含未知字段")
    request = WorkspaceRequest(scope=scope, operation=operation, **values)
    path = request.path
    if not isinstance(path, str) or len(path) > 1024:
        raise invalid("文件路径无效")
    if path:
        if (path.startswith("/") or "\\" in path or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in path)
                or any(part in {"", ".", ".."} for part in path.split("/"))):
            raise invalid("文件路径必须是相对路径")
    elif operation not in {"status", "list", "search"}:
        raise invalid("文件路径不能为空")
    if len(path.encode("utf-8")) > 1024:
        raise invalid("文件路径过长")
    if operation == "status" and path:
        raise invalid("状态查询不能指定文件")
    max_limit = MAX_TEXT_CHARS if operation == "read_text" else 100
    if (type(request.offset) is not int or not 0 <= request.offset <= 100_000_000
            or type(request.limit) is not int or not 1 <= request.limit <= max_limit):
        raise invalid("读取范围无效")
    if not isinstance(request.query, str) or len(request.query) > 500:
        raise invalid("搜索内容过长")
    for value in (request.expected_version, request.version):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value)):
            raise invalid("文件版本无效")
    if not isinstance(request.idempotency_key, str) or len(request.idempotency_key) > 128:
        raise invalid("保存请求标识无效")
    if operation in {"write", "delete"} and not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", request.idempotency_key):
        raise invalid("保存请求必须提供幂等标识")
    if operation == "delete" and not request.expected_version:
        raise invalid("删除必须提供当前版本")
    if (not isinstance(request.content_type, str) or len(request.content_type) > 200
            or any(ord(char) < 32 or ord(char) == 127 for char in request.content_type)):
        raise invalid("文件类型无效")
    if operation == "write":
        if not isinstance(request.content, bytes):
            raise invalid("保存内容必须是字节")
        if len(request.content) > MAX_FILE_BYTES:
            raise WorkspaceError("文件超过大小限制", code="workspace_too_large", status_code=413)
    elif request.content is not None:
        raise invalid("此操作不接受文件内容")
    return request
