# Long-term memory contracts

Core owns a provider-neutral memory runtime. A memory plugin supplies the
backend; a product plugin may supply a scope authorizer. Core does not contain
Hindsight or Bishu branches.

The runtime is optional. Uninstalled or disabled plugins are not called and do
not create extract jobs. A temporarily degraded provider is not treated as
uninstalled: enabled sessions still snapshot complete turns and resume extract
after recovery. Foreground chat fail-opens when recall or authorization fails.
Background extract retries safely and does not use foreground grants.

## Registrar

```python
registrar.add_memory_scope_authorizer(authorizer)
registrar.add_memory_provider(provider)
```

`add_memory_scope_authorizer` is the unique shared interface with product
plugins. The authorizer is a trusted owner-scoped object:

```python
async def authorize(self, *, external_ref: str, memory_scope: str) -> bool: ...
```

Core calls it before automatic recall, agent memory tools, and background
extract/retain. A false or raised result closes that memory action only.

`memory_scope` is a 64-character lowercase SHA-256 hex digest from trusted
invocation context. It is not an authorization token and may be persisted on
the memory job. Grants and request auth must not be persisted.

## Agent opt-in

```json
{
  "extension_options": {
    "<provider-plugin-id>": {
      "enabled": true,
      "scope": "user"
    }
  }
}
```

`scope` is `user` or `local`. User scope requires a valid `memory_scope` and
must not fall back to a global bank. Local scope is only for Core local `main`
sessions with an empty `resource_owner`; third-party or external sessions cannot
declare `local` to bypass the authorizer. They do not share an external user
library.

## Provider

A memory provider implements recall, retain, reflect, runtime policy, usage
rules, extract Agent local id, and bank mapping. Retain must return
`confirmed`, `accepted`, or `failed`. `accepted` is not `confirmed`; Core does
not advance the extract watermark until every frozen fact is confirmed.

Providers may optionally implement `graph(request) -> MemoryGraph`. Missing
`graph` is unavailable, not an empty node list. Core does not import provider
packages or vendor constants.

## Persistence

Session ledgers are stored in SQLite (`ledgers.sqlite`) under the memory data
directory. Writes use `BEGIN IMMEDIATE` transactions and versioned payloads.
Claim, lease renew, freeze, and retain checkpoints are fenced by `job_id` plus
`worker_id`, so an expired worker cannot submit after takeover.

The scheduler remains off when no configured provider enables consolidation.
`max_concurrent_jobs` is enforced across sessions and processes by counting
unexpired active jobs in the same transaction as the claim. `max_retries` and
`retry_delay_seconds` control extract/retain failure backoff; exhausted jobs
stay failed without moving the watermark.

This runtime is unpublished; leftover JSON ledgers are not migrated.

## Recall

Core recalls from the real user turn into `model_context`. Display and stored
user text stay unchanged. The recall query may include a bounded window of
recent raw user turns plus the current input; it does not include recalled
memory or injection text. Default mode is every effective turn; `first` only
recalls the first effective input. Pure confirmations skip recall but still
snapshot the complete source turn. Tool resume, action observations, failures,
cancels, and waiting tool approval are not successful complete turns; a resumed
approved tool pair is.

The foreground recall timeout covers authorization and the provider, not only
the provider call. User activity is recorded when input starts so a long reply
does not look like idle time.

Dedup only excludes memory ids still present in the live model context, so
compression can bring a memory back. Changing `memory_scope` or bank strips
previously injected memory blocks from history so the old library is not leaked
into the new one.

System prompt contributions may include stable usage rules only. Recalled
history is a low-trust reference, not an instruction.

Successful recall preserves `long_term_memory.items: []` even when no items
remain after retrieval or filtering. The injection disclosure shows this as
`长期记忆：[]`, separately from product context, without extra status details.
Skipped, unavailable or failed recall must not fabricate an empty success;
older messages without a recorded memory block keep that absence.

Agent tools must not report an empty hit when the binding or provider is
unavailable. `tool_recall` and `tool_reflect` raise `MemoryUnavailableError`.

## Extract

Core snapshots complete turns as they are received, including after tool
resume. Compression or reset cannot drop already received unprocessed turns.
Snapshots preserve complete message bodies and tool pairs. Extraction selects
whole turns up to a 128 KB input budget; remaining turns wait for the next batch.
A single oversized turn fails visibly in the ledger without advancing progress,
instead of silently truncating useful facts. Output is limited to 64 facts and
128 KB; source IDs must refer to the supplied turns.

