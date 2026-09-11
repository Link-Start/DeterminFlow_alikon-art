"""Display metadata for inline files and resource references.

Only the matching text in the user message is sent to the model. Metadata never
loads a resource, grants a tool, or injects resource contents.
"""

from __future__ import annotations

RESOURCE_TYPES = frozenset({"prompt", "agent", "skill", "rule", "workflow", "session"})
MAX_ATTACHMENTS = 64


def _text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}无效")
    if len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label}过长或包含无效字符")
    return value


def validate_attachment(raw: object, content: str | None) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("附件信息格式无效")
    name = _text(raw.get("name"), "附件名称", 255)
    if "resource_type" in raw:
        resource_type = raw["resource_type"]
        if not isinstance(resource_type, str) or resource_type not in RESOURCE_TYPES:
            raise ValueError("资源类型无效")
        if "absolute_path" in raw:
            raise ValueError("资源引用不能同时包含文件路径字段")
        resource_id = _text(raw.get("resource_id"), "资源 ID", 1024)
        reference = _text(raw.get("reference_text"), "资源引用", 4096)
        if content is not None and reference not in content:
            raise ValueError("资源引用必须存在于消息正文中")
        return {
            "name": name,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "reference_text": reference,
        }

    path = _text(raw.get("absolute_path"), "附件路径", 4096)
    absolute = path.startswith("/") or (
        len(path) >= 3 and path[0].isalpha()
        and path[1] == ":" and path[2] in ("/", "\\")
    )
    if not absolute or (content is not None and path not in content):
        raise ValueError("附件绝对路径必须存在于消息正文中")
    return {"name": name, "absolute_path": path}


def validate_message_attachments(raw: object, content: str) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("attachments 必须是数组")
    if len(raw) > MAX_ATTACHMENTS:
        raise ValueError(f"单条消息最多包含 {MAX_ATTACHMENTS} 个附件")
    return [validate_attachment(item, content) for item in raw]


def retain_message_attachments(raw: object, content: str | None = None) -> list[dict[str, str]]:
    """Retain valid metadata still present after editing or restoring a turn."""
    if not isinstance(raw, list):
        return []
    retained = []
    for item in raw[:MAX_ATTACHMENTS]:
        try:
            retained.append(validate_attachment(item, content))
        except ValueError:
            continue
    return retained
