# Settings extension contract

Core owns the settings category catalog and durable provider-neutral memory
controls. Plugins register categories through the existing `[settings]` TOML
table. Core does not import plugin packages or hard-code plugin ids.

## Settings sections

`GET /api/settings/sections` returns `{ "sections": SettingsSection[] }`.

Each descriptor has:

| Field | Type | Notes |
|---|---|---|
| `id` | string | Core id, or `plugin:<plugin_id>:<section_id>` |
| `title` | string | Display title |
| `owner` | string | `"core"` or the plugin id |
| `kind` | string | `"core"` or `"plugin"` |
| `order` | integer | Sort key |
| `description` | string | Short explanation |
| `plugin_id` | string | Plugin descriptors only |

Core ids are fixed: `appearance`, `desktop`, `models`, `agent`, `roundtable`,
`coding`, `compression`, `memory`, `system`. Frontend renders those through a
Core registry. Plugin descriptors do not supply URLs or components.

Any installed plugin that declares `settings.schema` is registered, including
disabled, failed, or degraded plugins, so config remains editable. Descriptor
ids are prefixed and must not collide with Core ids. Plugins keep using the
existing `/api/plugins` list and config APIs for schema-backed fields.

## Plugin `[settings]` metadata

Existing `schema` remains required to register a category. Optional fields:

```toml
[settings]
schema = "settings.schema.json"
title = "Example"
description = "Connection and retrieval parameters"
section_id = "memory"
order = 90
```

Defaults: `title` from plugin name, `description` from plugin description,
`section_id` `"settings"`, `order` `100`. `section_id` is a local kebab-case
id. The public descriptor id is always `plugin:<plugin_id>:<section_id>`.

## Memory settings

`GET /api/memory/settings` and `PUT /api/memory/settings` share one shape:

```json
{
  "settings": { "...MemorySettings" },
  "providers": [{ "id": "", "name": "", "status": "", "healthy": true, "reason": "" }],
  "effective_enabled": false,
  "reason": "",
  "schema": {}
}
```

`PUT` body is `{ "settings": object }` and returns the same GET shape. Write
access matches Plugin administration: loopback is allowed when no admin token
is configured; otherwise a Bearer token is required.

`MemorySettings` keys owned by Core:

- `enabled`, `external_enabled`, `provider_id`
- `auto_recall_enabled`, `recall_mode` (`first` / `every`)
- `recall_timeout_seconds`, `recall_max_chars`, `recall_max_bytes`
- `auto_consolidate_enabled`, `consolidate_idle_seconds`, `consolidate_length_chars`
- `max_batch_turns`, `max_concurrent_jobs`, `max_retries`, `lease_seconds`
- `extract_timeout_seconds`, `extract_model`

Numeric ranges follow the existing `MemoryRuntimePolicy` limits. Backend
defaults and validation are authoritative; the optional `schema` field is
a JSON object schema (`type`, `properties`) for shared form controls. Provider-owned values stay in plugin settings: service
URL, auth, bank, retrieval budget/types/`max_tokens`, network retry, extract
agent identity, and compatibility parsing of old plugin configs.

Persisted Core settings live in `config/memory_settings.json`. They take
effect immediately and do not use Plugin `restart_required`. Once that file
exists, Core settings are authoritative; old plugin general settings cannot
override them.

## Enable gate

Saving a document that leaves `enabled` and `external_enabled` both true
requires all of:

1. Selected `provider_id` is a registered memory provider
2. That plugin is `running` and `active_enabled`
3. Desired enabled is true
4. No staged removal, disable, or pending restart/configuration change
5. Bounded live `health()` returns true

Frontend disabled state is explanatory only. Closing the master or external
switch remains possible when the plugin is missing or failed. Plugin repair
settings stay writable through `/api/plugins` independently of this gate.

`effective_enabled` is true only when the master and external switches are on
and the selected provider is registered, running, and passes its current health check.
A pending plugin change still refers to the old running configuration until restart; it blocks new enable saves.

## Runtime gates

Persisted master and provider selection gate auto-recall, memory tools, and
delayed extract jobs. A stopped or absent plugin never runs background jobs.
A temporarily degraded but still configured provider may keep snapshots; jobs
and foreground recall still require a running provider.

When no Core settings file exists, runtime keeps the previous provider-policy
compat path so existing Agent opt-in continues to work until the first
successful Core persist.

## Optional provider methods

Core accesses these with `getattr`. Missing methods are not Protocol errors.

```python
async def health(self) -> tuple[bool, str]:
    """Bounded liveness. Missing health() cannot enable external memory."""

def legacy_runtime_settings(self) -> dict:
    """Generic Core keys only, excluding enabled/external_enabled/provider_id."""
```

`health()` must not return secrets or raise. Core bounds the call and replaces
exceptions with a generic failure reason. `legacy_runtime_settings()` is used
once when Core settings do not yet exist and exactly one provider is
configured after plugin start; valid generic values are copied, then Core persists and becomes
authoritative. Older adapters without this method are migrated from their existing `runtime_policy()` fields. Core never rewrites Agent `extension_options`.

Plugin schemas may mark legacy fields `deprecated: true`. They remain validated and preserved for migration but are omitted from the settings editor. Unknown fields are still rejected. Unreadable Core memory settings fail closed and return HTTP 503; the settings UI must not overwrite the unreadable file with defaults.
