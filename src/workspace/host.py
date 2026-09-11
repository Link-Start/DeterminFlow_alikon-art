"""Plugin lifecycle wiring; Core ships no storage implementation."""
from src.workspace.tools import TOOL_NAMES, register_workspace_tools


def sync_workspace_runtime(manager, runtime):
    getter = getattr(runtime, "get_service", None)
    workspace = getter("workspace") if callable(getter) else None
    if workspace is None:
        return
    contributions = manager.contributions
    workspace.attach(providers=dict(contributions.workspace_providers),
                     authorizers=dict(contributions.workspace_scope_authorizers),
                     owner_status=manager.get_state, management=getattr(manager, "plugin_management", None))
    registry = runtime.tool_registry
    if any(workspace._running(owner) for owner in workspace._providers):
        existing = {item["name"] for item in registry.get_tools() if item.get("owner") == "core"}
        if not set(TOOL_NAMES).issubset(existing):
            register_workspace_tools(registry, "core")
    else:
        registry.unregister_tools(TOOL_NAMES, owner="core")
