# CLAUDE.md — Classiflow

<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tool** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them, including dynamic-dispatch hops grep can't follow. Name a file or symbol in the query to read its current line-numbered source. If it's listed but deferred, load it by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` prints the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->

Classiflow is a multi-agent document classification system for Municipalidad de Rosario (Argentina).
It ingests municipal documents from multiple sources, extracts and enriches their content, classifies
them using LLM agents with confidence scoring, and exposes the results through a chat interface and
a web UI.

## Architecture

```
Sources (inputs)
  ├── Municipal dataset (CSV + PDFs)
  ├── Web scraping
  └── Manual upload (PDF · DOCX · img)
          │
          ▼
  ┌─────────────────────────────────────────────┐
  │                 Orchestrator                │
  │                                             │
  │  Ingestion ──► Text extraction              │
  │                     │                       │
  │              Refinement and enrichment       │
  │                     │                       │
  │  ┌──────────────────────────────────────┐   │
  │  │  Ingestion agent                     │   │
  │  │  receives · validates · detects lang │   │
  │  │                                      │   │
  │  │  Classification agent                │   │
  │  │  document type · confidence score    │   │
  │  │                                      │   │
  │  │  Confidence gate                     │   │
  │  │  auto · review · escalation          │   │
  │  │                                      │   │
  │  │  Routing agent                       │   │
  │  │  directory · audit log               │   │
  │  └──────────────────────────────────────┘   │
  └─────────────────────────────────────────────┘
          │
          ├── Knowledge base (chunks · vectors · sources)
          │         │
          │   Chat agent (query · retrieve · respond with sources)
          │
          ├── Outputs
          │     ├── Classified documents
          │     ├── Review queue (low confidence)
          │     └── Audit log (every decision)
          │
          └── Web interface
                upload · agent visualization · classification · chat
```

## Project structure

```
/
├── .claude/                        Claude Code project settings
├── documents/                      Reference documents and architecture diagrams
├── src/
│   └── classiflow/                 Main Python package
├── pyproject.toml                  Dependencies and tool configuration (managed by uv)
├── uv.lock                         Locked dependency graph
└── .pre-commit-config.yaml         Pre-commit hooks (ruff, mypy, gitleaks, uv-lock)
```

## Environment setup

```bash
uv sync --dev          # install all deps (runtime + dev group) into .venv
```

The `.venv/` directory is gitignored. Always use `uv sync` — do not use `pip install`.

## Code revision

**Run after every modification:**

```bash
uv run poe check
```

This is the single verification gate. It runs in order:

| Step | Command | What it checks |
|------|---------|---------------|
| `lint` | `ruff check . && ruff format --check .` | Style and lint rules (Python only) |
| `typecheck` | `mypy src` | Type correctness |
| `coverage` | `pytest tests -v --cov=. ...` | Full backend test suite + coverage report |
| `precommit-reloaded` | `uv run --all-groups pre-commit run --all-files` | Every pre-commit hook, including frontend eslint/prettier and codespell |

`poe lint`/`poe typecheck` are Python-only — frontend lint/format checks only run as part of
`precommit-reloaded` (inside the full `poe check`), not via any standalone `poe` task.

Individual tools (when you need to run one step in isolation):

```bash
uv run poe lint        # lint + format check only (Python)
uv run poe typecheck   # mypy only
uv run poe test        # pytest tests/ only, no coverage report
uv run poe coverage    # pytest tests/ with coverage report (what `check` actually runs)
uv run poe fmt         # auto-format (ruff format .)
uv run poe precommit   # full pre-commit run on all files (verbose)
```

Hooks enforced on every commit (see `.pre-commit-config.yaml`):

| Hook | What it checks |
|------|---------------|
| `trailing-whitespace` | Trailing spaces |
| `end-of-file-fixer` | Files end with a newline |
| `check-yaml` | Valid YAML syntax |
| `debug-statements` | No `breakpoint()` / `pdb` left in code |
| `uv-lock` | `uv.lock` is in sync with `pyproject.toml` |
| `gitleaks` | No secrets committed |
| `ruff-format` | Code formatted per ruff config |
| `ruff-check` | Lint rules (exits non-zero if fixes were applied) |
| `mypy` | Type correctness of `src/` |

## Execution workflow

**Never run notebooks or other commands in the background.** The user runs them
themselves. When a notebook or command needs to be executed (e.g. `jupyter execute`,
`uv run poe check`, a benchmark script), hand over the exact command and wait — do not
invoke it yourself, foreground or background.

## LangGraph agent structure

Source: https://docs.langchain.com/oss/python/langgraph/application-structure

The canonical LangGraph layout for a Python + pyproject.toml project is:

```
my-app/
├── my_agent/
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── tools.py      # tools the graph can call
│   │   ├── nodes.py      # node functions
│   │   └── state.py      # graph state definition
│   ├── __init__.py
│   └── agent.py          # graph construction entrypoint
├── .env
├── langgraph.json         # LangGraph Platform config
└── pyproject.toml
```

**How this maps to Classiflow's `ingesta/` package:**

| Canonical | Classiflow equivalent | Notes |
|---|---|---|
| `agent.py` | `ingesta/coordinator.py` | builds and runs the LangGraph state machine |
| `utils/state.py` | `ingesta/domain/state.py` | `JobState` TypedDict |
| `utils/nodes.py` | `ingesta/agents/agent*.py` | one file per agent instead of one combined file |
| `utils/tools.py` | `ingesta/llm_provider.py` + `ingesta/prompts/` | LLM singleton + prompt chains |

Classiflow splits `nodes.py` into individual agent files — this is intentional and correct for
this project's size. The `domain/` package plays the `utils/` role.

**`langgraph.json` format** (add to repo root when deploying to LangGraph Platform):

```json
{
  "dependencies": ["."],
  "graphs": {
    "ingesta": "./src/classiflow/ingesta/coordinator.py:coordinator"
  },
  "env": "./.env"
}
```

Apply this structure to every new LangGraph agent added to the project.

---

## Conventions

- Package source lives in `src/classiflow/`.
- All comments, docstrings, and commit messages are in English.
- Line length: 100. Quote style: double. (Configured in `[tool.ruff]`.)
- Type annotations required on all functions in `src/` (mypy strict).
- **Never use `from __future__ import annotations`** — quote forward references explicitly
  (`"MyType"`) instead. Only acceptable for true circular cross-file import cycles.
- **Never use `from typing import TYPE_CHECKING`** unless the import causes a real circular
  dependency. Stdlib and cheap third-party imports go at the top level unconditionally.
- **Never use `Any`** — it disables mypy checking. Use `TypedDict`, `BaseModel`, `object`,
  or an explicit `Union` instead. The only acceptable exception is overriding a third-party
  method that declares `**kwargs: Any` in its signature (and even then, prefer removing
  `**kwargs` from the override if the mock/subclass does not forward them).

### Exception style

Each service that raises custom exceptions gets its own `exceptions.py` alongside it.
Define a plain base class and `@dataclass` subclasses for each distinct error case:

```python
from dataclasses import dataclass


