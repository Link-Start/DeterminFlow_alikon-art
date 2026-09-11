# DeterminFlow Core Design Standard

This document is the authoritative visual contract for DeterminFlow Core. `PRODUCT.md`
defines the product purpose and personality; this file defines how those qualities are
expressed in the interface.

## Brand Direction

The Core palette is **Determin Indigo + Blue Slate**: precise, calm, capable, and built
for sustained use in a developer tool.

- About 80% of the interface uses blue-slate neutral surfaces.
- About 15% is text and hierarchy.
- No more than 5% is brand indigo.
- Do not use gradients, decorative glow, glass effects, or page-specific accent colors.

## Color Roles

| Role | Dark | Light | Use |
| --- | --- | --- | --- |
| Canvas | `#0C1323` | `#F8FAFC` | Application background |
| Surface | `#101B2D` | `#FFFFFF` | Panels and cards |
| Raised surface | `#18273E` | `#F1F5F9` | Controls and nested regions |
| Hover | `#253A55` | `#E2E8F0` | Hover and low emphasis selection |
| Border | `#304661` | `#E2E8F0` | Default separators |
| Strong border | `#455C79` | `#CBD5E1` | Focused structure |
| Primary text | `#F8FAFC` | `#0F172A` | Titles and body |
| Secondary text | `#CBD5E1` | `#475569` | Supporting information |
| Muted text | `#94A3B8` | `#64748B` | Metadata and placeholders |
| Brand | `#6366F1` | `#4F46E5` | Primary action, active navigation, focus |

The table documents intent. Components consume semantic tokens such as `background`,
`card`, `foreground`, `muted`, `primary`, and `border`; they must not copy these values.

## Semantic States

| State | Semantic token | Meaning |
| --- | --- | --- |
| Success | `success` | Connected, enabled, completed |
| Warning | `warning` | Pending, retrying, needs attention |
| Danger | `destructive` | Failed, destructive, invalid |
| Information | `info` | Informational runtime state |

State must never be communicated by color alone. Pair it with a label, icon, or both.
Brand indigo is not a success or status color.

## Domain Colors

Domain colors are limited to workflow, graph, and orchestration objects. They may appear
on a node icon, small marker, compact tag, or restrained identity tint, never as a page
theme. Repeated orchestration objects without an explicit type rotate through the domain
palette in display order so adjacent objects never share a color. Color supplements the
visible name and never becomes the only identifier.

| Object | Token |
| --- | --- |
| Agent | `node-agent` |
| Tool | `node-tool` |
| Script | `node-script` |
| API | `node-api` |
| Approval | `node-approval` |

Graph libraries that require literal color values must import them from
`web/src/lib/brand-colors.ts`. That file is the only product-code exception to the raw
color-literal rule.

## Component Rules

1. All top-navigation active states use brand indigo, regardless of page.
2. Primary buttons use `primary`; secondary actions use neutral outline or ghost styles.
3. Cards use `card`; nested controls use `secondary` or `muted`; page backgrounds use
   `background`.
4. Text hierarchy uses `foreground` and `muted-foreground`; never tune hierarchy with a
   page-specific hue.
5. Focus uses `ring`; selected state uses `primary` with a restrained translucent surface.
6. Keep authoritative state and the next valid action adjacent. Do not add decorative cards.
7. Target WCAG 2.1 AA, keyboard focus visibility, reduced motion, and 390px usability.
8. Dense workbenches may locally promote light-theme neutral separators to `Strong border`;
   dark-theme separators keep the default `Border` role.

## Settings

The settings page is a document-scrolling workbench under the app header.

1. Preserve the centered, single-column collapsible-card layout. Categories come from one registry; registration and field consistency do not authorize replacing this layout with sidebar navigation. Appearance and models start expanded; other cards can open independently. Collapsing a card preserves its editor and draft.
2. A sticky save/discard toolbar sits at the top of the page scroll container. Use a solid `background` bar with `border`; do not use blur or glass.
3. Theme changes apply immediately and do not enter the dirty/save state.
4. Provider create/delete/discover, desktop update, and clearing saved plugin config are explicit operations. Editable provider and plugin fields join the unified dirty/save state.
5. Save outcomes are per category. Do not present a single success state when any category failed.
6. Preserve the established category icon colors using semantic tokens: Agent uses `info`, roundtable `success`, coding `destructive`, and compression/system `warning`. These small identity accents do not indicate errors or change the neutral card, heading, and field backgrounds.
7. Field lists share the parent card surface, using spacing and faint separators to pair labels with controls. Do not use zebra stripes or add an inner table-like frame; short labels and controls align vertically. Fields use the shared shadcn controls through the settings field renderer. Sensitive values use a password control; enums use a select; defaults appear as the current value, not helper copy.

Background memory failures belong beside the memory settings, with the affected
session, concise failure reason and retry action together. Refreshing operational
status must not replace unsaved settings drafts.

The optional persistent workspace category uses the same field renderer and unified
save state. Its activation switch remains available for disabling during outages;
enabling requires an active healthy registered provider. Conversation context details
show loaded file references and empty/unavailable states without hidden binding IDs.

## Enforcement

`npm run test:design` scans Core product TypeScript and TSX for raw Tailwind palette
utilities and raw color literals. A failing check means the design contract has been
violated. Add or change semantic tokens centrally instead of weakening the test.