Idle time or unprocessed estimated tokens claims a leased job. Network extract
and retain run outside the ledger transaction. New complete turns that arrive
during a job are snapshotted immediately and wait for the next batch; they do
not overwrite frozen facts.

`consolidate_length_tokens` defaults to 20,000 and counts all pending complete
turns in the current partition, using Core's shared `estimate_tokens` heuristic
on message text and serialized tool-call arguments. This is an estimate, not
provider billing usage. Existing snapshots recompute from source messages when
`estimated_tokens` is absent; `char_count` is never used as a conversion proxy.
Settings v2 migrates the legacy character key once, preserving its numeric value
as the new token threshold (there is no claim of equivalent text capacity).
Other settings are preserved. The deprecated provider policy constructor field
is accepted for already installed adapters; saved Core policy uses tokens only.

The extraction caller requests JSON mode through the existing Core provider
adapter, preserving explicit Agent response-format settings. Core reinforces the
facts output contract in the system prompt. Providers without JSON mode still
use strict parsing; a request failure is never treated as an empty result.
One format-correction call is allowed within the original total timeout.

Parsing accepts a single complete JSON document, optionally wrapped in prose,
Markdown fences or closed leading reasoning blocks. It rejects duplicate keys,
multiple documents, malformed/truncated outer objects and provider-reported
truncation; it never searches nested objects or rewrites quoted text/commas to
rescue a broken response. Source validation remains mandatory after correction.

The plugin Agent plus Core LLM extract long-term facts using the host's layered
`PromptBuilder` and Core-configured LLM. Resource resolution uses type
`agents`. Invalid extract JSON, a missing `facts` field, unknown source ids, or
a turn mismatch raise and retry without moving the watermark. Only a legal
`{"facts":[]}` is a successful empty extract. Source timestamps come from the
frozen source turn, not the model. Preference facts are excluded.

Results are frozen, then retained with idempotent `document_id` values. Plugin
disable, auto-consolidate off, or revoked authorization after extract and
before retain is re-checked and must not write. Failure retries re-check
authorization. Only confirmed writes move the watermark. New messages during a
job wait for the next batch. After prune, the watermark cursor and seen turn
ids remain, so the next batch is not empty.

## Public service

`CoreRuntime.get_service("memory")` is the authorized facade used by session
hooks and agent tools. Background jobs re-authorize with persisted
`external_ref` and `memory_scope` and never reuse a foreground grant.
`CoreRuntime` also exposes the host `prompt_builder` so extract uses the same
layered plugin prompts as chat.

`read_graph` is a provider-neutral read of user memory. Callers pass
`resource_owner`, `external_ref`, `memory_scope`, `agent_type`, and `limit`
(1..300). Core applies the same global/external/provider/Agent gates as recall,
resolves the bank through the provider, authorizes with the owner callback,
then rechecks authorization and runtime after the awaited provider call.
Failures, timeouts, disabled gates, and unsupported providers are errors, not
empty graphs. The response is the bounded node/link wire schema; extra metadata,
bank identifiers, and upstream URLs are dropped.

Providers may optionally implement `runtime_policy_for_agent(agent_type)` to
preserve agent-specific recall budgets. The mandatory `runtime_policy()` remains
the provider-wide consolidation policy. Authorization and lease ownership are
rechecked before extraction and each individual write. A retry receives a new
claim ID so a stale execution cannot mutate the reclaimed job.


## Administrative recovery

The Core memory settings category includes background job status and an explicit
retry for failed jobs. `GET /api/memory/jobs` and
`POST /api/memory/jobs/{session_id}/retry` both require local administration or
the configured administrator token. Summaries contain counts, approximate tokens,
phase, attempt and a sanitized error category; source text, bank IDs, scopes,
external identities, provider errors and frozen facts are not exposed.

Retry requires the observed `job_id`; a changed or already-retried job returns
409. Recovery rechecks global/provider/auto-consolidate gates, provider health and
owner authorization, then transactionally replaces the worker/job fence while
preserving source range, watermarks, frozen facts and deterministic document IDs.
The ordinary scheduler claims the queued retry under existing concurrency limits.
A failed batch is never skipped, and newer turns stay outside its frozen range.
Exhausted retries remain visible until an explicit recovery request. Completed
jobs retain a compact completion timestamp and counts without source content.
