"""Project provider graph payloads onto the Core read-only wire schema."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from src.memory.contracts import (
    GRAPH_LINK_TYPES,
    GRAPH_NODE_TYPES,
    MemoryGraph,
    MemoryGraphLink,
    MemoryGraphNode,
    MemoryUnavailableError,
)

_ID_MAX = 128
_LABEL_MAX = 256
_TEXT_MAX = 8000
_CONTEXT_MAX = 2000
_TOKEN_MAX = 128
_LIST_MAX = 32
_STAMP_MAX = 64
_LINK_MAX = 10_000


def project_memory_graph(value: object, *, limit: int) -> MemoryGraph:
    payload = _payload(value)
    raw_nodes = payload.get("nodes")
    raw_links = payload.get("links", payload.get("edges"))
    if not isinstance(raw_nodes, Sequence) or isinstance(raw_nodes, (str, bytes)):
        raise MemoryUnavailableError("memory graph unavailable")
    if raw_links is None:
        raw_links = ()
    if not isinstance(raw_links, Sequence) or isinstance(raw_links, (str, bytes)):
        raise MemoryUnavailableError("memory graph unavailable")

    nodes: list[MemoryGraphNode] = []
    seen: set[str] = set()
    for raw in raw_nodes:
        node = _node(raw)
        if node is None or node.id in seen:
            continue
        seen.add(node.id)
        nodes.append(node)
        if len(nodes) >= limit:
            break

    ids = {node.id for node in nodes}
    links: list[MemoryGraphLink] = []
    for raw in raw_links[:_LINK_MAX]:
        link = _link(raw, ids)
        if link is None:
            continue
        links.append(link)

    truncated = (bool(payload.get("truncated")) or len(raw_nodes) > len(nodes)
                 or len(raw_links) > _LINK_MAX)
    total = payload.get("total_units")
    if isinstance(total, int) and total > len(nodes):
        truncated = True
    return MemoryGraph(nodes=tuple(nodes), links=tuple(links), truncated=truncated)


def _payload(value: object) -> Mapping[str, Any]:
    if isinstance(value, MemoryGraph):
        return {
            "nodes": [node.to_wire() for node in value.nodes],
            "links": [link.to_wire() for link in value.links],
            "truncated": value.truncated,
        }
    if isinstance(value, Mapping):
        return value
    to_wire = getattr(value, "to_wire", None)
    if callable(to_wire):
        payload = to_wire()
        if isinstance(payload, Mapping):
            return payload
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return payload
    raise MemoryUnavailableError("memory graph unavailable")


def _node(raw: object) -> MemoryGraphNode | None:
    data = _item(raw)
    node_id = _clip(data.get("id"), _ID_MAX)
    if not node_id:
        return None
    label = _clip(data.get("label"), _LABEL_MAX)
    text = _clip(data.get("text"), _TEXT_MAX) or label
    return MemoryGraphNode(
        id=node_id,
        label=label,
        text=text,
        type=_enum(data.get("type"), GRAPH_NODE_TYPES, "unknown"),
        context=_clip(data.get("context"), _CONTEXT_MAX),
        entities=_tokens(data.get("entities")),
        tags=_tokens(data.get("tags")),
        occurred_at=_optional(data.get("occurred_at"), _STAMP_MAX),
        document_id=_optional(data.get("document_id"), _ID_MAX),
    )


def _link(raw: object, node_ids: set[str]) -> MemoryGraphLink | None:
    data = _item(raw)
    source = _clip(data.get("source", data.get("from")), _ID_MAX)
    target = _clip(data.get("target", data.get("to")), _ID_MAX)
    if not source or not target or source not in node_ids or target not in node_ids:
        return None
    weight = data.get("weight", 0.0)
    if isinstance(weight, bool) or not isinstance(weight, (int, float)):
        return None
    value = float(weight)
    if not math.isfinite(value) or value < 0:
        return None
    return MemoryGraphLink(
        source=source,
        target=target,
        type=_enum(data.get("type"), GRAPH_LINK_TYPES, "unknown"),
        weight=value,
    )


def _item(raw: object) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        return raw
    if isinstance(raw, (MemoryGraphNode, MemoryGraphLink)):
        return raw.to_wire()
    to_dict = getattr(raw, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return payload
    raise MemoryUnavailableError("memory graph unavailable")


def _clip(value: object, limit: int) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        return ""
    return text[:limit]


def _optional(value: object, limit: int) -> str | None:
    if value is None:
        return None
    text = _clip(value, limit)
    return text or None


def _enum(value: object, allowed: frozenset[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def _tokens(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [item.strip() for item in value.split(",")]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        parts = [item.strip() for item in value if isinstance(item, str)]
    else:
        return ()
    tokens: list[str] = []
    seen: set[str] = set()
    for part in parts:
        token = part[:_TOKEN_MAX]
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= _LIST_MAX:
            break
    return tuple(tokens)
