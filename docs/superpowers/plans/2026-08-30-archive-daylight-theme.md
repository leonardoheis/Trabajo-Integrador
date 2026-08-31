# Archive, Daylight Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flip the app's dark "Archive" theme to a light one with the same identity (same
token names, same Georgia serif + Courier New mono fonts, same "municipal records office"
feel), and bump the type scale one Tailwind step up everywhere, per user feedback that the
current theme is too dark and text reads too small.

**Architecture:** A single-file color-token recolor (`src/classiflow/frontend/src/index.css`)
that re-themes the whole app for free, since every page already consumes these CSS custom
properties rather than hardcoded colors. Plus a mechanical, uniform Tailwind text-size class
bump across the 10 files that currently use `text-xs`/`text-sm`/`text-base`/`text-lg`/`text-xl`.
No component, layout, or logic changes.

**Tech Stack:** React 19, TypeScript, Tailwind v4, plain CSS custom properties (no CSS-in-JS).

**Spec:** `docs/superpowers/specs/2026-08-30-archive-daylight-theme-design.md`

## Global Constraints

- No dark-mode toggle — this replaces the single existing palette, it does not add a switch.
- No layout, component, or motion changes — only color values and text-size utility classes.
- No new npm dependencies.
- No revisiting the "Console" or "Ledger" directions shown during design — both were rejected.
- No automated tests for this plan (spec's own Testing section: this is a pure CSS-value and
  Tailwind-class change with no new logic; tests asserting on color hex values or text-size
  classes would break on every future palette tweak while verifying nothing about behavior).
  Verification is visual, via manual review in a running dev server.

---

### Task 1: Light color tokens

**Files:**
- Modify: `src/classiflow/frontend/src/index.css`

**Interfaces:**
- No code interfaces — this is a CSS custom-property value change. Every component already
  reads these tokens by name (`var(--color-bg)`, etc.); nothing about how they're consumed
  changes.

- [ ] **Step 1: Replace the `:root` color block**

Current file (verbatim, for reference):

```css
@import "tailwindcss";

:root {
  /* Backgrounds */
  --color-bg: #14110f;
  --color-bg-inset: #100d0a;
  --color-surface: #1b1712;
  --color-surface-hover: #221d16;

  /* Borders */
  --color-border: #322a20;
  --color-border-subtle: #2a2319;

  /* Text */
  --color-text: #f2ead9;
  --color-text-muted: #a89a80;
  --color-text-faint: #6b5f4d;
  --color-text-pending: #57503f;

  /* Accents */
  --color-accent: #c1663a;
  --color-success: #6b8f5a;
  --color-warning: #d49d3c;
  --color-danger: #b5453a;

  /* Type */
  --font-serif: Georgia, "Times New Roman", serif;
  --font-mono: "Courier New", ui-monospace, monospace;
}

html,
body,
#root {
  height: 100%;
}

body {
  margin: 0;
  background: var(--color-bg);
  color: var(--color-text);
  font-family: var(--font-serif);
}
```

Replace only the color values inside `:root` (keep both `--font-serif`/`--font-mono` and
everything outside `:root` exactly as-is):

```css
:root {
  /* Backgrounds */
  --color-bg: #F7F3EA;
  --color-bg-inset: #EFE7D4;
  --color-surface: #FFFFFF;
  --color-surface-hover: #F4EEE0;

  /* Borders */
  --color-border: #E4DBC8;
  --color-border-subtle: #EFE8D8;

  /* Text */
  --color-text: #2A2318;
  --color-text-muted: #6b5f4d;
  --color-text-faint: #8a7d64;
  --color-text-pending: #b6ab92;

  /* Accents */
  --color-accent: #B4552E;
  --color-success: #4d6b3f;
  --color-warning: #a1752c;
  --color-danger: #9c3b30;

  /* Type */
  --font-serif: Georgia, "Times New Roman", serif;
  --font-mono: "Courier New", ui-monospace, monospace;
}
```

- [ ] **Step 2: Start the frontend dev server and visually verify**

