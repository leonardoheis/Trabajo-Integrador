# CLAUDE.md — Classiflow

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

## Conventions

- **Python**: standard library + aiohttp / aiofiles / tqdm / beautifulsoup4 / weasyprint.
- Package source lives in `src/classiflow/`. Scripts live in `scrapper/`.
- All comments, docstrings, and commit messages are in English.
- Line length: 100. Quote style: double. (Configured in `[tool.ruff]`.)
- Type annotations required on all functions in `src/` (mypy strict).

## Git workflow

**Commits, pushes, and pull requests are always initiated by the human.**
Claude prepares and verifies changes but never commits, pushes, or opens PRs autonomously.

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
