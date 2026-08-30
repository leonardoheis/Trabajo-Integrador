# Archive, Daylight — Light Theme Design Spec

## Status

Draft — pending user review.

## Context

`2026-08-25-frontend-visual-redesign-design.md`'s Decision 1 established "Archive": a warm
paper-ink dark palette (near-black `#14110f` background, warm off-white text), Georgia serif for
display/body, Courier New monospace for utility text (IDs, timestamps, node names). It's shipped
and every page consumes it via CSS custom properties in `src/classiflow/frontend/src/index.css` —
no page hardcodes a color.

Feedback on the live app: the theme reads as too dark. This spec **supersedes Decision 1's color
values only** — same token names, same font families, same "municipal records office" identity —
flipped from dark to light. Validated with the user via the visual companion against two other
directions ("Console" — a cooler, sans-serif, blue-accented direction closer to a reference
screenshot the user shared; "Ledger" — a serif/sans hybrid with a desaturated ochre accent). The
user picked staying closest to the existing identity: same warm palette, same serif/mono pairing,
just paper instead of near-black.

A second, independent piece of feedback came out of reviewing the mockup at a realistic scale: the
type scale used across the live app reads too small. That is not a color-token concern — Tailwind
sizes are hardcoded per-element today, there is no size token — so it's captured here as its own
decision.

## Decisions

### 1. Light color tokens (supersedes Decision 1's palette)

**File:** `src/classiflow/frontend/src/index.css`

Same 14 variable names, same two font-family variables, unchanged font families — only the
color values change:

```css
:root {
  /* Backgrounds */
  --color-bg: #F7F3EA;            /* was #14110f */
  --color-bg-inset: #EFE7D4;      /* was #100d0a */
  --color-surface: #FFFFFF;       /* was #1b1712 */
  --color-surface-hover: #F4EEE0; /* was #221d16 */

  /* Borders */
  --color-border: #E4DBC8;        /* was #322a20 */
  --color-border-subtle: #EFE8D8; /* was #2a2319 */

  /* Text */
  --color-text: #2A2318;          /* was #f2ead9 */
  --color-text-muted: #6b5f4d;    /* was #a89a80 */
  --color-text-faint: #8a7d64;    /* was #6b5f4d */
  --color-text-pending: #b6ab92;  /* was #57503f */

  /* Accents -- darkened relative to their dark-theme values: a hue tuned for contrast
     against near-black often fails contrast against cream at the same lightness. */
  --color-accent: #B4552E;        /* was #c1663a */
  --color-success: #4d6b3f;       /* was #6b8f5a */
  --color-warning: #a1752c;       /* was #d49d3c */
  --color-danger: #9c3b30;        /* was #b5453a */

  /* Type -- unchanged */
  --font-serif: Georgia, "Times New Roman", serif;
  --font-mono: "Courier New", ui-monospace, monospace;
}
```

Because every page already consumes these tokens rather than hardcoded colors, this one file
change re-themes the entire app — no per-page color work needed. Component-level color usage
(badge background tints like `--color-success` at partial opacity, e.g.
`bg-[var(--color-success)]/20`) needs no change either — it's still deriving from the same
token, just a lighter starting color underneath.

### 2. Uniform type-scale bump

Validated against a realistic-scale mockup of the Classification page (26px page title, 15px
table body text, 13-14px mono/label text) — a real increase over what's live today, not a
scaling artifact of a compressed comparison thumbnail.

**Mechanical, one step up on Tailwind's scale, applied everywhere** rather than page-by-page
tuning: `text-xs`→`text-sm`, `text-sm`→`text-base`, `text-base`→`text-lg`, `text-lg`→`text-xl`,
`text-xl`→`text-2xl`. 54 occurrences across 10 files
(`UsersPage.tsx`, `AuditLogPage.tsx`, `ProcessingPage.tsx`, `ChatPage.tsx`,
`DocumentDetailPage.tsx`, `ClassificationPage.tsx`, `PdfViewer.tsx`, `DataTable.tsx`,
`Sidebar.tsx`, `StepTimeline.tsx`).

A uniform bump was chosen over bespoke per-page tuning because only the Classification page was
actually reviewed against a mockup — tuning the other five pages individually would mean guessing
at sizes nobody has seen, for a problem only demonstrated on one page. The mechanical rule answers
the actual feedback and applies consistently everywhere for free.

One exception worth calling out during implementation, not a new decision: any place a `text-*`
class is already `text-2xl` or larger (page-level display headings, if any exceed the enumerated
scale) has no next step defined in this rule and should be left unchanged — this spec's scale
table only covers `xs` through `xl`, which is everything found in the current codebase.

## Non-Goals

- **No dark-mode toggle.** This replaces the single existing palette; it does not add a
  light/dark switch. The app has never had a theme toggle, and none of the feedback that triggered
  this spec asked for one.
- **No layout, component, or motion changes.** Decisions 2-7 of the original visual-redesign spec
  (layout shell, the phase-grouped timeline, per-page structure, motion) are unchanged — this spec
  only touches color values and text-size utility classes.
- **No revisiting the "Console" or "Ledger" directions.** Both were shown and rejected in favor of
  staying close to the existing Archive identity.
- **No changes to the two out-of-scope items raised alongside this** (the "Indexed" table column,
  the chat/processing VRAM isolation work) — both have their own separate specs.

## Testing

This is a pure CSS-value and Tailwind-class change with no new logic — no new unit tests. The
project's own frontend test suite (Vitest + Testing Library) doesn't assert on color values or
text-size classes today, and shouldn't start doing so for a redesign like this: those tests would
break on every future palette tweak while verifying nothing about actual behavior.

Verification is visual: run `uv run poe serve` (or `serve-ui` alone) and check each of the app's
pages by eye — Processing, Classification, Document Detail (all four tabs), Users, Audit Log,
Chat — for legibility and that nothing regressed (contrast on badges/buttons, no color hardcoded
outside the token system that got missed). Hand this to the user per the project's
execution-workflow rule rather than screenshotting it myself.

Run `uv run poe check` (lint + typecheck, including the frontend's ESLint/Prettier steps) per the
project's standard gate — hand to the user rather than running directly.
