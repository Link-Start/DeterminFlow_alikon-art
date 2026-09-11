from __future__ import annotations

import asyncio
import math
from pathlib import Path

import pytest

from src.memory.contracts import (
    GRAPH_DEFAULT_LIMIT,
    MemoryGraph,
    MemoryGraphLink,
    MemoryGraphNode,
    MemoryGraphRequest,
    MemoryUnavailableError,
)
from src.memory.graph import project_memory_graph
from src.memory.service import MemoryRuntimeService
from src.memory.settings import (
    MemorySettingsStore,
    default_memory_settings,
    parse_memory_settings,
)
from tests.test_memory_runtime import (  # noqa: F401
    SCOPE_A,
    FakeAuthorizer,
    FakeProvider,
    _policy,
    _runtime,
    patch_agents,
)


pytestmark = pytest.mark.usefixtures("patch_agents")


class GraphProvider(FakeProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.graphs: list[MemoryGraphRequest] = []
        self.graph_result = MemoryGraph(nodes=(), links=(), truncated=False)
        self.graph_error: BaseException | None = None
        self.graph_delay = 0.0
        self.after_graph = None

    async def graph(self, request: MemoryGraphRequest) -> MemoryGraph:
        if self.graph_delay:
            await asyncio.sleep(self.graph_delay)
        self.graphs.append(request)
        if self.after_graph is not None:
            self.after_graph()
        if self.graph_error is not None:
            raise self.graph_error
        return self.graph_result


def _graph_result() -> MemoryGraph:
    return MemoryGraph(
        nodes=(
            MemoryGraphNode(
                id="m1",
                label="short",
                text="full text",
                type="world",
                context="source",
                entities=("Alice",),
                tags=("tag",),
                occurred_at="2024-01-15T10:30:00+00:00",
                document_id="doc-1",
            ),
            MemoryGraphNode(id="m2", label="other", text="other text", type="experience"),
        ),
        links=(
            MemoryGraphLink(source="m1", target="m2", type="semantic", weight=0.8),
        ),
        truncated=False,
    )


def _persist(service: MemoryRuntimeService, **overrides):
    values = default_memory_settings().to_dict()
    values.update(enabled=True, external_enabled=True, provider_id="mem")
    values.update(overrides)
    return service._settings_store.save(parse_memory_settings(values))


def _gated_runtime(tmp_path, provider, authorizer=None, **settings):
    store = MemorySettingsStore(tmp_path / "memory_settings.json")
    service = MemoryRuntimeService(
        tmp_path / "memory",
        settings_store=store,
        worker_id="worker-1",
    )
    states = {"mem": {"status": "running"}, "product": {"status": "running"}}
    service.attach(
        authorizers={"product": authorizer or FakeAuthorizer()},
        providers={"mem": provider},
        owner_status=lambda owner: states.get(owner, {"status": "missing"}),
    )
    _persist(service, **settings)
    return service


async def _read(service, **overrides):
    values = dict(
        resource_owner="product",
        external_ref="user:42",
        memory_scope=SCOPE_A,
        agent_type="page-assistant",
        limit=200,
    )
    values.update(overrides)
    return await service.read_graph(**values)


def test_core_memory_has_no_hindsight_imports() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "memory"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "hindsight" not in text.lower()
        assert "HINDSIGHT" not in text


def test_project_memory_graph_drops_dangling_nan_and_unknown_types() -> None:
    graph = project_memory_graph(
        {
            "nodes": [
                {"id": "m1", "label": "A", "text": "full A", "type": "world"},
                {"id": "m2", "label": "B", "type": "mystery"},
            ],
            "edges": [
                {"from": "m1", "to": "m2", "type": "temporal", "weight": 1.5},
                {"from": "m1", "to": "missing", "type": "semantic", "weight": 1},
                {"from": "m1", "to": "m2", "type": "semantic", "weight": math.nan},
            ],
            "total_units": 9,
        },
        limit=2,
    )
    assert [node.id for node in graph.nodes] == ["m1", "m2"]
    assert graph.nodes[1].type == "unknown"
    assert graph.nodes[1].text == "B"
    assert graph.links == (
        MemoryGraphLink(source="m1", target="m2", type="temporal", weight=1.5),
    )
    assert graph.truncated is True


def test_read_graph_authorizes_resolves_bank_and_rechecks_after_await(
    tmp_path, patch_agents
) -> None:
    async def scenario() -> None:
        authorizer = FakeAuthorizer(allowed={("user:42", SCOPE_A)})
        provider = GraphProvider()
        provider.graph_result = _graph_result()
        service = _runtime(tmp_path, provider, authorizer)
        graph = await _read(service)
        assert graph.to_wire()["nodes"][0]["id"] == "m1"
        assert provider.graphs == [MemoryGraphRequest(bank_id=SCOPE_A, limit=200)]
        assert provider.bank_calls == [("user", SCOPE_A)]
        assert authorizer.calls == [("user:42", SCOPE_A), ("user:42", SCOPE_A)]

        provider.after_graph = lambda: authorizer.allowed.clear()
        with pytest.raises(MemoryUnavailableError, match="unauthorized"):
            await _read(service)
        assert len(authorizer.calls) == 4

    asyncio.run(scenario())


def test_read_graph_unavailable_when_provider_lacks_graph(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        service = _runtime(tmp_path, FakeProvider())
        with pytest.raises(MemoryUnavailableError, match="graph unavailable"):
            await _read(service)

    asyncio.run(scenario())


def test_read_graph_honors_global_external_provider_and_agent_gates(
    tmp_path, patch_agents
) -> None:
    async def scenario() -> None:
        provider = GraphProvider()
        provider.graph_result = _graph_result()
        disabled = _gated_runtime(tmp_path, provider, enabled=False)
        with pytest.raises(MemoryUnavailableError, match="provider unavailable"):
            await _read(disabled)
        assert provider.graphs == []

        closed = _gated_runtime(
            tmp_path, GraphProvider(), external_enabled=False
        )
        with pytest.raises(MemoryUnavailableError, match="provider unavailable"):
            await _read(closed)

        other = _gated_runtime(
            tmp_path, GraphProvider(), provider_id="other-memory"
        )
        with pytest.raises(MemoryUnavailableError, match="provider unavailable"):
            await _read(other)

        opted_out = _gated_runtime(tmp_path, GraphProvider())
        with pytest.raises(MemoryUnavailableError, match="binding unavailable"):
            await _read(opted_out, agent_type="writer")

    asyncio.run(scenario())


def test_read_graph_timeout_and_provider_failure_are_errors_not_empty(
    tmp_path, patch_agents
) -> None:
    async def scenario() -> None:
        slow = GraphProvider(_policy(recall_timeout_seconds=0.05))
        slow.graph_delay = 0.2
        slow.graph_result = _graph_result()
        timed = _runtime(tmp_path, slow)
        with pytest.raises(MemoryUnavailableError, match="timed out"):
            await _read(timed)
        assert slow.graphs == []

        failing = GraphProvider()
        failing.graph_error = RuntimeError("upstream boom")
        service = _runtime(tmp_path, failing)
        with pytest.raises(MemoryUnavailableError, match="graph unavailable"):
            await _read(service)
        assert failing.graphs == [MemoryGraphRequest(bank_id=SCOPE_A, limit=200)]

        empty = GraphProvider()
        empty_service = _runtime(tmp_path, empty)
        graph = await _read(empty_service, limit=GRAPH_DEFAULT_LIMIT)
        assert graph == MemoryGraph(nodes=(), links=(), truncated=False)

    asyncio.run(scenario())


def test_read_graph_rejects_out_of_range_limit(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        service = _runtime(tmp_path, GraphProvider())
        with pytest.raises(ValueError, match="1..300"):
            await _read(service, limit=0)
        with pytest.raises(ValueError, match="1..300"):
            await _read(service, limit=301)

    asyncio.run(scenario())


def test_projection_bounds_links_preserves_count_weights_and_discards_nested_values():
    graph = project_memory_graph({
        "nodes": [{"id": "a", "text": {"secret": "do not stringify"}, "entities": [{"secret": "x"}]}, {"id": "b"}],
        "links": [{"source": "a", "target": "b", "weight": 3}] * 10001,
    }, limit=200)
    assert len(graph.links) == 10000
    assert graph.links[0].weight == 3
    assert graph.truncated
    assert graph.nodes[0].text == ""
    assert graph.nodes[0].entities == ()
    rejected = project_memory_graph({"nodes": [{"id": "a"}], "links": [
        {"source": "a", "target": "a", "weight": weight} for weight in [-1, float("nan"), float("inf")]
    ]}, limit=200)
    assert not rejected.links
