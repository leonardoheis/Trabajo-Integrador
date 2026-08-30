# Knowledge Base Branch Migration — Design Spec

## Status

Approved — in progress. Claude/Anthropic scope decided (see Decision 5): dropped entirely, not
ported.

## Context

The Stage 5 Knowledge Base / RAG feature (chunking, embeddings, vector store, retrieval, a
Claude/llama.cpp-swappable chat LLM, and the `DocumentKb` catalogue table) was built end-to-end
on `origin/feat/documents-kb` (tip `ed4e818`), with 7 backend test files and a clean,
well-documented `src/classiflow/knowledge/` package. That branch is not merged anywhere and is
not checked out locally.

Meanwhile, `feat/stage5-kb-tracing` (the current branch) independently landed two unrelated
pieces of work that `feat/documents-kb` predates entirely:

- Weave/W&B LLM tracing (`e06cb3d`, `ac32998`, `6775e26`) — `observability.py`,
  `Settings.WANDB_*`/`tracing_enabled`, the `weave`/`wandb` dependencies, and (as of `6775e26`)
  automatic `weave.op()` wrapping of every `BaseNode.run()`.
- OCR/job-status work (`bc3f89c`) — `ClassificationSummary.status`, `job.status` surfaced through
  `documents/endpoints.py` and `documents/schemas.py`, `StepTimeline`/`ClassificationPage`
  frontend changes.

`feat/documents-kb`'s diffs to shared files (`settings.py`, `pyproject.toml`, `.env.example`,
`services/pipeline/service.py`, `api/dependencies.py`) were written against the pre-tracing,
pre-status codebase. Taken at face value, applying that branch's changes to those files would
**delete** the tracing feature and drop the status field — not because the KB feature needs
either removed, but because the branch simply never saw them exist. Direct review (see below)
also found the same commit bundles three changes unrelated to the KB feature itself: removing
`unload_bert()` from `PipelineService._run` (VRAM management `stage5` still needs), bumping
`MAX_CONCURRENT_JOBS` 1→2, and reversing a deliberate DI policy in `api/dependencies.py` that
kept LangChain chains out of the container to avoid holding GGUF models resident.

