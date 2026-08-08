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
├── notebooks/                      Jupyter notebooks
│   └── colab_downloader.ipynb      Bulk download via Google Colab
├── scrapper/                       Ingestion scripts and CSV metadata
│   ├── downloader.py               Async bulk downloader — Phase 1 ingestion
│   └── *.csv                       One CSV per document category (10 types)
├── src/
│   └── classiflow/                 Main Python package
├── pyproject.toml                  Dependencies and tool configuration (managed by uv)
├── uv.lock                         Locked dependency graph
├── .pre-commit-config.yaml         Pre-commit hooks (ruff, mypy, gitleaks, uv-lock)
└── DEPLOY.md                       Deployment options and scale estimates
```

## Environment setup

```bash
uv sync --dev          # install all deps (runtime + dev group) into .venv
```

The `.venv/` directory is gitignored. Always use `uv sync` — do not use `pip install`.

## Running the downloader (ingestion Phase 1)

```bash
uv run python scrapper/downloader.py --output ./downloads --concurrency 5 --delay 0.5
```

Arguments:
- `--output` — destination folder (default: `./downloads`)
- `--concurrency` — parallel downloads, keep ≤ 5 to avoid rate-limiting (default: 5)
- `--delay` — seconds between requests (default: 0.5)

A `checkpoint.json` file tracks progress; re-running skips already-downloaded files.

## Code revision

**Run after every modification:**

```bash
uv run poe check
```

This is the single verification gate. It runs in order:

| Step | Command | What it checks |
|------|---------|---------------|
| `lint` | `ruff check . && ruff format --check .` | Style and lint rules |
| `typecheck` | `mypy src && nbqa mypy notebooks` | Type correctness |
| `nbtest` | `pytest --nbmake notebooks` | Notebooks execute without error |

Individual tools (when you need to run one step in isolation):

```bash
uv run poe lint        # lint + format check only
uv run poe typecheck   # mypy only
uv run poe test        # pytest tests/ only
uv run poe fmt         # auto-format (ruff format .)
uv run poe precommit   # full pre-commit run on all files
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
| `nbqa-mypy` | Type correctness of notebooks |

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

- **Python**: standard library + aiohttp / aiofiles / tqdm / beautifulsoup4 / weasyprint.
- Package source lives in `src/classiflow/`. Scripts live in `scrapper/`.
- All comments, docstrings, and commit messages are in English.
- Line length: 100. Quote style: double. (Configured in `[tool.ruff]`.)
- Type annotations required on all functions in `src/` (mypy strict).
- **Never use `from __future__ import annotations`** — quote forward references explicitly
  (`"MyType"`) instead. Only acceptable for true circular cross-file import cycles.
- **Never use `from typing import TYPE_CHECKING`** unless the import causes a real circular
  dependency. Stdlib and cheap third-party imports go at the top level unconditionally.

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
2. Verify `uv run poe lint`, `uv run poe typecheck`, and all relevant tests pass.
3. Present a **change summary**: each file (new/modified), what changed, and test results.
4. Ask: *"Do you authorize the PR creation?"*
5. Wait for explicit authorization (e.g. "authorize", "yes", "go ahead") before running any `git commit`, `git push`, or `gh pr create` command.

Saying "execute task X" or "implement and make a PR" is **not** authorization — the user must explicitly approve after reviewing the summary.

**Base branch:** All task PRs target `feat/ingesta-pipeline` (the sprint integration branch), never `main`.

## Downloader link resolution strategies

| Type | How it works |
|------|-------------|
| `direct_pdf` | URL already points to the PDF |
| `normativa` | Extracts `idNormativa` and builds a direct download URL |
| `boletin_html` | Scrapes bulletin index page to find internal PDF IDs |
| `html_to_pdf` | Downloads a Plone HTML page and converts it via weasyprint |
| `scrape_page` | Generic scraping for compendium pages |

## Downloaded documents (Phase 1 output)

Available on Google Drive:
https://drive.google.com/drive/folders/1_IPfa4m1mmz6wFPOLtEf3T4xYknJap7B?usp=drive_link
