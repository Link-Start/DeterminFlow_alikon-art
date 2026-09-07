"""Opaque SHA-256 routing identity for Workflow node LLM requests."""

from __future__ import annotations

import hashlib
import json
from typing import Any

REQUEST_FINGERPRINT_SCHEMA = "workflow_llm_request_fingerprint.v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def build_workflow_llm_request_fingerprint(
    *,
    workflow_id: str | None,
    task_id: str | None,
    node_id: str | None,
    model: str | None = None,
    agent_type: str | None = None,
    input_snapshot: dict[str, Any] | None = None,
    model_params: dict[str, Any] | None = None,
) -> str | None:
    """Hash stable Workflow attempt identity and frozen input facts.

    The digest is based only on non-secret identity/input fields. Prompt text,
    custom prompt, session IDs, and attempt counts are intentionally excluded
    so a frozen node retry stays stable while distinct task/node/input/model
    requests normally differ.
    """
    workflow_id = str(workflow_id or "").strip()
    task_id = str(task_id or "").strip()
    node_id = str(node_id or "").strip()
    if not workflow_id or not task_id or not node_id:
        return None
    payload = {
        "schema": REQUEST_FINGERPRINT_SCHEMA,
        "workflow_id": workflow_id,
        "task_id": task_id,
        "node_id": node_id,
        "model": str(model or ""),
        "agent_type": str(agent_type or ""),
        "input_snapshot": input_snapshot or {},
        "model_params": model_params or {},
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
