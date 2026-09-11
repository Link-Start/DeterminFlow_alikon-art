"""Wire Extension contributions into the Core memory runtime."""

from __future__ import annotations

from typing import Any

from src.memory.extract import DefaultExtractRunner


def _core_llm_factory(model_override: str, model_params: dict | None):
    from src.core.llm_client import create_startup_llm

    return create_startup_llm(
        model_override=model_override or None,
        streaming=False,
        model_params=model_params,
    )


def sync_memory_runtime(manager: Any, runtime: Any) -> None:
    memory = None
    if runtime is not None:
        getter = getattr(runtime, "get_service", None)
        if callable(getter):
            memory = getter("memory")
    if memory is None:
        return
    contributions = getattr(manager, "contributions", None)
    authorizers = {}
    providers = {}
    if contributions is not None:
        authorizers = {
            owner: authorizer
            for owner, authorizer in getattr(
                contributions, "memory_scope_authorizers", []
            )
        }
        providers = {
            owner: provider
            for owner, provider in getattr(contributions, "memory_providers", [])
        }
    resolver = getattr(manager, "resource_resolver", None)

    def resolve_resource(owner: str, resource_type: str, local_id: str) -> str:
        if resolver is None:
            return local_id
        return resolver.resolve(owner, resource_type, local_id)

    prompt_builder = None
    if runtime is not None:
        prompt_builder = runtime.get_service("prompt_builder")

    memory.attach(
        authorizers=authorizers,
        providers=providers,
        owner_status=getattr(manager, "get_state", None),
        resolve_resource=resolve_resource,
        extract_runner=DefaultExtractRunner(
            prompt_builder=prompt_builder,
            llm_factory=_core_llm_factory,
        ),
    )
