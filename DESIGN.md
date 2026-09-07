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

## Enforcement

`npm run test:design` scans Core product TypeScript and TSX for raw Tailwind palette
utilities and raw color literals. A failing check means the design contract has been
violated. Add or change semantic tokens centrally instead of weakening the test.