class ServiceError(Exception): ...  # base — callers can catch this broadly


@dataclass
class SpecificError(ServiceError):
    field: str  # typed, inspectable by callers

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.field} is required"
```

Rules:
- `__post_init__` **must** call `super().__init__(str(self))` so `str(exc)` and logging work.
- Raise the specific subclass, never the base class directly.
- Use `try/except SpecificInfraError` (never bare `except` or `except Exception`).
- Full rationale: `.claude/learnings.md`

### `__init__.py` content

`__init__.py` files may only contain `__version__`, re-exports, and `__all__`.
No executable statements, no function definitions, no side-effectful calls — ruff RUF067
enforces this. `configure_container()` is called inside `create_app()`, never at import time.

### `__init__` vs `BaseModel`

- **Domain / value objects** (data that moves between layers) → `BaseModel`
- **Services / repositories** (hold injected dependencies or mutable runtime state) → plain `__init__`

Full rationale: `.claude/learnings.md`

## Git workflow

**Commits, pushes, pull requests, and any other git operations that affect the remote are always initiated by the human with an explicit order.**
Claude prepares and verifies changes but **never** runs `git commit`, `git push`, `git pull`, or `gh pr create` unless the user explicitly says so in that message.

### PR authorization protocol

Before opening a PR, Claude must:
1. Implement the changes in a worktree branch.
2. Run `uv run poe check` — all steps (lint, typecheck, coverage, precommit-reloaded) must pass.
3. Run `uv run --all-groups pre-commit run --all-files` — all hooks must pass.
4. Present a **change summary**: each file (new/modified), what changed, and test results.
5. Ask: *"Do you authorize the PR creation?"*
6. Wait for explicit authorization (e.g. "authorize", "yes", "go ahead") before running any `git commit`, `git push`, or `gh pr create` command.

Saying "execute task X" or "implement and make a PR" is **not** authorization — the user must explicitly approve after reviewing the summary.

**Base branch:** Stages 1–5 (ingesta pipeline through knowledge base + chat) are all done
and merged to `main` (PRs #17, #20, #21, #22, and the Stage 5 KB/chat/memory work landing
across PRs #25–#30). There is no active per-stage integration branch anymore — new work
is a short-lived feature branch cut directly from `main` (e.g. `feat/chat-vram-isolation`,
`feat/archive-daylight-theme`, `feat/inspectable-pipeline-steps`,
`feat/chat-streaming-and-autoscroll`, `feat/chat-markdown-and-memory`,
`feat/classification-search-and-sort`), PR'd back into `main` once done. Same authorization rule applies: implement on the branch, verify,
present the summary, wait for explicit "authorize"/"yes"/"go ahead" before pushing or
opening the PR.

## Downloaded documents (Phase 1 output)

Available on Google Drive:
https://drive.google.com/drive/folders/1_IPfa4m1mmz6wFPOLtEf3T4xYknJap7B?usp=drive_link