Separately, commit `ed4e818` on `feat/documents-kb` claims to "Implement frontend Knowledge Base
integration" but does not: `ChatPage.tsx` is still the literal "Coming soon — Stage 5." stub, and
none of `DocumentDetailPage.tsx`, `ClassificationPage.tsx`, or `api/knowledge.ts` were touched.
What that commit actually added is a complete design spec
(`docs/superpowers/specs/2026-08-26-frontend-knowledge-base-design.md`) and a 7-task
implementation plan (`docs/superpowers/plans/2026-08-26-frontend-knowledge-base.md`, status "not
started") describing exactly this frontend work — written against `stage5`'s frontend state
*before* `bc3f89c` added job-status UI. Those documents don't exist on `stage5` and need to be
brought over (and re-validated against the current frontend) before the frontend work in this
migration can proceed.

This spec defines what "port the KB feature onto `stage5`" means precisely: which files move
verbatim, which need a hand-merge and why, and which of `feat/documents-kb`'s changes are
excluded as out of scope for this migration.

## Decisions

### 1. Migration strategy: targeted port, not `git merge`

**Decision:** Cherry-pick/copy net-new files from `origin/feat/documents-kb` as-is, and hand-merge
the small number of shared files that both branches independently changed. Do not
`git merge origin/feat/documents-kb`.

**Rationale:** A real merge forces conflict resolution on `settings.py`, `pyproject.toml`,
`services/pipeline/service.py`, `api/dependencies.py`, and `documents/schemas.py` regardless —
both branches touch all five independently — but a merge additionally pulls in the tracing
deletion and the three unrelated bundled changes by default, requiring them to be un-done
*after* the merge completes and risking one being missed. A targeted, file-by-file port produces
a diff where every line has a known, stated reason to exist.

### 2. Backend: port the `knowledge/` package and its direct dependents verbatim

**Decision:** The following are copied unchanged from `origin/feat/documents-kb`, since they were
confirmed (by direct file-by-file review) to already match `stage5`'s house conventions and have
no overlapping changes on `stage5`:

- `src/classiflow/knowledge/` — the entire package (domain, chunking, embeddings, vectordb,
  retrieval, prompts, llm, chat, indexing, utils, `README.md`, `exceptions.py`). Uses the
  project's `@dataclass` exception-subclass pattern, `BaseEntity`-based domain models, and the
  package's own documented "no ports layer except where 2+ implementations exist" convention
  (`VectorStore`, `ChatLlm` ABCs; everything else named directly).
- `src/classiflow/database/repositories/document_kb.py` and
  `src/classiflow/domain/repositories/document_kb.py` — `IDocumentKbRepository` Protocol +
  `SqlDocumentKbRepository`/`InMemoryDocumentKbRepository` pair, matching the exact repository
  pattern used everywhere else in the codebase (e.g. `enriched_record.py`).
- `src/classiflow/api/routes/knowledge/` (`__init__.py`, `endpoints.py`, `schemas.py`) — three
  routes (`POST /knowledge/chat`, `/chat/stream`, `/synchronize-kb`), `BaseSchema`-based schemas
  with `from_domain` mapping, router-wide `Depends(get_current_user)` — matches the
  `documents/` route module pattern exactly.
- `src/classiflow/api/error_handlers/knowledge.py` — `handle_chat_refusal` (422),
  `handle_knowledge_error` (503), same `assert isinstance(exc, ...)` handler shape as every
  other file in `error_handlers/`.
- `alembic/versions/0009_documents.py`, `0010_rename_documents_to_document_kb.py`,
  `0011_add_enriched_record_filename_sha256.py` — apply directly; `stage5` is at `0008` with no
  numbering collision.
- Tests: `tests/knowledge/` (whole directory), `tests/api/routes/test_knowledge.py`,
  `tests/shared/test_pipeline_service_kb_sync.py`.
- Notebooks: `src/classiflow/playground/stage5/knowledge_indexing.ipynb`,
  `synchronize_kb.ipynb`.

**Also apply directly** (isolated additions within files that otherwise don't conflict):

- `src/classiflow/database/models.py` — add the `DocumentKb` class and the two new
  `EnrichedRecord` columns (`filename`, `sha256`).
- `src/classiflow/domain/repositories/__init__.py` and
  `src/classiflow/database/repositories/enriched_record.py` — add `find_unindexed()` and the
  `IDocumentKbRepository` re-export.
- `src/classiflow/api/error_handlers/types.py` — register `KnowledgeError`'s handler in
  `EXCEPTION_HANDLERS` (`ChatRefusalError` is dropped along with Claude — see Decision 5, so
  there is no more-specific-subclass entry to order before it).
- `src/classiflow/api/routes/registry.py` — add the knowledge router to `ROUTERS`.
- `src/classiflow/injections/production.py` / `injections/test.py` — add the KB provider blocks
  (`embedder`, `vector_store`, `document_metadata_repo`, `chunker`, `chat_llm` as
  `providers.Singleton(LlamaCppChatLlm)`, `retriever`, `chat_service`; test-side
  `_StubEmbedder`/`_StubChatLlm`/`_StubMetadataRepository`, `document_kb_repo`, `indexer`) and
  wire `indexer`/`document_kb_repo` into the existing `PipelineService(...)` provider call. These
  already use `stage5`'s exact `Singleton`/`ThreadSafeSingleton`/`Factory` conventions, confirmed
  line-by-line (no `providers.Selector` needed with a single provider — see Decision 5).
- `src/classiflow/api/dependencies.py` — add **only** the three new functions (`get_indexer`,
  `get_retriever`, `get_chat_service`) and the two new params on `get_pipeline_service`.

### 3. Backend: hand-merge three files instead of copying

**Decision:** `settings.py`, `services/pipeline/service.py`, and `pyproject.toml`/`.env.example`
are edited in place on `stage5`, adding only the KB-relevant lines, rather than replaced with
`feat/documents-kb`'s versions.

**`settings.py`:** add the new fields (`CHROMA_PATH`, `CHROMA_COLLECTION`, `EMBEDDING_MODEL`,
`CHUNK_SIZE`, `CHUNK_OVERLAP`, `RETRIEVAL_TOP_K`, `SCRAPPER_DIR`, `CHAT_MAX_TOKENS`,
`CHAT_MODEL_PATH`, `CHAT_MODEL_N_CTX`) plus their lowercase `@property` accessors, in the same
one-field-one-property style already used for every other setting. `CHAT_LLM_PROVIDER` and
`ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL` are not added — with Claude dropped (Decision 5) there is
only one chat provider, so a provider-selector setting would be dead config. Keep
`WANDB_API_KEY`/`WANDB_PROJECT`/`WEAVE_TRACE_LANGCHAIN`/`tracing_enabled` untouched. Do not
change `MAX_CONCURRENT_JOBS`.

**`services/pipeline/service.py`:** add `_build_document_kb`, the `indexer`/`document_kb_repo`
constructor params and instance attributes, `index_enriched_record`, `synchronize_kb`, and the
`filename=`/`sha256=` arguments on the `EnrichedRecord(...)` construction plus the
`await self.index_enriched_record(...)` call immediately after
`await self._enriched_record_repo.save(record)` in `_run_enrichment`. Keep the existing
`unload_bert()` call in `_run` exactly where it is.

**`pyproject.toml`:** add `chromadb>=0.5` to `dependencies` (`anthropic` is intentionally not
added — see Decision 5); add `"chromadb"`, `"chromadb.*"` to the mypy `ignore_missing_imports`
override; bump `max-args` from 9 to 11 in both `[tool.ruff.lint]`'s justification comment/value
and `[tool.pylint.design]`, updating the comment to list `indexer`/`document_kb_repo` alongside
the existing collaborators. Do not touch the `weave`/`wandb` dependencies or the `serve` script.
Run `uv sync` afterward.

**`.env.example`:** add the "Knowledge base (stage 5)" and "Chat agent" sections, with no
`CHAT_LLM_PROVIDER`/`ANTHROPIC_*` entries (Decision 5). Do not touch the existing W&B section.

### 5. Drop the Claude/Anthropic chat provider entirely

**Decision:** `llm/claude.py` (`ClaudeChatLlm`) is not ported. `ChatRefusalError` is removed from
`llm/exceptions.py` — it exists solely to surface an Anthropic API safety-decline response, which
has no llama.cpp equivalent. `Settings.chat_llm_provider`/`CHAT_LLM_PROVIDER`, `ANTHROPIC_API_KEY`,
and `ANTHROPIC_MODEL` are not added to `settings.py` or `.env.example`. The `anthropic` package is
not added to `pyproject.toml`. `chat_llm` is wired directly to
`providers.Singleton(LlamaCppChatLlm)` in both `injections/production.py` and (as a stub) in
`injections/test.py` — no `providers.Selector`.

**Rationale:** explicit user decision — Anthropic is out of scope for this project. The `ChatLlm`
ABC in `llm/chat_llm.py` is still kept even with a single production provider: `LlamaCppChatLlm`
in production vs. the test-only `_StubChatLlm` in `injections/test.py` are still two
implementations needing a common type to name, the same justification the codebase already uses
for `VectorStore` (`ChromaVectorStore` vs. `InMemoryVectorStore`). All doc comments in the
`knowledge/` package that referenced Claude/anthropic (`knowledge/__init__.py`, `llm/__init__.py`,
`llm/chat_llm.py`, `knowledge/README.md`) are updated to describe the single-provider setup.

### 4. Frontend: build from spec, not port from branch

**Decision:** Bring over the two existing planning documents from `feat/documents-kb`
(`docs/superpowers/specs/2026-08-26-frontend-knowledge-base-design.md` and
`docs/superpowers/plans/2026-08-26-frontend-knowledge-base.md`) as-is, since no frontend code
exists to port — then execute that plan's 7 tasks against `stage5`'s current frontend, with one
addition: **before Task 4** (the Knowledge Base tab on Document Detail), re-read the current
`DocumentDetailPage.tsx` and `ClassificationPage.tsx`, since both were modified by `bc3f89c`
after the spec was written (job status badge, `StepTimeline` changes). Confirm the `Tab` union,
`TABS` array, and toolbar row the spec assumes still match; adjust insertion points if not. No
other change to that plan's scope, task order, or non-goals.

**Rationale:** the spec is already well-scoped, reuses existing frontend conventions
(`apiFetch`, TanStack Query, `useMutation`, no new npm dependencies, no toast system) and was
written by someone with full context of this codebase's frontend patterns — rewriting it from
scratch would be redundant. The one addition accounts for the only material drift since it was
written.

## Non-Goals

- No changes to `knowledge/` package internals (chunking, embedding, retrieval) beyond the
  Claude-removal edits in Decision 5 — everything else ports unchanged.
- No re-litigating the frontend design spec's own Decisions 8–12 — this document only adds the
  backend-tracing/status reconciliation step and defers everything else to that spec.
- No porting of the Weave/W&B tracing removal, the `unload_bert()` removal, the
  `MAX_CONCURRENT_JOBS` bump, or the DI-injection-of-chains reversal — all four are explicitly
  excluded (see Context).
- No changes to the `serve` poe task or any other unrelated `pyproject.toml` diff on
  `feat/documents-kb`.

## Testing

- `uv run poe check` (lint, typecheck, full pytest suite including the new `tests/knowledge/*`,
  `tests/api/routes/test_knowledge.py`, `tests/shared/test_pipeline_service_kb_sync.py`, and the
  existing 411 tests currently on `stage5`) — the standard project verification gate. Hand this
  command to the user to run per this repo's execution-workflow rule.
- `uv run alembic upgrade head` — confirm `0009`→`0011` apply cleanly against `stage5`'s current
  schema (at `0008`).
- Frontend: `uv run poe check` covers eslint/prettier/vitest; additionally, manually exercise the
  Chat page streaming, the Document Detail KB tab (indexed and not-indexed states), and the
  Classification page sync button in a running dev server, per this repo's UI-testing rule.
