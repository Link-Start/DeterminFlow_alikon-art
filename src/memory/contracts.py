"""Provider-neutral long-term memory contracts owned by Core."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

RECALL_FIRST = "first"
RECALL_EVERY = "every"
SCOPE_LOCAL = "local"
SCOPE_USER = "user"
RETAIN_ACCEPTED = "accepted"
RETAIN_CONFIRMED = "confirmed"
RETAIN_FAILED = "failed"
SKIP_CONFIRMATION = "confirmation"
SKIP_OBSERVATION = "action_observation"
SKIP_RESUME = "tool_resume"
SKIP_NON_HUMAN = "non_human"
MEMORY_CONTEXT_KEY = "long_term_memory"
GRAPH_DEFAULT_LIMIT = 200
GRAPH_LIMIT_MIN = 1
GRAPH_LIMIT_MAX = 300
GRAPH_NODE_TYPES = frozenset({"world", "experience", "observation", "unknown"})
GRAPH_LINK_TYPES = frozenset({"semantic", "temporal", "entity", "causal", "unknown"})

RecallMode = Literal["first", "every"]
MemoryScopeKind = Literal["local", "user"]
RetainStatus = Literal["accepted", "confirmed", "failed"]


@dataclass(frozen=True)
class MemoryRuntimePolicy:
    auto_recall_enabled: bool
    recall_mode: RecallMode
    recall_budget: str
    recall_types: tuple[str, ...]
    recall_max_tokens: int
    recall_timeout_seconds: float
    recall_max_chars: int
    recall_max_bytes: int
    auto_consolidate_enabled: bool
    consolidate_idle_seconds: int
    max_batch_turns: int
    max_concurrent_jobs: int
    max_retries: int
    retry_delay_seconds: float
    lease_seconds: int
    extract_timeout_seconds: float
    extract_agent_local_id: str
    extract_model: str
    local_main_enabled: bool
    local_bank_id: str
    consolidate_length_tokens: int | None = None
    # Constructor compatibility for already installed provider plugins.
    consolidate_length_chars: int | None = None

    def __post_init__(self) -> None:
        if self.consolidate_length_tokens is None:
            value = self.consolidate_length_chars
            object.__setattr__(self, "consolidate_length_tokens", 20000 if value is None else value)


@dataclass(frozen=True)
class MemoryBinding:
    provider_id: str
    scope: MemoryScopeKind
    bank_id: str
    memory_scope: str
    policy: MemoryRuntimePolicy


class MemoryUnavailableError(RuntimeError):
    """Binding, authorization, or provider is missing; tools must not fake empty hits."""

    def __init__(
        self, message: str = "memory unavailable", *, code: str = "memory_unavailable"
    ):
        super().__init__(message)
        self.code = code


class MemoryLeaseLostError(RuntimeError):
    """Job fencing rejected this worker; frozen results must not be submitted."""


class ExtractParseError(ValueError):
    """Extract output is not a valid facts document; watermark must stay."""


@dataclass(frozen=True)
class MemoryRecallItem:
    id: str
    text: str
    type: str = "observation"
    provenance: str = ""


@dataclass(frozen=True)
class MemoryRecallRequest:
    query: str
    bank_id: str
    budget: str
    types: tuple[str, ...]
    max_tokens: int


@dataclass(frozen=True)
class MemoryRetainRequest:
    content: str
    bank_id: str
    document_id: str
    timestamp: str
    metadata: Mapping[str, str]
    tags: tuple[str, ...] = ()
    context: str = ""
    update_mode: str | None = None
    retain_async: bool = False


@dataclass(frozen=True)
class MemoryRetainResult:
    status: RetainStatus
    document_id: str
    operation_id: str = ""
    message: str = ""


@dataclass(frozen=True)
class MemoryReflectRequest:
    query: str
    bank_id: str
    budget: str = "mid"


@dataclass(frozen=True)
class MemoryFact:
    text: str
    source_message_ids: tuple[str, ...]
    source_timestamp: str
    turn_id: str
    kind: str = "fact"


@dataclass(frozen=True)
class MemoryExtractRequest:
    session_id: str
    bank_id: str
    memory_scope: str
    extract_agent_type: str
    turns: tuple[Mapping[str, object], ...]
    timeout_seconds: float
    model_override: str = ""


@dataclass(frozen=True)
class MemoryGraphRequest:
    bank_id: str
    limit: int = GRAPH_DEFAULT_LIMIT


@dataclass(frozen=True)
class MemoryGraphNode:
    id: str
    label: str = ""
    text: str = ""
    type: str = "unknown"
    context: str = ""
    entities: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    occurred_at: str | None = None
    document_id: str | None = None

    def to_wire(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "text": self.text,
            "type": self.type,
            "context": self.context,
            "entities": list(self.entities),
            "tags": list(self.tags),
            "occurred_at": self.occurred_at,
            "document_id": self.document_id,
        }


@dataclass(frozen=True)
class MemoryGraphLink:
    source: str
    target: str
    type: str = "unknown"
    weight: float = 0.0

    def to_wire(self) -> dict[str, object]:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "weight": self.weight,
        }


@dataclass(frozen=True)
class MemoryGraph:
    nodes: tuple[MemoryGraphNode, ...]
    links: tuple[MemoryGraphLink, ...]
    truncated: bool = False

    def to_wire(self) -> dict[str, object]:
        return {
            "nodes": [node.to_wire() for node in self.nodes],
            "links": [link.to_wire() for link in self.links],
            "truncated": self.truncated,
        }


@runtime_checkable
class MemoryProvider(Protocol):
    def runtime_policy(self) -> MemoryRuntimePolicy: ...

    def usage_rules(self) -> str: ...

    def extract_agent_local_id(self) -> str: ...

    def bank_id_for(self, *, scope: str, memory_scope: str) -> str: ...

    async def recall(
        self,
        request: MemoryRecallRequest,
    ) -> Sequence[MemoryRecallItem]: ...

    async def retain(self, request: MemoryRetainRequest) -> MemoryRetainResult: ...

    async def reflect(self, request: MemoryReflectRequest) -> str: ...

    # Optional Core settings contract, accessed by getattr:
    # async def health(self) -> tuple[bool, str]: ...
    # def legacy_runtime_settings(self) -> Mapping[str, object]: ...
    # async def graph(self, request: MemoryGraphRequest) -> MemoryGraph: ...


@runtime_checkable
class MemoryScopeAuthorizer(Protocol):
    async def authorize(self, *, external_ref: str, memory_scope: str) -> bool: ...


@runtime_checkable
class MemoryExtractRunner(Protocol):
    async def extract(self, request: MemoryExtractRequest) -> Sequence[MemoryFact]: ...
