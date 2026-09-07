"""Workflow Agent 输出文件的确定性规范化。

LLM 输出校验失败必须结束当前 Node attempt。这里仅保留不会再次调用模型的
本地 JSON 安全修复；失败后的重新生成统一由节点失败策略创建新 attempt。
"""

from __future__ import annotations

from .json_output import get_json_policy, validate_and_format_json


async def prepare_json_file_output(
    *,
    raw_output: str,
    node_params: dict | None,
    output_file_path: str,
) -> dict:
    """校验 JSON 文件输出，只允许当前 attempt 内的确定性安全修复。"""
    policy = get_json_policy(output_file_path, node_params)
    meta: dict[str, str] = {
        "_json_repair_policy": policy,
        "_json_output_file": output_file_path,
        "_json_retry_attempts": "0",
    }
    if policy == "none":
        return {"success": True, "text": raw_output, "meta": meta}

    allow_safe_repair = policy in {"safe_repair", "safe_repair_then_retry"}
    result = validate_and_format_json(raw_output, repair=allow_safe_repair)
    if result.success:
        if result.repairs:
            meta["_json_repair_applied"] = ",".join(result.repairs)
        return {"success": True, "text": result.formatted, "meta": meta}

    return {
        "success": False,
        "error": f"JSON 输出校验失败 [invalid_json]: {result.error}",
        "meta": meta,
    }
