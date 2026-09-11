# Optional persistent workspaces

Persistent workspaces are an additional plugin integration, disabled by default.
Core ships no persistence provider. Existing session/Workflow execution directories,
Agent coding-tool whitelist, and coding-tool behavior remain unchanged.

## Ownership and activation

Core owns the service contract, logical-path validation, authorization dispatch,
settings gates, bounded context loading and optional workspace tools. A plugin owns
file storage, versioned catalog, parsing and durable commits. A product plugin owns
user identity and access policy; no product user model is embedded in Core.

A provider registers with `registrar.add_workspace_provider(provider)`. The owner
plugin must be installed, enabled, running and configured without pending removal
or restart. The provider implements async `health() -> bool` and
`execute(WorkspaceRequest) -> dict`. Registration never enables the integration.
A missing/unhealthy provider never triggers a local fallback or deletion. The six
generic dispatch tools are Core-owned, registered while at least one provider runs.
Multiple provider plugins can coexist without tool-name collisions; only the selected
provider receives requests. Removing the last provider unregisters those definitions.

Products register `registrar.add_workspace_scope_authorizer(authorizer)`, whose
async `authorize(external_ref, workspace_scope, operation, path, access)` receives
keyword arguments. Every external operation, including status/list/read, must pass
this callback again. Product callbacks must reject mismatched user/session anchors
and define which paths an Agent can modify. `access='user'` is reserved for a
signed, authenticated product file-management bridge; no model tool exposes it.

`CoreRuntime.get_service('workspace')` and
`src.workspace.service.get_workspace_runtime()` expose the same runtime.

## Settings and Agent opt-in

`GET/PUT /api/workspace/settings` uses the existing settings category and protected
administrator write convention. Settings live in `config/workspace_settings.json`:

| Setting | Default |
| --- | --- |
| enabled | false |
| provider_id | empty |
| context_enabled | true |
| context_token_budget | 2000 estimated tokens |
| timeout_seconds | 15 |
| local_main_enabled | false |

Saving an enabled configuration checks the plugin state and bounded health probe.
Disabling remains possible during outages. Backend-specific options belong in the
provider plugin's registered settings section, not Core.

Each Agent additionally needs an explicit definition:

```json
{"extension_options":{"workspace":{"enabled":true,"scope":"user"}},
 "tools":["workspace_list","workspace_read","workspace_search","workspace_write","workspace_versions"]}
```

This illustrative tool list does not replace a product's other allowed tools.
`workspace_delete` is separately available. New workspace tools also obey the
existing whitelist. Core adds no coding permissions and introduces no persistent
workspace restrictions on coding tools. Main is not opted in by default. An
internal Main can use `scope: "local"` only with `local_main_enabled: true`; a
plugin/external session cannot claim this binding. The local binding is a fixed stable namespace within the selected provider,
never an implicit disk backend. Core installations intentionally sharing a provider
namespace also share its local Main workspace; product users always use their own
authorized scopes.

Workspace definitions are omitted for Agents without opt-in and are checked again
before each model call when the integration/provider becomes unavailable. Execution
always rechecks gates, including stale tools held by an existing graph.

## File service

```python
await workspace.execute(
    resource_owner="product-plugin", external_ref="trusted-session-anchor",
    workspace_scope=trusted_scope, agent_type="resolved-agent-id",
    operation="read_text", path="notes/INDEX.md", limit=6000,
)
```

Scopes are opaque lowercase 64-hex identifiers supplied only by trusted product
identity. The model never chooses the scope, provider or authorization mode.
Operations are `status`, `list`, `stat`, `read`, `read_text`, `search`, `write`,
`delete`, and `versions`. Paths use relative POSIX components; absolute paths,
traversal, empty components, backslashes and controls are rejected. Root is allowed
for status/list/search. Providers must additionally prevent symlink escape in any
local storage implementation. Requests are limited to 8 MiB; providers may lower
this. List/search/version pages are at most 100 records. Text reads use Unicode
character offsets and a maximum 12000 characters; binary `read` returns bytes.

A write without `expected_version` is create-only. Updates and deletes use the
exact prior version. Write/delete require an idempotency key: replay returns the
same result; changing the body with the same key conflicts. Tools derive this key
from the actual injected tool call ID and session, never a model-selected value.
A successful mutation must return `committed: true` after durable catalog commit.
A timeout is uncertain: retry with the original key, never report a local write as
saved. Providers retain historical versions and explicit parse states.

File metadata contains `path`, `version`, `size`, `content_type`, `sha256`,
`updated_at`, and `parse_status`. Unsupported/unreadable text is explicit; it is
not a successful empty document. Provider errors use `WorkspaceError` with stable
codes and HTTP status (invalid 422, forbidden 403, missing 404, conflict 409,
unsupported 415, too large 413, unavailable 503). Provider transport exceptions
are translated to generic errors without connection credentials.

## Context and session lifecycle

The trusted invocation context carries `workspace_scope` alongside other hidden
product metadata. It is not a browser/model-controlled request field. Every
fresh user turn loads `preferences.md`, `notes/INDEX.md` and a bounded file
manifest. Missing optional files are a valid empty workspace. Unavailable reads
produce a distinct context status. The complete injected block, including
metadata and guidance, respects the estimated token budget. Original user text
is unchanged. Materials are low-trust references; explicit preferences remain
subordinate to application policy.

Each effective user turn reads current versions, replacing prior workspace
injections rather than stacking stale notes. Pure tool resumes do not reload or
add an injection. Disabled/changed/omitted bindings strip old metadata and already
composed model bodies, including restored sessions. The cleanup marker is hidden
from model input and from the context disclosure. Rehydrated sessions receive a
fresh trusted scope from the product on invoke/resume, not a persisted grant.

The six workspace tools use the current session's hidden identity. Agent notes
are ordinary versioned files. Core does not infer which events deserve notes,
change a user's personalization, copy all uploads into the prompt, or depend on
Hindsight to enable files.

## Explicit script materialization

Trusted Workflow/script integration may explicitly call:

```python
path = await workspace.materialize_for_session(
    session, invocation_context=trusted_context, path="materials/source.txt",
)
# Read/process this temporary file. Explicitly commit any intended output later.
workspace.clear_cache()  # Only after consumers finish with their paths.
```

This method authorizes and reads the authoritative provider before accessing the
cache. Materialized names bind scope/path/version/hash and the content hash is
verified. Disabled or unauthorized calls create no directories. Clear/cache loss
is recoverable by reading the durable provider again. The returned absolute path
is never exposed by model tools; materialization grants no terminal or coding
permissions. There is no automatic local-directory synchronization, filesystem
mount, or promise that uncommitted script changes survive a restart.

For production, the provider's objects and catalog must survive application-machine
replacement (for example private object storage plus a remote database). A local
plugin mode is only for explicit development or local Community installations.
Community source publication remains a separate release action.