Run (hand this to the user per this repo's execution-workflow rule, do not run it yourself):

```
uv run poe serve-ui
```

Open each page — Processing, Classification, Document Detail (all tabs), Users, Audit Log,
Chat — and confirm: light cream background, readable dark text, no leftover dark surfaces
(check `StepTimeline`'s pending/done states and `StatusBadge` colors specifically, since they
render at partial opacity over the token colors and are the most likely spot for a contrast
miss).

- [ ] **Step 3: Commit**

```bash
git add src/classiflow/frontend/src/index.css
git commit -m "feat: switch the Archive theme from dark to light (Daylight)"
```

---

### Task 2: Uniform type-scale bump

**Files:**
- Modify: `src/classiflow/frontend/src/pages/UsersPage.tsx`
- Modify: `src/classiflow/frontend/src/pages/AuditLogPage.tsx`
- Modify: `src/classiflow/frontend/src/pages/ProcessingPage.tsx`
- Modify: `src/classiflow/frontend/src/pages/ChatPage.tsx`
- Modify: `src/classiflow/frontend/src/pages/DocumentDetailPage.tsx`
- Modify: `src/classiflow/frontend/src/pages/ClassificationPage.tsx`
- Modify: `src/classiflow/frontend/src/components/PdfViewer.tsx`
- Modify: `src/classiflow/frontend/src/components/DataTable.tsx`
- Modify: `src/classiflow/frontend/src/components/Sidebar.tsx`
- Modify: `src/classiflow/frontend/src/components/StepTimeline.tsx`

**Interfaces:**
- No code interfaces — purely Tailwind utility class names inside JSX `className` strings.

This is one batched task, not ten — the same mechanical rule applies identically across all
ten files, so per this repo's execution convention for same-shape work, it's a single dispatch
rather than one task per file.

- [ ] **Step 1: Apply the class-size mapping in every listed file**

In every `className` (including inside template literals with conditional classes), bump each
of these Tailwind text-size utilities by exactly one step:

```
text-xs   -> text-sm
text-sm   -> text-base
text-base -> text-lg
text-lg   -> text-xl
text-xl   -> text-2xl
```

Rules:
- Apply the mapping only to `text-*` size utilities (e.g. `text-sm`, `font-mono text-xs`) —
  do not touch color utilities that happen to contain similar substrings, `text-[var(--color-*)]`
  color classes, or non-Tailwind text (comments, literal strings the app renders).
- If a file has no occurrence of any of the five sizes, leave it untouched (some of the ten
  listed files may only use one or two of the five sizes — that's expected, not a gap).
- Any `text-*` size found in these ten files that is `text-2xl` or larger has no next step
  defined by this mapping and must be left unchanged (the spec's own scope only covers `xs`
  through `xl`, since that's everything present in the current codebase).
- Do not touch any file outside this list of ten, even if it also contains `text-*` classes —
  the spec's mechanical rule was scoped to exactly these ten files (the full set found in a
  prior audit of the codebase).

- [ ] **Step 2: Verify with the linter/typechecker**

```
uv run poe lint
```

This won't catch a missed or wrong class rename (Tailwind classes are just strings to ESLint/
TypeScript), but it confirms nothing else broke. The real check is Step 3.

- [ ] **Step 3: Visual verification**

Same as Task 1 Step 2 — hand `uv run poe serve-ui` to the user, walk every page, confirm text
reads larger throughout and nothing looks broken (overflow, clipped text, misaligned badges).

- [ ] **Step 4: Commit**

```bash
git add src/classiflow/frontend/src/pages/UsersPage.tsx src/classiflow/frontend/src/pages/AuditLogPage.tsx src/classiflow/frontend/src/pages/ProcessingPage.tsx src/classiflow/frontend/src/pages/ChatPage.tsx src/classiflow/frontend/src/pages/DocumentDetailPage.tsx src/classiflow/frontend/src/pages/ClassificationPage.tsx src/classiflow/frontend/src/components/PdfViewer.tsx src/classiflow/frontend/src/components/DataTable.tsx src/classiflow/frontend/src/components/Sidebar.tsx src/classiflow/frontend/src/components/StepTimeline.tsx
git commit -m "feat: bump the type scale one step up across all pages"
```

---

### Task 3: Whole-app verification

- [ ] Run `uv run poe check` (lint + typecheck + full backend test suite + pre-commit,
  including frontend eslint/prettier) — hand to the user per this repo's execution-workflow
  rule.
- [ ] Manual walkthrough (hand to the user, `uv run poe serve` running): confirm every page
  reads correctly in the new light theme at the new type scale, with particular attention to
  `StepTimeline`'s phase-grouped states and `StatusBadge`'s color-coded pills, since both derive
  their look from the token colors at partial opacity and are the most likely place a contrast
  problem would show up first.
