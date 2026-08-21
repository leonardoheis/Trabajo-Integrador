# Stage 4 (Classification & Routing) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take every Stage 3 `EnrichedRecord` and produce a final classification decision — primary LLM label, a real BETO/OOD/SVM second opinion, foreign-municipality and smell/risk signals, a confidence-gated (and optionally LLM-judged) review route — then physically route the source document to `storage/documents/classified/<label>/` or `storage/documents/review/human_review/` and persist a `ClassificationRecord` with a full audit trail.

**Architecture:** A new top-level `classiflow/storage/` package (`IDocumentStorage` Protocol + `LocalDiskStorage`) gives both Stage 1 (staging) and Stage 4 (final routing) a swappable disk-backed seam. A new top-level `classiflow/classification/` package (mirroring `enrichment/`'s shape) hosts a 7-node LangGraph coordinator (primary classifier → second opinion → foreign municipality → smells/risk → confidence gate → conditional LLM judge → routing), with `classification/bert/` holding code ported from the sibling `bert_tunning` repo (BETO embeddings, OOD scoring, SVM reviewer). `PipelineService._run()` chains straight from a successful `_run_enrichment()` into a new `_run_classification()`, mirroring Stage 3's own automatic-trigger shape. A new `/classification` API surface exposes the human-review queue and decision endpoint, reusing `RoutingNode` directly (no pipeline "resume").

**Tech Stack:** LangGraph (`StateGraph`), LangChain (`Runnable`/`RunnableLambda`/`StrOutputParser`), Pydantic (`BaseEntity`), SQLAlchemy 2.0 async + Alembic, `dependency_injector`, PyTorch + `transformers` (BETO forward pass), `scikit-learn`/`joblib` (SVM reviewer), `scipy` (Mahalanobis/OOD math), pytest.

**Spec:** `docs/superpowers/specs/2026-08-18-classification-routing-design.md` (supersedes/completes `docs/superpowers/specs/2026-08-17-bert-tunning-classification-integration-design.md`, "the BERT spec", for the Second Opinion Agent's package layout and label mapping — treated as settled and not re-litigated here).

## Global Constraints

- Line length 100, double-quote strings (ruff-enforced).
- mypy strict: never use `Any`. Never use `from __future__ import annotations` — quote forward references (`"MyType"`) instead. Never use `TYPE_CHECKING` unless avoiding a real circular import — this plan follows the one narrow precedent already in this codebase (`api/dependencies.py`'s `_FormatChain`/`_ContentChain`/`_EntityChain`, and `tests/ingesta/test_extraction_concurrency.py`'s `DocumentStep`/`JobState`) exactly, adding `_EntityChain`-style protocol aliases and test-only cast targets to those same existing blocks — no other new `TYPE_CHECKING` blocks.
- Domain/value objects (data crossing layers) → `BaseEntity` (`classiflow/domain/base.py`), never plain `BaseModel`. Services/nodes/repositories (hold dependencies or mutable state) → plain `__init__`.
- Exceptions: each service gets its own `exceptions.py` — a plain base class (`class XError(Exception): ...`) plus `@dataclass` subclasses that call `super().__init__(str(self))` in `__post_init__` and define `__str__`. Never raise the base directly; never use bare `except Exception`.
- `__init__.py` files contain only `__version__`, re-exports, and `__all__` — no executable statements.
- `uv run poe check` is the project's single verification gate. **Do not run it yourself** (or any notebook/benchmark command) — hand the exact command to the user and wait, per this project's standing convention. Plain `pytest tests/path::test -v` runs during the test-first loop within a task are fine to run directly.
- Git: never `git add`, `git commit`, `git push`, or open a PR without the user's explicit go-ahead in that message.
- All comments/docstrings/commit messages in English.
- Blocking, CPU-bound calls inside an async `run()`/method (SLM invocation, embedding computation, BETO forward pass, file I/O) are wrapped in `await asyncio.to_thread(...)` — `run()` is awaited directly on the event loop, unlike a LangGraph-dispatched sync node function, so a bare blocking call freezes every other concurrent request for its duration. See `node4_duplicate_control.py`'s `find_similarity`/`add` calls and `enrichment/nodes/entity_extractor.py`'s `extract` call for the established pattern.
- New DB models use `Integer`/`autoincrement=True` primary keys (this project's convention, not UUID — already corrected once for `EnrichedRecord`, corrected again here for `ClassificationRecord` vs. the BERT spec's original UUID sketch).

---

## Task 1: Storage package — `IDocumentStorage` Protocol + `LocalDiskStorage`

New top-level `classiflow/storage/` package (sibling to `ingesta/`/`enrichment/`, not inside `classification/` — Stage 1 needs `save_staged` too, and `ingesta` depending on `classification` would be the wrong direction). Real files land on disk now, behind a Protocol seam that lets a future blob backend replace `LocalDiskStorage` without touching any calling code.

**Files:**
- Create: `src/classiflow/storage/__init__.py`
- Create: `src/classiflow/storage/document_storage.py`
- Modify: `src/classiflow/settings.py`
- Modify: `.gitignore`
- Create: `tests/storage/__init__.py`
- Create: `tests/storage/test_document_storage.py`

**Interfaces:**
- Consumes: `classiflow.settings.Settings.document_storage_root` (new property, this task).
- Produces: `IDocumentStorage` (Protocol: `async def save_staged(self, job_id: str, filename: str, file_bytes: bytes) -> str`, `async def move_to_final(self, job_id: str, filename: str, subdirectory: str) -> str`). `LocalDiskStorage(root: str | None = None)` — `root` defaults to `Settings.document_storage_root` when omitted. Both methods return the resulting absolute path as `str`.

- [x] **Step 1: Write the failing test**

```python
# tests/storage/test_document_storage.py
from pathlib import Path

import pytest

from classiflow.storage.document_storage import LocalDiskStorage

pytestmark = pytest.mark.anyio


class TestLocalDiskStorageSaveStaged:
    async def test_writes_file_under_staging_with_job_id_prefix(self, tmp_path: Path) -> None:
        storage = LocalDiskStorage(root=str(tmp_path))

        staged_path = await storage.save_staged("job-1", "doc.pdf", b"%PDF-1.4 fake bytes")

        expected = tmp_path / "staging" / "job-1_doc.pdf"
        assert staged_path == str(expected)
        assert expected.read_bytes() == b"%PDF-1.4 fake bytes"

    async def test_creates_staging_directory_if_missing(self, tmp_path: Path) -> None:
        storage = LocalDiskStorage(root=str(tmp_path / "does" / "not" / "exist"))

        staged_path = await storage.save_staged("job-2", "doc.pdf", b"content")

        assert Path(staged_path).exists()


class TestLocalDiskStorageMoveToFinal:
    async def test_relocates_staged_file_to_subdirectory(self, tmp_path: Path) -> None:
        storage = LocalDiskStorage(root=str(tmp_path))
        staged_path = await storage.save_staged("job-3", "doc.pdf", b"content")

        final_path = await storage.move_to_final("job-3", "doc.pdf", "classified/ordenanzas")

        expected = tmp_path / "classified" / "ordenanzas" / "job-3_doc.pdf"
        assert final_path == str(expected)
        assert expected.read_bytes() == b"content"

    async def test_staged_file_no_longer_exists_at_old_path(self, tmp_path: Path) -> None:
        storage = LocalDiskStorage(root=str(tmp_path))
        staged_path = await storage.save_staged("job-4", "doc.pdf", b"content")

        await storage.move_to_final("job-4", "doc.pdf", "review/human_review")

        assert not Path(staged_path).exists()

    async def test_creates_final_parent_directories(self, tmp_path: Path) -> None:
        storage = LocalDiskStorage(root=str(tmp_path))
        await storage.save_staged("job-5", "doc.pdf", b"content")

        final_path = await storage.move_to_final("job-5", "doc.pdf", "review/human_review")

        assert Path(final_path).parent == tmp_path / "review" / "human_review"

    async def test_moves_a_file_already_routed_once_to_a_new_subdirectory(
        self, tmp_path: Path
    ) -> None:
        # The human-review -> accept flow (spec Decision 9): a job already moved to
        # review/human_review/ by one move_to_final call gets moved AGAIN, to
        # classified/<label>/, by a second call -- the file is no longer in staging/
        # by then, so move_to_final must find it wherever it currently sits.
        storage = LocalDiskStorage(root=str(tmp_path))
        await storage.save_staged("job-6", "doc.pdf", b"content")
        await storage.move_to_final("job-6", "doc.pdf", "review/human_review")

        final_path = await storage.move_to_final("job-6", "doc.pdf", "classified/ordenanzas")

        expected = tmp_path / "classified" / "ordenanzas" / "job-6_doc.pdf"
        assert final_path == str(expected)
        assert expected.read_bytes() == b"content"
        assert not (tmp_path / "review" / "human_review" / "job-6_doc.pdf").exists()
```

```python
# tests/storage/__init__.py
```
(empty — package marker, mirrors `tests/enrichment/__init__.py`)

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/storage/test_document_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.storage'`

- [x] **Step 3: Add `Settings.DOCUMENT_STORAGE_ROOT`**

In `src/classiflow/settings.py`, add after `ENRICHMENT_CONFIG_PATH`:

```python
    DOCUMENT_STORAGE_ROOT: str = str(_PROJECT_ROOT / "storage" / "documents")
```

and add after the `enrichment_config_path` property:

```python
    @property
    def document_storage_root(self) -> str:
        return self.DOCUMENT_STORAGE_ROOT
```

- [x] **Step 4: Implement `LocalDiskStorage`**

```python
# src/classiflow/storage/document_storage.py
import asyncio
import shutil
from pathlib import Path
from typing import Protocol

from classiflow.settings import Settings


class IDocumentStorage(Protocol):
    async def save_staged(self, job_id: str, filename: str, file_bytes: bytes) -> str: ...
    async def move_to_final(self, job_id: str, filename: str, subdirectory: str) -> str: ...


class LocalDiskStorage:
    def __init__(self, root: str | None = None) -> None:
        self._root = Path(root if root is not None else Settings.document_storage_root)

    async def save_staged(self, job_id: str, filename: str, file_bytes: bytes) -> str:
        return await asyncio.to_thread(self._save_staged_sync, job_id, filename, file_bytes)

    def _save_staged_sync(self, job_id: str, filename: str, file_bytes: bytes) -> str:
        staged_path = self._root / "staging" / f"{job_id}_{filename}"
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_bytes(file_bytes)
        return str(staged_path)

    async def move_to_final(self, job_id: str, filename: str, subdirectory: str) -> str:
        return await asyncio.to_thread(self._move_to_final_sync, job_id, filename, subdirectory)

    def _move_to_final_sync(self, job_id: str, filename: str, subdirectory: str) -> str:
        # Locates the file wherever it currently sits (glob, not a fixed "staging/"
        # path) rather than assuming it's always still staged. A job routed to
        # human_review legitimately gets moved TWICE: staging/ -> review/human_review/
        # (Routing's automatic run), then review/human_review/ -> classified/<label>/
        # (the human-decision endpoint calling Routing a second time, spec Decision 9).
        # There is always exactly one physical copy on disk (moved, never copied), so
        # the glob is unambiguous. A job that's already reached its real terminal state
        # (classified/<label>/) being routed *again* is the actual bug case Decision 1
        # warns about -- that still surfaces as shutil.move raising on a
        # source==destination no-op collision rather than being silently swallowed.
        target_name = f"{job_id}_{filename}"
        matches = list(self._root.glob(f"**/{target_name}"))
        if not matches:
            msg = f"No staged or previously-routed file found for job {job_id} ({filename})"
            raise FileNotFoundError(msg)
        source_path = matches[0]
        final_path = self._root / subdirectory / target_name
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(final_path))
        return str(final_path)
```

```python
# src/classiflow/storage/__init__.py
from classiflow.storage.document_storage import IDocumentStorage, LocalDiskStorage

__all__ = ["IDocumentStorage", "LocalDiskStorage"]
```

- [x] **Step 5: Add `.gitignore` entry**

In `.gitignore`, add after the `models/**` / `!models/**/.gitkeep` block (before the "Un-ignore the main dev database" section):

```
# ---- Local document storage root (staged uploads, classified/review-queue files) ----
storage/documents/**
```

- [x] **Step 6: Run test to verify it passes**

Run: `pytest tests/storage/test_document_storage.py -v`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add src/classiflow/storage/ src/classiflow/settings.py .gitignore tests/storage/
git commit -m "feat: add IDocumentStorage protocol and LocalDiskStorage implementation"
```

---

## Task 2: Stage 1 change — persist bytes to staging inside `PipelineService._run()`

Wires `IDocumentStorage` (Task 1) into `PipelineService`, adds the one `save_staged` call from spec Decision 2, and changes `_run_enrichment` to return the saved `EnrichedRecord` (or `None`) so Task 16 can chain `_run_classification` off it without another signature change later.

**Files:**
- Modify: `src/classiflow/services/pipeline/service.py`
- Modify: `src/classiflow/injections/production.py`
- Modify: `src/classiflow/injections/test.py`
- Modify: `src/classiflow/api/dependencies.py`
- Modify: `tests/shared/test_pipeline_service_enrichment.py`
- Modify: `tests/ingesta/test_extraction_concurrency.py`

**Interfaces:**
- Consumes: `classiflow.storage.document_storage.{IDocumentStorage, LocalDiskStorage}` (Task 1).
- Produces: `PipelineService.__init__(job_repo, document_steps_repo, enriched_record_repo, broadcaster, coordinator, enrichment_coordinator, document_storage)`. `PipelineService._run_enrichment(job_id, filename, final_state) -> EnrichedRecord | None` (was implicitly `-> None`). `Container.document_storage` (production), `TestContainer.document_storage` (test).

- [x] **Step 1: Extend the failing test — staging assertion + fixture plumbing**

In `tests/shared/test_pipeline_service_enrichment.py`, add to the imports:

```python
from pathlib import Path
from typing import cast

from langgraph.graph.state import CompiledStateGraph

from classiflow.storage.document_storage import LocalDiskStorage
```

Change `_build_service`'s signature to accept `tmp_path` and pass a `LocalDiskStorage` rooted there into the `PipelineService(...)` call (only the signature's second parameter, and the added `document_storage=` kwarg, are new — every other line is unchanged from the current file):

```python
def _build_service(entity_response: str, tmp_path: Path) -> _ServiceUnderTest:
    audit = AuditService(InMemoryAuditRepository())
    broadcaster = EventBroadcaster()

    n1 = FileReceptionNode(
        audit=audit, broadcaster=broadcaster, mime_detector=lambda _b: "application/pdf"
    )
    n2 = FormatValidationNode(audit=audit, broadcaster=broadcaster)
    extraction_step = ExtractionStep(
        audit=audit,
        broadcaster=broadcaster,
        text_extractor=lambda *_: ExtractionResult(
            text=_SPANISH_TEXT, extractor_used="test", char_count=len(_SPANISH_TEXT)
        ),
        semaphore=asyncio.Semaphore(10),
    )
    n3 = ContentValidationNode(
        audit=audit,
        broadcaster=broadcaster,
        language_detector=_MockDetector("es"),
        content_chain=build_content_chain(MockLlm(response=_SLM_LEGITIMATE)),
    )
    n4 = DuplicateControlNode(
        hash_repo=InMemoryHashRepository(),
        audit=audit,
        broadcaster=broadcaster,
        embedding_store=EmbeddingStore(dim=4, embed_fn=_stub_embed),
    )
    coordinator = build_coordinator(n1, n2, n3, n4, extraction_step=extraction_step)

    text_cleaner = TextCleanerNode(audit=audit, broadcaster=broadcaster)
    entity_extractor = EntityExtractorNode(
        audit=audit,
        broadcaster=broadcaster,
        entity_chain=build_entity_extraction_chain(MockLlm(response=entity_response)),
    )
    metadata_enricher = MetadataEnricherNode(audit=audit, broadcaster=broadcaster)
    enrichment_coordinator = build_enrichment_coordinator(
        text_cleaner, entity_extractor, metadata_enricher
    )

    job_repo = InMemoryJobRepository()
    enriched_record_repo = InMemoryEnrichedRecordRepository()
    service = PipelineService(
        job_repo=job_repo,
        document_steps_repo=InMemoryDocumentStepsRepository(),
        enriched_record_repo=enriched_record_repo,
        broadcaster=broadcaster,
        coordinator=coordinator,
        enrichment_coordinator=enrichment_coordinator,
        document_storage=LocalDiskStorage(root=str(tmp_path)),
    )
    return _ServiceUnderTest(
        service=service, job_repo=job_repo, enriched_record_repo=enriched_record_repo
    )
```

Update both existing test methods to accept and forward `tmp_path` (only the method signature and the `_build_service(...)` call's second argument change; the rest of each test body is unchanged):

```python
class TestPipelineServiceEnrichmentHappyPath:
    async def test_accepted_job_gets_enriched_record(self, tmp_path: Path) -> None:
        under_test = _build_service(_VALID_ENTITY_RESPONSE, tmp_path)
        background_tasks = BackgroundTasks()
        job_id = await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        job = await under_test.job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status == "accepted"

        record = await under_test.enriched_record_repo.find_by_job_id(job_id)
        assert record is not None
        assert "Artículo 1" in record.cleaned_text
        assert record.entities["doc_type_hint"] == "ordenanza"
        assert record.metadata_["source"] == "manual_upload"


class TestPipelineServiceEnrichmentFailurePath:
    async def test_enrichment_failure_marks_job_for_review(self, tmp_path: Path) -> None:
        under_test = _build_service("not json at all", tmp_path)
        background_tasks = BackgroundTasks()
        job_id = await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        job = await under_test.job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status == "review"
        assert job.review_action_needed == "enrichment_failed"
        assert job.failed_at_node == "enrichment"
        assert "Enrichment failed after retries" in (job.rejection_reason or "")

        record = await under_test.enriched_record_repo.find_by_job_id(job_id)
        assert record is None
```

Add a new test class proving Decision 2's staging behavior end-to-end:

```python
class TestPipelineServiceStaging:
    async def test_accepted_job_stages_file_bytes(self, tmp_path: Path) -> None:
        under_test = _build_service(_VALID_ENTITY_RESPONSE, tmp_path)
        background_tasks = BackgroundTasks()
        job_id = await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        staged_path = tmp_path / "staging" / f"{job_id}_ordenanza.pdf"
        assert staged_path.exists()
        assert staged_path.read_bytes() == _MINIMAL_PDF

    async def test_job_rejected_before_extraction_is_never_staged(self, tmp_path: Path) -> None:
        # A fake coordinator standing in for "node2 rejected the file before extraction"
        # -- final_state has no "extraction" key, the exact condition _run() gates
        # save_staged on. Isolates this test from the real 4-node coordinator's own
        # content-sniffing internals (not this test's concern).
        class _RejectsBeforeExtractionCoordinator:
            async def ainvoke(self, state: dict[str, object]) -> dict[str, object]:
                return {
                    "job_id": state["job_id"],
                    "filename": state["filename"],
                    "final_status": "rejected",
                    "rejection_reason": "bad format",
                }

        under_test = _build_service(_VALID_ENTITY_RESPONSE, tmp_path)
        under_test.service._coordinator = cast(  # noqa: SLF001
            "CompiledStateGraph", _RejectsBeforeExtractionCoordinator()
        )
        background_tasks = BackgroundTasks()
        job_id = await under_test.service.start(background_tasks, "bad.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        job = await under_test.job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status == "rejected"
        assert not (tmp_path / "staging" / f"{job_id}_bad.pdf").exists()
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/shared/test_pipeline_service_enrichment.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'document_storage'`

- [x] **Step 3: Update `PipelineService`**

In `src/classiflow/services/pipeline/service.py`, add to imports:

```python
from classiflow.storage.document_storage import IDocumentStorage
```

Update `__init__`:

```python
class PipelineService:
    def __init__(
        self,
        job_repo: IJobRepository,
        document_steps_repo: IDocumentStepsRepository,
        enriched_record_repo: IEnrichedRecordRepository,
        broadcaster: EventBroadcaster,
        coordinator: CompiledStateGraph,  # type: ignore[type-arg]
        enrichment_coordinator: CompiledStateGraph,  # type: ignore[type-arg]
        document_storage: IDocumentStorage,
    ) -> None:
        self._job_repo = job_repo
        self._document_steps_repo = document_steps_repo
        self._enriched_record_repo = enriched_record_repo
        self._broadcaster = broadcaster
        self._coordinator = coordinator
        self._enrichment_coordinator = enrichment_coordinator
        self._document_storage = document_storage
```

Update `_run` to stage the bytes right after `_finalize_job`, before the enrichment trigger:

```python
    async def _run(self, job_id: str, filename: str, file_bytes: bytes) -> None:
        initial: JobState = {"job_id": job_id, "filename": filename, "file_bytes": file_bytes}
        final_state = cast("JobState", await self._coordinator.ainvoke(initial))

        failed_at_node = await self._persist_steps(job_id, final_state)
        await self._finalize_job(job_id, final_state, failed_at_node)

        if final_state.get("extraction") is not None:
            await self._document_storage.save_staged(job_id, filename, file_bytes)

        if final_state.get("final_status") == "accepted":
            await self._run_enrichment(job_id, filename, final_state)

        unload_slm()

        await self._broadcaster.emit(
            NodeEvent(job_id=job_id, node=_PIPELINE_NODE, status=JobStatus.DONE)
        )
```

Change `_run_enrichment`'s return type — it now returns the saved `EnrichedRecord` on success, `None` after retries are exhausted. `_run()` itself does not capture the return value yet (Task 16 does):

```python
async def _run_enrichment(
    self, job_id: str, filename: str, final_state: JobState
) -> EnrichedRecord | None:
    reception = final_state["reception"]
    content_validation = final_state["content_validation"]
    extraction = final_state["extraction"]
    initial: EnrichmentState = {
        "job_id": job_id,
        "filename": filename,
        "text": final_state["text"],
        "language": content_validation.detected_language,
        "sha256": reception.sha256,
        "stage2_extractor_used": extraction.extractor_used,
    }
    max_retries = get_enrichment_config().max_enrichment_retries
    last_error: EnrichmentError | None = None
    for _attempt in range(max_retries + 1):
        try:
            result = cast("EnrichmentState", await self._enrichment_coordinator.ainvoke(initial))
            record = EnrichedRecord(
                job_id=job_id,
                cleaned_text=result["cleaned_text"],
                entities=result["entities"].model_dump(),
                metadata_=result["metadata"].model_dump(),
            )
            await self._enriched_record_repo.save(record)
        except EnrichmentError as exc:
            last_error = exc
            continue
        return record
    await self._job_repo.update_status(
        job_id,
        "review",
        rejection_reason=f"Enrichment failed after retries: {last_error}",
        review_action_needed="enrichment_failed",
        failed_at_node="enrichment",
    )
    return None
```

- [x] **Step 4: Wire `document_storage` into `Container` (production.py)**

In `src/classiflow/injections/production.py`, add import:

```python
from classiflow.storage.document_storage import LocalDiskStorage
```

Add inside `Container`, after `broadcaster`:

```python
    # Singleton: stateless (root path is fixed at construction), no per-request teardown
    # needed -- same reasoning as broadcaster above.
    document_storage = providers.Singleton(LocalDiskStorage)
```

- [x] **Step 5: Wire `document_storage` into `TestContainer` (injections/test.py)**

Add imports:

```python
import tempfile

from classiflow.storage.document_storage import LocalDiskStorage
```

Add near the top of the module, alongside the other test constants:

```python
# ponytail: reuse the real LocalDiskStorage against a throwaway temp directory instead
# of inventing a fake in-memory storage class -- one less code path to diverge from
# production, and TestContainer is module-scoped so a pytest tmp_path fixture isn't
# available here.
_TEST_STORAGE_ROOT = tempfile.mkdtemp(prefix="classiflow-test-storage-")
```

Add a provider inside `TestContainer`, after `enriched_record_repo`:

```python
    document_storage = providers.Singleton(LocalDiskStorage, root=_TEST_STORAGE_ROOT)
```

Update `pipeline_service`:

```python
    pipeline_service = providers.Factory(
        PipelineService,
        job_repo=job_repo,
        document_steps_repo=document_steps_repo,
        enriched_record_repo=enriched_record_repo,
        broadcaster=broadcaster,
        coordinator=coordinator,
        enrichment_coordinator=enrichment_coordinator,
        document_storage=document_storage,
    )
```

- [x] **Step 6: Wire `document_storage` into `api/dependencies.py`'s `get_pipeline_service`**

Add import:

```python
from classiflow.storage.document_storage import IDocumentStorage
```

Update `get_pipeline_service`:

```python
@inject
def get_pipeline_service(
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    document_steps_repo: Annotated[IDocumentStepsRepository, Depends(get_document_steps_repo)],
    enriched_record_repo: Annotated[IEnrichedRecordRepository, Depends(get_enriched_record_repo)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    coordinator: Annotated[CompiledStateGraph, Depends(get_coordinator)],  # type: ignore[type-arg]
    enrichment_coordinator: Annotated[  # type: ignore[type-arg]
        CompiledStateGraph, Depends(get_enrichment_coordinator)
    ],
    document_storage: Annotated[IDocumentStorage, Depends(Provide[Container.document_storage])],
) -> PipelineService:
    return PipelineService(
        job_repo=job_repo,
        document_steps_repo=document_steps_repo,
        enriched_record_repo=enriched_record_repo,
        broadcaster=broadcaster,
        coordinator=coordinator,
        enrichment_coordinator=enrichment_coordinator,
        document_storage=document_storage,
    )
```

- [x] **Step 7: Fix the other direct `PipelineService(...)` construction site**

In `tests/ingesta/test_extraction_concurrency.py`, add `IDocumentStorage` to the existing `TYPE_CHECKING` block:

```python
if TYPE_CHECKING:
    from classiflow.database.models import DocumentStep
    from classiflow.ingesta.domain import JobState
    from classiflow.storage.document_storage import IDocumentStorage
```

Update the `PipelineService(...)` construction (this test only exercises `_persist_steps`, never `_run()`, so the new param is genuinely unused — same pattern already used for `coordinator`/`enrichment_coordinator` here):

```python
    service = PipelineService(
        job_repo=InMemoryJobRepository(),
        document_steps_repo=document_steps_repo,
        enriched_record_repo=InMemoryEnrichedRecordRepository(),  # unused: only _persist_steps runs
        broadcaster=EventBroadcaster(),
        coordinator=cast("CompiledStateGraph", None),  # unused: only _persist_steps runs
        enrichment_coordinator=cast("CompiledStateGraph", None),  # unused: only _persist_steps runs
        document_storage=cast("IDocumentStorage", None),  # unused: only _persist_steps runs
    )
```

- [x] **Step 8: Run test to verify it passes**

Run: `pytest tests/shared/test_pipeline_service_enrichment.py tests/ingesta/test_extraction_concurrency.py -v`
Expected: PASS

- [x] **Step 9: Run the full existing test suite (regression check)**

Run: `pytest tests -v`
Expected: PASS across the board — `tests/api` picks up the new `Container.document_storage`/`TestContainer.document_storage` wiring automatically through `get_pipeline_service`.

- [x] **Step 10: Commit**

```bash
git add src/classiflow/services/pipeline/service.py src/classiflow/injections/production.py src/classiflow/injections/test.py src/classiflow/api/dependencies.py tests/shared/test_pipeline_service_enrichment.py tests/ingesta/test_extraction_concurrency.py
git commit -m "feat: stage uploaded file bytes to disk after successful extraction"
```

---

## Task 3: `ClassificationRecord` DB model, migration, and repository

Adds the BERT spec's original field list plus this spec's three additions (`judged_by_llm`, `stored_path`, `human_overridden`). `enriched_id`/`id` are `Integer`/`autoincrement=True`, matching this project's convention (corrected from the BERT spec's original UUID sketch, same correction already applied to `EnrichedRecord`). `0005` is the next migration — `0004_add_enriched_records.py` is the current head.

**Files:**
- Modify: `src/classiflow/database/models.py`
- Create: `alembic/versions/0005_add_classification_records.py`
- Create: `src/classiflow/domain/repositories/classification_record.py`
- Modify: `src/classiflow/domain/repositories/__init__.py`
- Create: `src/classiflow/database/repositories/classification_record.py`
- Modify: `tests/shared/test_repositories.py`

**Interfaces:**
- Produces: `classiflow.database.models.ClassificationRecord` (`id: int` PK autoincrement, `job_id: str` FK→`jobs.job_id`, `enriched_id: int` FK→`enriched_records.id`, `label: str | None`, `confidence: float`, `all_scores: dict[str, object]`, `second_opinion_label: str | None`, `second_opinion_confidence: float`, `classifier_disagreement: bool`, `ood_metrics: dict[str, object] | None`, `svm_scores: dict[str, object]`, `svm_agrees_with_prediction: bool`, `review_route: str`, `smells: list[str]`, `risk_score: int`, `smell_review_suggested: bool`, `foreign_municipality: str | None`, `judged_by_llm: bool`, `stored_path: str | None`, `human_overridden: bool`, `created_at: datetime`). `classiflow.domain.repositories.classification_record.IClassificationRecordRepository` (Protocol: `save(record) -> None`, `find_by_job_id(job_id) -> ClassificationRecord | None`, `list_needing_human_review() -> list[ClassificationRecord]`). `SqlClassificationRecordRepository`, `InMemoryClassificationRecordRepository`.
- Consumes: `classiflow.database.base.Base`, `classiflow.database.models.EnrichedRecord` (Task existing), `Job`.

- [x] **Step 1: Write the failing test**

Append to `tests/shared/test_repositories.py` (add `ClassificationRecord` to the existing `classiflow.database.models` import, and `InMemoryClassificationRecordRepository`/`SqlClassificationRecordRepository` to a new import line):

```python
from classiflow.database.repositories.classification_record import (
    InMemoryClassificationRecordRepository,
    SqlClassificationRecordRepository,
)
```

```python
def _classification_record(
    job_id: str = _JOB, review_route: str = "accept"
) -> ClassificationRecord:
    return ClassificationRecord(
        job_id=job_id,
        enriched_id=1,
        label="ordenanzas",
        confidence=0.91,
        all_scores={"ordenanzas": 0.91, "decretos": 0.05},
        second_opinion_label="ordenanza",
        second_opinion_confidence=0.88,
        classifier_disagreement=False,
        ood_metrics=None,
        svm_scores={"ordenanzas": 0.7},
        svm_agrees_with_prediction=True,
        review_route=review_route,
        smells=[],
        risk_score=0,
        smell_review_suggested=False,
        foreign_municipality=None,
        judged_by_llm=False,
        stored_path=None,
        human_overridden=False,
    )


class TestSqlClassificationRecordRepository:
    async def test_save_and_find(self, session: AsyncSession) -> None:
        repo = SqlClassificationRecordRepository(session)
        await repo.save(_classification_record())
        record = await repo.find_by_job_id(_JOB)
        assert record is not None
        assert record.label == "ordenanzas"
        assert record.all_scores == {"ordenanzas": 0.91, "decretos": 0.05}
        assert record.judged_by_llm is False
        assert record.human_overridden is False

    async def test_find_missing_returns_none(self, session: AsyncSession) -> None:
        repo = SqlClassificationRecordRepository(session)
        assert await repo.find_by_job_id("no-such-job") is None

    async def test_list_needing_human_review_filters_by_route(self, session: AsyncSession) -> None:
        repo = SqlClassificationRecordRepository(session)
        await repo.save(_classification_record(job_id=_JOB, review_route="human_review"))
        pending = await repo.list_needing_human_review()
        assert [r.job_id for r in pending] == [_JOB]

    async def test_list_needing_human_review_excludes_accepted(self, session: AsyncSession) -> None:
        repo = SqlClassificationRecordRepository(session)
        await repo.save(_classification_record(job_id=_JOB, review_route="accept"))
        assert await repo.list_needing_human_review() == []


class TestInMemoryClassificationRecordRepository:
    async def test_save_and_find(self) -> None:
        repo = InMemoryClassificationRecordRepository()
        await repo.save(_classification_record())
        record = await repo.find_by_job_id(_JOB)
        assert record is not None
        assert record.label == "ordenanzas"

    async def test_find_missing_returns_none(self) -> None:
        repo = InMemoryClassificationRecordRepository()
        assert await repo.find_by_job_id("no-such-job") is None

    async def test_list_needing_human_review_filters_by_route(self) -> None:
        repo = InMemoryClassificationRecordRepository()
        await repo.save(_classification_record(job_id=_JOB, review_route="human_review"))
        await repo.save(_classification_record(job_id="job-002", review_route="accept"))
        pending = await repo.list_needing_human_review()
        assert [r.job_id for r in pending] == [_JOB]
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/shared/test_repositories.py -k ClassificationRecord -v`
Expected: FAIL with `ImportError` (nothing exists yet)

- [x] **Step 3: Add `ClassificationRecord` to `database/models.py`**

Add `Float` to the existing `sqlalchemy` import line, then append the class after `EnrichedRecord`:

```python
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
```

```python
class ClassificationRecord(Base):
    __tablename__ = "classification_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True
    )
    enriched_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("enriched_records.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    all_scores: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    second_opinion_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    second_opinion_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    classifier_disagreement: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ood_metrics: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    svm_scores: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    svm_agrees_with_prediction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_route: Mapped[str] = mapped_column(String(20), nullable=False)
    smells: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    smell_review_suggested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    foreign_municipality: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Whether the LLM Judge tier ran and produced the final review_route (spec Decision 6).
    judged_by_llm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Set by RoutingNode once the file has been moved to its final location (Decision 8).
    stored_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Set by the human-decision endpoint (Decision 9).
    human_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
```

- [x] **Step 4: Write the Alembic migration**

```python
# alembic/versions/0005_add_classification_records.py
"""Add classification_records table

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-18

"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classification_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "enriched_id",
            sa.Integer,
            sa.ForeignKey("enriched_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("all_scores", sa.JSON, nullable=False),
        sa.Column("second_opinion_label", sa.String(100), nullable=True),
        sa.Column("second_opinion_confidence", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("classifier_disagreement", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("ood_metrics", sa.JSON, nullable=True),
        sa.Column("svm_scores", sa.JSON, nullable=False),
        sa.Column(
            "svm_agrees_with_prediction", sa.Boolean, nullable=False, server_default=sa.true()
        ),
        sa.Column("review_route", sa.String(20), nullable=False),
        sa.Column("smells", sa.JSON, nullable=False),
        sa.Column("risk_score", sa.Integer, nullable=False, server_default="0"),
        sa.Column("smell_review_suggested", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("foreign_municipality", sa.String(255), nullable=True),
        sa.Column("judged_by_llm", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("stored_path", sa.String(500), nullable=True),
        sa.Column("human_overridden", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_classification_records_job_id", "classification_records", ["job_id"])


def downgrade() -> None:
    op.drop_table("classification_records")
```

- [x] **Step 5: Write the repository Protocol**

```python
# src/classiflow/domain/repositories/classification_record.py
from typing import Protocol

from classiflow.database.models import ClassificationRecord


class IClassificationRecordRepository(Protocol):
    async def save(self, record: ClassificationRecord) -> None: ...
    async def find_by_job_id(self, job_id: str) -> ClassificationRecord | None: ...
    async def list_needing_human_review(self) -> list[ClassificationRecord]: ...
```

Update `src/classiflow/domain/repositories/__init__.py`:

```python
from classiflow.domain.repositories.classification_record import IClassificationRecordRepository
from classiflow.domain.repositories.document_steps import IDocumentStepsRepository
from classiflow.domain.repositories.enriched_record import IEnrichedRecordRepository
from classiflow.domain.repositories.human_decision import IHumanDecisionRepository
from classiflow.domain.repositories.job import UNSET, IJobRepository, UnsetType
from classiflow.domain.repositories.user import IUserRepository

__all__ = [
    "UNSET",
    "IClassificationRecordRepository",
    "IDocumentStepsRepository",
    "IEnrichedRecordRepository",
    "IHumanDecisionRepository",
    "IJobRepository",
    "IUserRepository",
    "UnsetType",
]
```

- [x] **Step 6: Write the Sql/InMemory implementations**

```python
# src/classiflow/database/repositories/classification_record.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.database.models import ClassificationRecord

_HUMAN_REVIEW_ROUTE = "human_review"


class SqlClassificationRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: ClassificationRecord) -> None:
        self._session.add(record)
        await self._session.flush()

    async def find_by_job_id(self, job_id: str) -> ClassificationRecord | None:
        result = await self._session.execute(
            select(ClassificationRecord).where(ClassificationRecord.job_id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_needing_human_review(self) -> list[ClassificationRecord]:
        result = await self._session.execute(
            select(ClassificationRecord).where(
                ClassificationRecord.review_route == _HUMAN_REVIEW_ROUTE
            )
        )
        return list(result.scalars().all())


class InMemoryClassificationRecordRepository:
    def __init__(self) -> None:
        self._records: dict[str, ClassificationRecord] = {}

    async def save(self, record: ClassificationRecord) -> None:
        self._records[record.job_id] = record

    async def find_by_job_id(self, job_id: str) -> ClassificationRecord | None:
        return self._records.get(job_id)

    async def list_needing_human_review(self) -> list[ClassificationRecord]:
        return [r for r in self._records.values() if r.review_route == _HUMAN_REVIEW_ROUTE]
```

- [x] **Step 7: Apply the migration to the local dev DB**

Hand to the user (per this project's convention — do not run yourself): `uv run alembic upgrade head`

- [x] **Step 8: Run test to verify it passes**

Run: `pytest tests/shared/test_repositories.py -k ClassificationRecord -v`
Expected: PASS

- [x] **Step 9: Commit**

```bash
git add src/classiflow/database/models.py alembic/versions/0005_add_classification_records.py src/classiflow/domain/repositories/classification_record.py src/classiflow/domain/repositories/__init__.py src/classiflow/database/repositories/classification_record.py tests/shared/test_repositories.py
git commit -m "feat: add ClassificationRecord model, migration, and repository"
```

---

## Task 4: `classification/` package skeleton — config, exceptions, domain models

New top-level `classiflow/classification/` package (sibling to `enrichment/`, not inside `ingesta/`). `config/classification.yaml` and `ClassificationConfig`'s fields are exactly the BERT spec's (unchanged by this spec); `CLASSIFICATION_MODEL_PATH`/`JUDGE_MODEL_PATH` (the primary-classifier and LLM-judge GGUF paths) go in `Settings`, not the YAML, per this spec's "Config additions" section — distinct from `bert_model_path`, which stays in the YAML per the BERT spec (it points at the ported BETO artifact directory, not a chat-model GGUF).

**Files:**
- Create: `config/classification.yaml`
- Create: `src/classiflow/classification/__init__.py`
- Create: `src/classiflow/classification/config_classification.py`
- Create: `src/classiflow/classification/exceptions.py`
- Create: `src/classiflow/classification/domain/__init__.py`
- Create: `src/classiflow/classification/domain/results.py`
- Create: `src/classiflow/classification/domain/state.py`
- Modify: `src/classiflow/settings.py`
- Create: `tests/classification/__init__.py`
- Create: `tests/classification/test_config_classification.py`
- Create: `tests/classification/test_domain.py`

**Interfaces:**
- Consumes: `classiflow.config_loader.load_yaml_config`, `classiflow.domain.base.BaseEntity`.
- Produces: `ClassificationConfig` (fields: `confidence_threshold: float = 0.75`, `smell_review_risk_threshold: int = 4`, `max_input_tokens: int = 512`, `second_opinion_enabled: bool = True`, `foreign_municipality_enabled: bool = True`, `bert_model_path: str = "models/bert_tunning_beto_v2"`, `ood_mahalanobis_p_threshold: float = 0.001`, `ood_cosine_threshold: float = 13.7366`, `ood_knn_distance_threshold: float = 26.125`, `ood_tfidf_cosine_threshold: float = 2.5`, `ood_pca_components: int = 64`, `ood_trained_municipality: str = "rosario"`), `get_classification_config() -> ClassificationConfig` (`@lru_cache(maxsize=1)`). `Settings.classification_model_path`, `Settings.classification_config_path`, `Settings.judge_model_path`. `ClassificationError(Exception)` base, `ClassificationRecordNotFoundError(job_id: str)`, `ClassificationNotInReviewError(job_id: str, review_route: str)`. `PrimaryClassificationOutput(BaseEntity)`, `JudgeOutput(BaseEntity)`, `RoutingResult(BaseEntity)` (`domain/results.py`). `ClassificationState` (`TypedDict`, required: `job_id`, `filename`, `cleaned_text`, `enriched_id` — the last needed by Routing, Task 14, to build `RoutingInput`/`ClassificationRecord`; optional fields accumulate as each node runs), `ClassificationUpdate(BaseEntity)` (`domain/state.py`).

- [x] **Step 1: Write the failing test**

```python
# tests/classification/test_config_classification.py
from classiflow.classification.config_classification import (
    ClassificationConfig,
    get_classification_config,
)


class TestClassificationConfig:
    def test_defaults(self) -> None:
        config = ClassificationConfig()
        assert config.confidence_threshold == 0.75
        assert config.smell_review_risk_threshold == 4
        assert config.max_input_tokens == 512
        assert config.second_opinion_enabled is True
        assert config.foreign_municipality_enabled is True
        assert config.bert_model_path == "models/bert_tunning_beto_v2"

    def test_get_classification_config_loads_real_yaml(self) -> None:
        config = get_classification_config()
        assert isinstance(config, ClassificationConfig)
        assert config.confidence_threshold > 0
        assert config.smell_review_risk_threshold >= 0
```

```python
# tests/classification/test_domain.py
import pytest

from classiflow.classification.domain.results import (
    JudgeOutput,
    PrimaryClassificationOutput,
    RoutingResult,
)
from classiflow.classification.domain.state import ClassificationUpdate
from classiflow.classification.exceptions import (
    ClassificationNotInReviewError,
    ClassificationRecordNotFoundError,
)


class TestResultDefaults:
    def test_primary_classification_output_defaults(self) -> None:
        result = PrimaryClassificationOutput(label="ordenanzas", confidence=0.9)
        assert result.all_scores == {}

    def test_judge_output_defaults(self) -> None:
        result = JudgeOutput(accept=True)
        assert result.reasoning == ""

    def test_routing_result_requires_stored_path(self) -> None:
        result = RoutingResult(stored_path="/tmp/classified/ordenanzas/job-1_doc.pdf")
        assert result.stored_path == "/tmp/classified/ordenanzas/job-1_doc.pdf"


class TestClassificationUpdate:
    def test_dump_excludes_none_fields(self) -> None:
        update = ClassificationUpdate(label="ordenanzas", confidence=0.9)
        dumped = {k: v for k, v in update if v is not None}
        assert dumped == {"label": "ordenanzas", "confidence": 0.9}


class TestClassificationRecordNotFoundError:
    def test_message(self) -> None:
        exc = ClassificationRecordNotFoundError(job_id="job-1")
        assert str(exc) == "Classification record for job job-1 not found"

    def test_raises_with_context(self) -> None:
        with pytest.raises(ClassificationRecordNotFoundError, match="job-1"):
            raise ClassificationRecordNotFoundError(job_id="job-1")


class TestClassificationNotInReviewError:
    def test_message(self) -> None:
        exc = ClassificationNotInReviewError(job_id="job-1", review_route="accept")
        assert str(exc) == (
            "Classification for job job-1 is not awaiting human review (review_route=accept)"
        )
```

```python
# tests/classification/__init__.py
```
(empty — package marker, mirrors `tests/enrichment/__init__.py`)

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/classification -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.classification'`

- [x] **Step 3: Add Settings fields**

In `src/classiflow/settings.py`, add after `DOCUMENT_STORAGE_ROOT`:

```python
    CLASSIFICATION_MODEL_PATH: str = _DEFAULT_MODEL
    CLASSIFICATION_CONFIG_PATH: str = str(_PROJECT_ROOT / "config" / "classification.yaml")
    JUDGE_MODEL_PATH: str = _DEFAULT_MODEL
```

and add after the `document_storage_root` property:

```python
@property
def classification_model_path(self) -> str:
    return self.CLASSIFICATION_MODEL_PATH


@property
def classification_config_path(self) -> str:
    return self.CLASSIFICATION_CONFIG_PATH


@property
def judge_model_path(self) -> str:
    return self.JUDGE_MODEL_PATH
```

- [x] **Step 4: Create `config/classification.yaml`**

```yaml
# Stage 4 (Classification & Routing) thresholds. Per the BERT spec
# (docs/superpowers/specs/2026-08-17-bert-tunning-classification-integration-design.md)
# -- this file is unchanged by the Stage 4 routing spec.

confidence_threshold: 0.75
smell_review_risk_threshold: 4
max_input_tokens: 512
second_opinion_enabled: true
foreign_municipality_enabled: true

bert_model_path: models/bert_tunning_beto_v2   # relative to project root

# Fallback OOD thresholds, only used if a model's own ood_stats.npz isn't calibrated
# (mirrors bert_tunning's own uncalibrated-fallback design). BETO v2 ships pre-calibrated,
# so these are a safety net for future retrained models, not what BETO v2 itself uses.
ood_mahalanobis_p_threshold: 0.001
ood_cosine_threshold: 13.7366
ood_knn_distance_threshold: 26.125
ood_tfidf_cosine_threshold: 2.5
ood_pca_components: 64
ood_trained_municipality: rosario
```

- [x] **Step 5: Implement `config_classification.py`**

```python
# src/classiflow/classification/config_classification.py
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from classiflow.config_loader import load_yaml_config
from classiflow.settings import Settings


class ClassificationConfig(BaseModel):
    confidence_threshold: float = 0.75
    smell_review_risk_threshold: int = 4
    max_input_tokens: int = 512
    second_opinion_enabled: bool = True
    foreign_municipality_enabled: bool = True
    bert_model_path: str = "models/bert_tunning_beto_v2"
    ood_mahalanobis_p_threshold: float = 0.001
    ood_cosine_threshold: float = 13.7366
    ood_knn_distance_threshold: float = 26.125
    ood_tfidf_cosine_threshold: float = 2.5
    ood_pca_components: int = 64
    ood_trained_municipality: str = "rosario"


@lru_cache(maxsize=1)
def get_classification_config() -> ClassificationConfig:
    return load_yaml_config(Path(Settings.classification_config_path), ClassificationConfig)
```

- [x] **Step 6: Implement `exceptions.py`**

```python
# src/classiflow/classification/exceptions.py
from dataclasses import dataclass


class ClassificationError(Exception): ...


@dataclass
class ClassificationRecordNotFoundError(ClassificationError):
    job_id: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Classification record for job {self.job_id} not found"


@dataclass
class ClassificationNotInReviewError(ClassificationError):
    job_id: str
    review_route: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"Classification for job {self.job_id} is not awaiting human review "
            f"(review_route={self.review_route})"
        )
```

- [x] **Step 7: Implement `domain/results.py`**

```python
# src/classiflow/classification/domain/results.py
from pydantic import Field

from classiflow.domain.base import BaseEntity


class PrimaryClassificationOutput(BaseEntity):
    label: str
    confidence: float
    all_scores: dict[str, float] = Field(default_factory=dict)


class JudgeOutput(BaseEntity):
    accept: bool
    reasoning: str = ""


class RoutingResult(BaseEntity):
    stored_path: str
```

- [x] **Step 8: Implement `domain/state.py`**

```python
# src/classiflow/classification/domain/state.py
from typing import TypedDict

from classiflow.domain.base import BaseEntity


class _ClassificationStateRequired(TypedDict):
    job_id: str
    filename: str
    cleaned_text: str
    enriched_id: int


class ClassificationState(_ClassificationStateRequired, total=False):
    label: str
    confidence: float
    all_scores: dict[str, float]
    second_opinion_label: str | None
    second_opinion_confidence: float
    classifier_disagreement: bool
    ood_metrics: dict[str, object] | None
    svm_scores: dict[str, float]
    svm_agrees_with_prediction: bool
    foreign_municipality: str | None
    smells: list[str]
    risk_score: int
    smell_review_suggested: bool
    review_route: str
    judged_by_llm: bool
    stored_path: str


class ClassificationUpdate(BaseEntity):
    """Typed construction for a classification coordinator node's partial
    ClassificationState update — mirrors enrichment/domain/state.py's EnrichmentUpdate."""

    label: str | None = None
    confidence: float | None = None
    all_scores: dict[str, float] | None = None
    second_opinion_label: str | None = None
    second_opinion_confidence: float | None = None
    classifier_disagreement: bool | None = None
    ood_metrics: dict[str, object] | None = None
    svm_scores: dict[str, float] | None = None
    svm_agrees_with_prediction: bool | None = None
    foreign_municipality: str | None = None
    smells: list[str] | None = None
    risk_score: int | None = None
    smell_review_suggested: bool | None = None
    review_route: str | None = None
    judged_by_llm: bool | None = None
    stored_path: str | None = None
```

- [x] **Step 9: Implement package `__init__.py` files**

```python
# src/classiflow/classification/domain/__init__.py
from .results import JudgeOutput, PrimaryClassificationOutput, RoutingResult
from .state import ClassificationState, ClassificationUpdate

__all__ = [
    "ClassificationState",
    "ClassificationUpdate",
    "JudgeOutput",
    "PrimaryClassificationOutput",
    "RoutingResult",
]
```

```python
# src/classiflow/classification/__init__.py
```
(empty for now — populated with re-exports as later tasks add symbols, mirrors `enrichment/__init__.py`'s Task 3 starting point)

- [x] **Step 10: Run test to verify it passes**

Run: `pytest tests/classification -v`
Expected: PASS

- [x] **Step 11: Commit**

```bash
git add config/classification.yaml src/classiflow/classification/ src/classiflow/settings.py tests/classification/
git commit -m "feat: add classification package skeleton — config, exceptions, domain models"
```

---

## Task 5: Primary Classification Agent — LLM chain + node

Same chain pattern as `enrichment/prompts/entity_extraction.py`. Unlike that file, `PrimaryClassificationOutput` (the chain's output type) is imported directly from `domain/results.py` (Task 4) rather than duplicated as a separate prompts-level class — its fields (`label`, `confidence`, `all_scores`) are already exactly what the chain produces, so a second near-identical class would be pure duplication. `all_scores` is populated as a single-point `{label: confidence}` map, not a full per-class distribution — see the `_extract` docstring comment below for why. Truncation to `config.max_input_tokens` happens in the node (`classify()`), not the prompt template, per spec Decision 4.

**Files:**
- Create: `src/classiflow/classification/prompts/__init__.py`
- Create: `src/classiflow/classification/prompts/primary_classification.py`
- Create: `src/classiflow/classification/nodes/__init__.py`
- Create: `src/classiflow/classification/nodes/primary_classifier.py`
- Modify: `src/classiflow/classification/exceptions.py`
- Create: `tests/classification/test_primary_classification_chain.py`
- Create: `tests/classification/test_primary_classifier.py`

**Interfaces:**
- Consumes: `classiflow.domain.base.BaseEntity`, `classiflow.classification.domain.results.PrimaryClassificationOutput` (Task 4), `classiflow.classification.config_classification.{ClassificationConfig, get_classification_config}` (Task 4), `classiflow.pipeline.base.BaseNode`, `classiflow.pipeline.context.JobContext` (existing), `classiflow.ingesta.llm_provider.{get_llm_langchain, MockLlm}`, `classiflow.ingesta.exceptions.LlmProviderError`, `Settings.classification_model_path` (Task 4).
- Produces: `PrimaryClassificationInput(BaseEntity, cleaned_text: str)`, `build_classification_chain(llm: BaseLLM) -> Runnable[PrimaryClassificationInput, PrimaryClassificationOutput]`. `classiflow.classification.exceptions.PrimaryClassificationFailedError(reason: str)`. `PrimaryClassifierNode(BaseNode)` — `__init__(audit, broadcaster, *, classification_chain=None, config=None)`, `async run(ctx, cleaned_text) -> PrimaryClassificationOutput` (raises `PrimaryClassificationFailedError` on chain failure), `classify(cleaned_text) -> PrimaryClassificationOutput` (sync, directly testable, truncates to `config.max_input_tokens` chars).

- [x] **Step 1: Write the failing tests**

```python
# tests/classification/test_primary_classification_chain.py
import pytest

from classiflow.classification.prompts.primary_classification import (
    PrimaryClassificationInput,
    build_classification_chain,
)
from classiflow.ingesta.llm_provider import MockLlm

_VALID_RESPONSE = '{"label": "ordenanzas", "confidence": 0.91, "reasoning": "mentions ARTÍCULO"}'
_MALFORMED_RESPONSE = "not json at all"


class TestBuildClassificationChain:
    def test_parses_valid_response(self) -> None:
        chain = build_classification_chain(MockLlm(response=_VALID_RESPONSE))
        output = chain.invoke(PrimaryClassificationInput(cleaned_text="Artículo 1º ..."))
        assert output.label == "ordenanzas"
        assert output.confidence == 0.91
        assert output.all_scores == {"ordenanzas": 0.91}

    def test_raises_value_error_on_malformed_response(self) -> None:
        chain = build_classification_chain(MockLlm(response=_MALFORMED_RESPONSE))
        with pytest.raises(ValueError, match="No valid JSON object"):
            chain.invoke(PrimaryClassificationInput(cleaned_text="Artículo 1º ..."))
```

```python
# tests/classification/test_primary_classifier.py
import pytest

from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.exceptions import PrimaryClassificationFailedError
from classiflow.classification.nodes.primary_classifier import PrimaryClassifierNode
from classiflow.classification.prompts.primary_classification import build_classification_chain
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-classify-001"
_VALID_RESPONSE = '{"label": "decretos", "confidence": 0.8, "reasoning": "..."}'


def _node(response: str) -> PrimaryClassifierNode:
    return PrimaryClassifierNode(
        audit=AuditService(InMemoryAuditRepository()),
        broadcaster=EventBroadcaster(),
        classification_chain=build_classification_chain(MockLlm(response=response)),
    )


class TestPrimaryClassifierClassify:
    def test_classify_returns_result_on_valid_response(self) -> None:
        result = _node(_VALID_RESPONSE).classify("Decreto 42 ...")
        assert result.label == "decretos"
        assert result.confidence == 0.8

    def test_classify_raises_domain_error_on_malformed_response(self) -> None:
        with pytest.raises(PrimaryClassificationFailedError, match="No valid JSON object"):
            _node("not json").classify("Decreto 42 ...")


class TestPrimaryClassifierRun:
    async def test_run_emits_started_then_passed(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = PrimaryClassifierNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            classification_chain=build_classification_chain(MockLlm(response=_VALID_RESPONSE)),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, "Decreto 42 ...")
        assert result.label == "decretos"
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"

    async def test_run_emits_failed_and_reraises_on_error(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = PrimaryClassifierNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            classification_chain=build_classification_chain(MockLlm(response="not json")),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        with pytest.raises(PrimaryClassificationFailedError):
            await node.run(ctx, "Decreto 42 ...")
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "failed"

    async def test_run_truncates_to_max_input_tokens(self) -> None:
        broadcaster = EventBroadcaster()
        node = PrimaryClassifierNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=broadcaster,
            classification_chain=build_classification_chain(MockLlm(response=_VALID_RESPONSE)),
            config=ClassificationConfig(max_input_tokens=5),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, "Decreto 42, largo texto que supera el límite")
        assert result.label == "decretos"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/classification/test_primary_classification_chain.py tests/classification/test_primary_classifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.classification.prompts'`

- [x] **Step 3: Add `PrimaryClassificationFailedError` to `exceptions.py`**

Append to `src/classiflow/classification/exceptions.py`:

```python
@dataclass
class PrimaryClassificationFailedError(ClassificationError):
    reason: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Primary classification failed: {self.reason}"
```

- [x] **Step 4: Implement the chain**

```python
# src/classiflow/classification/prompts/primary_classification.py
import contextlib
import json
import re

from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnableLambda

from classiflow.classification.domain.results import PrimaryClassificationOutput
from classiflow.domain.base import BaseEntity

# Classiflow's 10 municipal document categories (README.md). BETO v2 (the Second
# Opinion Agent, classification/bert/) was only ever trained on 8 of these -- the
# primary LLM classifier is the only signal that can pick "convenios" or
# "compendios_de_boletines" at all. See the BERT spec's Decision 5 label-normalization
# map for the full BETO-to-Classiflow correspondence.
_CATEGORIES = (
    "boletines",
    "compendios_de_boletines",
    "convenios",
    "declaraciones_concejo_municipal",
    "decreto_ordenanzas",
    "decretos",
    "decretos_concejo_municipal",
    "ordenanzas",
    "resoluciones",
    "resoluciones_concejo_municipal",
)
_CATEGORIES_BLOCK = "\n".join(f"- {c}" for c in _CATEGORIES)


class PrimaryClassificationInput(BaseEntity):
    cleaned_text: str  # truncated to config.max_input_tokens by the node before this is built


_TEMPLATE = """\
Task: classify this excerpt of an official municipal document of the \
Municipalidad de Rosario into exactly one of the following categories:
{categories}

Text: {cleaned_text}

Answer with a single JSON object and nothing else.

JSON:
{{"label": "one of the categories above, exactly as written", \
"confidence": "your confidence in this label, a float between 0 and 1", \
"reasoning": "one short sentence justifying the label"}}"""

# Matches a single non-nested JSON object -- same approach as
# enrichment/prompts/entity_extraction.py's _JSON_RE.
_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


class _RawPrimaryOutput(BaseEntity):
    label: str
    confidence: float = 0.0
    reasoning: str = ""


def _extract(text: str) -> PrimaryClassificationOutput:
    for m in _JSON_RE.finditer(text):
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            raw = _RawPrimaryOutput.model_validate(json.loads(m.group()))
            # ponytail: all_scores is a single-point {label: confidence} map, not a
            # real per-class softmax distribution -- llama.cpp's plain text-completion
            # API used by get_llm_langchain() doesn't expose per-token logprobs across
            # all 10 categories here, and asking the model to hallucinate a full 10-way
            # distribution in freeform JSON would be unverifiable noise, not signal.
            # Upgrade path: switch to a logprob-exposing completion call if a genuine
            # distribution is ever needed downstream.
            return PrimaryClassificationOutput(
                label=raw.label,
                confidence=raw.confidence,
                all_scores={raw.label: raw.confidence},
            )
    msg = f"No valid JSON object found in LLM output: {text!r}"
    raise ValueError(msg)


def _format_prompt(chain_input: PrimaryClassificationInput) -> str:
    return _TEMPLATE.format(categories=_CATEGORIES_BLOCK, cleaned_text=chain_input.cleaned_text)


def build_classification_chain(
    llm: BaseLLM,
) -> Runnable[PrimaryClassificationInput, PrimaryClassificationOutput]:
    return RunnableLambda(_format_prompt) | llm | StrOutputParser() | RunnableLambda(_extract)
```

```python
# src/classiflow/classification/prompts/__init__.py
from classiflow.classification.prompts.primary_classification import (
    PrimaryClassificationInput,
    build_classification_chain,
)

__all__ = ["PrimaryClassificationInput", "build_classification_chain"]
```

- [x] **Step 5: Implement the node**

```python
# src/classiflow/classification/nodes/primary_classifier.py
import asyncio
from typing import Protocol, cast, runtime_checkable

from classiflow.classification.config_classification import (
    ClassificationConfig,
    get_classification_config,
)
from classiflow.classification.domain.results import PrimaryClassificationOutput
from classiflow.classification.exceptions import PrimaryClassificationFailedError
from classiflow.classification.prompts.primary_classification import (
    PrimaryClassificationInput,
    build_classification_chain,
)
from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.exceptions import LlmProviderError
from classiflow.ingesta.llm_provider import get_llm_langchain
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService
from classiflow.settings import Settings


@runtime_checkable
class _ClassificationChain(Protocol):
    def invoke(
        self, inp: PrimaryClassificationInput, **kwargs: object
    ) -> PrimaryClassificationOutput: ...


class PrimaryClassifierNode(BaseNode):
    @property
    def name(self) -> str:
        return "classification_primary_classifier"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        classification_chain: "_ClassificationChain | None" = None,
        config: ClassificationConfig | None = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.classification_chain: _ClassificationChain | None = classification_chain
        self.config: ClassificationConfig = (
            config if config is not None else get_classification_config()
        )

    async def run(self, ctx: JobContext, cleaned_text: str) -> PrimaryClassificationOutput:
        start = await self._emit_started(ctx)
        try:
            result = await asyncio.to_thread(self.classify, cleaned_text)
        except PrimaryClassificationFailedError as exc:
            await self._emit_and_audit(
                ctx,
                start,
                passed=False,
                detail=AuditDetail.model_validate({"filename": ctx.filename, "error": str(exc)}),
            )
            raise
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
                "label": result.label,
                "confidence": result.confidence,
            }),
        )
        return result

    def classify(self, cleaned_text: str) -> PrimaryClassificationOutput:
        excerpt = cleaned_text[: self.config.max_input_tokens]
        try:
            if self.classification_chain is not None:
                chain: _ClassificationChain = self.classification_chain
            else:
                chain = cast(
                    "_ClassificationChain",
                    build_classification_chain(
                        get_llm_langchain(Settings.classification_model_path)
                    ),
                )
            return chain.invoke(PrimaryClassificationInput(cleaned_text=excerpt))
        except (ValueError, LlmProviderError, OSError, RuntimeError) as exc:
            raise PrimaryClassificationFailedError(reason=str(exc)) from exc
```

```python
# src/classiflow/classification/nodes/__init__.py
from classiflow.classification.nodes.primary_classifier import PrimaryClassifierNode

__all__ = ["PrimaryClassifierNode"]
```

- [x] **Step 6: Run test to verify it passes**

Run: `pytest tests/classification/test_primary_classification_chain.py tests/classification/test_primary_classifier.py -v`
Expected: PASS — both files are `MockLlm`-based, so this passes with no real model file present.

- [x] **Step 7: No download needed — reuses the existing Phi-4-mini model**

`Settings.CLASSIFICATION_MODEL_PATH` reverted to `_DEFAULT_MODEL`
(`models/Phi-4-mini-instruct-Q4_K_M.gguf`), the same file Node2/Node3/enrichment
already share and that's already present on disk — an explicit choice to accept
shared-model risk (a Phi-4-mini weakness would show up at every stage that touches
it, not just the primary classifier) in exchange for zero new download and one fewer
model to manage. `PrimaryClassifierNode`/`build_classification_chain` can be
exercised for real with no setup step.

- [x] **Step 8: Commit**

```bash
git add src/classiflow/classification/prompts/ src/classiflow/classification/nodes/ src/classiflow/classification/exceptions.py tests/classification/test_primary_classification_chain.py tests/classification/test_primary_classifier.py
git commit -m "feat: add primary classification LLM chain and node"
```

---

## Task 6: Second Opinion Agent, part 1 — pure-math port (`embeddings.py`, `ood.py`, `svm_reviewer.py`, `smell_thresholds.py`, `text_cleaning.py`)

Ports the inference-time subset of `bert_tunning`'s scoring code (verified by reading the sibling repo directly — `c:\Users\leona\source\repos\bert_tunning\src\{embeddings.py,ood.py,svm_reviewer.py,smell_thresholds.py,ingestion/_text.py}`). **Not ported**: every training/calibration-only function (`compute_class_stats`, `compute_tfidf_stats`'s fitting path, `save_stats`, `fit_svm_classifiers`, `save_svm_classifiers`, `evaluate_svm_classifiers`, `fit_and_evaluate_svm_reviewer`, `save_smell_thresholds`) — Classiflow only ever *loads* an artifact `bert_tunning` already produced (`models/bert_tunning_beto_v2/`), it never trains or recalibrates one. `bert_tunning`'s own Pydantic schemas (`EmbeddingStats`, `LexicalStats`, `CalibratedThresholds`, `ArtifactMetadata`, `OodArtifact`) become plain `@dataclass(frozen=True)` here (not `BaseEntity` — they hold raw numpy arrays with no `arbitrary_types_allowed` machinery needed, and never cross an API/DB boundary; they're purely internal to `classification/bert/`). `SmellThresholds` becomes a small pydantic `BaseModel` (mirrors `ClassificationConfig`'s own convention, since it round-trips through JSON the same way). `BertTunningError` becomes the new `ClassificationArtifactError` (added to `classification/exceptions.py` this task). `Settings.OOD_KNN_NEIGHBORS` (bert_tunning's own fixed default, `10`, never overridden by any committed model) becomes a hardcoded module constant rather than a new `classification.yaml` key the spec never asked for.

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/classiflow/classification/exceptions.py`
- Create: `src/classiflow/classification/bert/__init__.py`
- Create: `src/classiflow/classification/bert/embeddings.py`
- Create: `src/classiflow/classification/bert/ood_stats.py`
- Create: `src/classiflow/classification/bert/svm_reviewer.py`
- Create: `src/classiflow/classification/bert/smell_thresholds.py`
- Create: `src/classiflow/classification/bert/text_cleaning.py`
- Create: `tests/classification/bert/__init__.py`
- Create: `tests/classification/bert/test_embeddings.py`
- Create: `tests/classification/bert/test_ood_stats.py`
- Create: `tests/classification/bert/test_svm_reviewer.py`
- Create: `tests/classification/bert/test_smell_thresholds.py`
- Create: `tests/classification/bert/test_text_cleaning.py`

**Interfaces:**
- Consumes: `classiflow.classification.config_classification.ClassificationConfig` (Task 4), `classiflow.classification.exceptions.ClassificationArtifactError` (this task).
- Produces: `classiflow.classification.bert.embeddings.{LoadedModel, extract_embeddings, extract_embeddings_and_predictions}`. `classiflow.classification.bert.ood_stats.{EmbeddingStats, LexicalStats, CalibratedThresholds, ArtifactMetadata, OodArtifact, OodThresholds, OodCalibrationStatus, mahalanobis_min_distance, cosine_min_distance, mahalanobis_chi2_p_value_from_distance, empirical_survival_p_value, compute_train_mahalanobis_distances, mahalanobis_empirical_p_value, cosine_z_score, knn_mean_distance, build_tfidf_vectorizer, tfidf_cosine_z_score, resolve_ood_thresholds, resolve_ood_calibration_status, load_stats}`. `classiflow.classification.bert.svm_reviewer.{load_svm_classifiers, svm_scores, svm_top_label}`. `classiflow.classification.bert.smell_thresholds.{SmellThresholds, SmellSignalKey, load_smell_thresholds, resolve_smell_thresholds}`. `classiflow.classification.bert.text_cleaning.{ForeignMunicipalityMatch, clean_text, detect_foreign_municipality}`.

- [x] **Step 1: Add the three new runtime dependencies**

In `pyproject.toml`, add to `dependencies` (after `torchvision`):

```toml
    "scipy>=1.14",
    "scikit-learn>=1.5",
    "transformers>=4.44",
```

Add to `[[tool.mypy.overrides]]`'s `module` list (these three ship incomplete/no type stubs; `joblib` already has `joblib-stubs` in the dev group, so it needs no entry here):

```toml
[[tool.mypy.overrides]]
module = ["google.*", "filetype", "llama_cpp", "faiss", "sentence_transformers", "markitdown", "pymupdf", "easyocr", "scipy.*", "sklearn.*", "transformers"]
ignore_missing_imports = true
```

Hand to the user (per this project's convention — do not run yourself): `uv sync --dev`

- [x] **Step 2: Write the failing tests**

```python
# tests/classification/bert/__init__.py
```
(empty — package marker)

```python
# tests/classification/bert/test_embeddings.py
from unittest.mock import MagicMock

import torch

from classiflow.classification.bert.embeddings import (
    LoadedModel,
    extract_embeddings,
    extract_embeddings_and_predictions,
)


def _mock_loaded_model() -> LoadedModel:
    tokenizer = MagicMock()
    tokenizer.return_value.to.return_value = {
        "input_ids": torch.zeros(2, 8, dtype=torch.long),
        "attention_mask": torch.ones(2, 8, dtype=torch.long),
    }
    model = MagicMock()
    model.return_value.hidden_states = [torch.zeros(2, 8, 4)]
    model.return_value.logits = torch.tensor([[2.0, 0.5], [0.1, 3.0]])
    model.base_model.return_value.last_hidden_state = torch.zeros(2, 8, 4)
    return LoadedModel(model=model, tokenizer=tokenizer, device="cpu")


class TestExtractEmbeddings:
    def test_returns_one_embedding_per_input_text(self) -> None:
        loaded = _mock_loaded_model()
        embeddings = extract_embeddings(loaded, ["doc one", "doc two"], max_length=8, batch_size=16)
        assert embeddings.shape == (2, 4)


class TestExtractEmbeddingsAndPredictions:
    def test_returns_one_embedding_and_prediction_per_input_text(self) -> None:
        loaded = _mock_loaded_model()
        embeddings, predicted_ids = extract_embeddings_and_predictions(
            loaded, ["doc one", "doc two"], max_length=8, batch_size=16
        )
        assert embeddings.shape == (2, 4)
        assert predicted_ids == [0, 1]
```

```python
# tests/classification/bert/test_ood_stats.py
from pathlib import Path

import numpy as np
import pytest

from classiflow.classification.bert.ood_stats import (
    CalibratedThresholds,
    EmbeddingStats,
    OodArtifact,
    OodCalibrationStatus,
    OodThresholds,
    cosine_min_distance,
    cosine_z_score,
    empirical_survival_p_value,
    knn_mean_distance,
    load_stats,
    mahalanobis_chi2_p_value_from_distance,
    mahalanobis_min_distance,
    resolve_ood_calibration_status,
    resolve_ood_thresholds,
)
from classiflow.classification.config_classification import ClassificationConfig


def _stats() -> OodArtifact:
    # Two well-separated 2D classes; pca_mean=0/pca_components=identity makes _project()
    # a no-op, so assertions can reason about raw distances directly.
    centroids = np.array([[0.0, 0.0], [10.0, 10.0]])
    return OodArtifact(
        format_version=2,
        class_names=["class_a", "class_b"],
        embedding=EmbeddingStats(
            pca_mean=np.zeros(2),
            pca_components=np.eye(2),
            centroids=centroids,
            covariance_inv=np.eye(2),
            cosine_calibration_mean=0.5,
            cosine_calibration_std=0.1,
            knn_train_embeddings=np.array([[0.1, 0.1], [0.2, 0.2], [10.1, 10.1]]),
            knn_train_labels=[0, 0, 1],
        ),
    )


class TestMahalanobisMinDistance:
    def test_closer_to_class_a_centroid(self) -> None:
        distance = mahalanobis_min_distance(np.array([0.5, 0.5]), _stats())
        assert distance == pytest.approx(0.5)  # 0.5^2 + 0.5^2, identity covariance_inv


class TestCosineMinDistance:
    def test_returns_nonnegative_float(self) -> None:
        distance = cosine_min_distance(np.array([1.0, 1.0]), _stats())
        assert distance >= 0.0


class TestCosineZScore:
    def test_zscores_against_calibration_mean_and_std(self) -> None:
        stats = _stats()
        z = cosine_z_score(np.array([1.0, 1.0]), stats)
        raw = cosine_min_distance(np.array([1.0, 1.0]), stats)
        assert z == pytest.approx((raw - 0.5) / 0.1)


class TestKnnMeanDistance:
    def test_returns_mean_distance_to_predicted_class_neighbors(self) -> None:
        distance = knn_mean_distance(np.array([0.0, 0.0]), _stats(), predicted_label_id=0, k=2)
        assert distance == pytest.approx(float(np.hypot(0.1, 0.1)))

    def test_returns_nan_for_class_with_no_training_points(self) -> None:
        distance = knn_mean_distance(np.array([0.0, 0.0]), _stats(), predicted_label_id=5, k=2)
        assert np.isnan(distance)


class TestMahalanobisChi2PValueFromDistance:
    def test_larger_distance_yields_smaller_p_value(self) -> None:
        stats = _stats()
        small_distance_p = mahalanobis_chi2_p_value_from_distance(0.1, stats)
        large_distance_p = mahalanobis_chi2_p_value_from_distance(50.0, stats)
        assert large_distance_p < small_distance_p


class TestEmpiricalSurvivalPValue:
    def test_rank_based_p_value(self) -> None:
        reference = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        p = empirical_survival_p_value(3.0, reference)
        assert p == pytest.approx((3 + 1) / (5 + 1))

    def test_raises_on_empty_reference(self) -> None:
        with pytest.raises(ValueError, match="reference array is empty"):
            empirical_survival_p_value(1.0, np.array([]))


class TestResolveOodThresholds:
    def test_falls_back_to_config_when_not_calibrated(self) -> None:
        stats = _stats()  # thresholds defaults to CalibratedThresholds() -- all None
        config = ClassificationConfig(
            ood_mahalanobis_p_threshold=0.01,
            ood_cosine_threshold=5.0,
            ood_knn_distance_threshold=3.0,
            ood_tfidf_cosine_threshold=2.0,
        )
        resolved = resolve_ood_thresholds(stats, config)
        assert resolved == OodThresholds(
            mahalanobis_p=0.01, cosine_z=5.0, knn_distance=3.0, tfidf_cosine_z=2.0
        )

    def test_prefers_per_model_calibrated_threshold(self) -> None:
        stats = OodArtifact(
            format_version=2,
            class_names=["a"],
            embedding=_stats().embedding,
            thresholds=CalibratedThresholds(mahalanobis_p=0.005, mahalanobis_status="calibrated"),
        )
        config = ClassificationConfig(ood_mahalanobis_p_threshold=0.01)
        resolved = resolve_ood_thresholds(stats, config)
        assert resolved.mahalanobis_p == 0.005


class TestResolveOodCalibrationStatus:
    def test_uncalibrated_stats_report_not_calibrated(self) -> None:
        status = resolve_ood_calibration_status(_stats())
        assert status == OodCalibrationStatus(
            mahalanobis="not_calibrated",
            cosine="not_calibrated",
            knn_distance="not_calibrated",
            tfidf_cosine=None,
        )


class TestLoadStats:
    def test_round_trips_minimal_npz(self, tmp_path: Path) -> None:
        path = tmp_path / "ood_stats.npz"
        np.savez(
            str(path),
            format_version=2,
            class_names=np.array(["class_a", "class_b"]),
            pca_mean=np.zeros(2),
            pca_components=np.eye(2),
            centroids=np.array([[0.0, 0.0], [10.0, 10.0]]),
            covariance_inv=np.eye(2),
            cosine_calibration_mean=0.5,
            cosine_calibration_std=0.1,
            knn_train_embeddings=np.array([[0.1, 0.1], [10.1, 10.1]]),
            knn_train_labels=np.array([0, 1]),
            mahalanobis_p_threshold=np.nan,
            cosine_threshold=np.nan,
            knn_distance_threshold=np.nan,
            tfidf_threshold=np.nan,
            mahalanobis_threshold_status="not_calibrated",
            model_type="",
            model_hidden_size=-1,
        )

        stats = load_stats(path)

        assert stats.format_version == 2
        assert stats.class_names == ["class_a", "class_b"]
        assert stats.lexical.is_fitted() is False
        assert stats.thresholds.mahalanobis_p is None
        assert stats.metadata is None
```

```python
# tests/classification/bert/test_svm_reviewer.py
from pathlib import Path

import numpy as np
from sklearn.svm import SVC

from classiflow.classification.bert.svm_reviewer import (
    load_svm_classifiers,
    svm_scores,
    svm_top_label,
)


def _fitted_svc(positive_center: float) -> SVC:
    x = np.array([
        [positive_center],
        [positive_center + 0.1],
        [-positive_center],
        [-positive_center - 0.1],
    ])
    y = np.array([1, 1, 0, 0])
    svc = SVC(kernel="linear")
    svc.fit(x, y)
    return svc


class TestLoadSvmClassifiers:
    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        assert load_svm_classifiers(tmp_path / "no_such_file.joblib") is None


class TestSvmScores:
    def test_returns_one_score_per_classifier(self) -> None:
        classifiers = {"class_a": _fitted_svc(5.0), "class_b": _fitted_svc(1.0)}
        scores = svm_scores(np.array([5.0]), classifiers)
        assert set(scores) == {"class_a", "class_b"}
        assert all(isinstance(v, float) for v in scores.values())


class TestSvmTopLabel:
    def test_returns_highest_scoring_class(self) -> None:
        assert svm_top_label({"class_a": 0.9, "class_b": -0.2}) == "class_a"
        assert svm_top_label({"class_a": -0.9, "class_b": 0.2}) == "class_b"
```

```python
# tests/classification/bert/test_smell_thresholds.py
import json
from pathlib import Path

from classiflow.classification.bert.ood_stats import OodThresholds
from classiflow.classification.bert.smell_thresholds import (
    SmellThresholds,
    load_smell_thresholds,
    resolve_smell_thresholds,
)


class TestLoadSmellThresholds:
    def test_returns_empty_defaults_when_file_missing(self, tmp_path: Path) -> None:
        thresholds = load_smell_thresholds(str(tmp_path))
        assert thresholds.thresholds == {}
        assert thresholds.mahalanobis_status == "not_calibrated"

    def test_loads_real_file(self, tmp_path: Path) -> None:
        (tmp_path / "smell_thresholds.json").write_text(
            json.dumps({"thresholds": {"svm_margin": 0.1}, "mahalanobis_status": "calibrated"})
        )
        thresholds = load_smell_thresholds(str(tmp_path))
        assert thresholds.thresholds == {"svm_margin": 0.1}
        assert thresholds.mahalanobis_status == "calibrated"


class TestResolveSmellThresholds:
    def test_empty_thresholds_falls_back_to_decision_thresholds(self) -> None:
        decision = OodThresholds(
            mahalanobis_p=0.01, cosine_z=5.0, knn_distance=3.0, tfidf_cosine_z=2.0
        )
        resolved = resolve_smell_thresholds(SmellThresholds(), decision)
        assert resolved == decision

    def test_customized_key_overrides_decision_threshold(self) -> None:
        decision = OodThresholds(
            mahalanobis_p=0.01, cosine_z=5.0, knn_distance=3.0, tfidf_cosine_z=2.0
        )
        smell = SmellThresholds(thresholds={"cosine": 1.0})
        resolved = resolve_smell_thresholds(smell, decision)
        assert resolved.cosine_z == 1.0
        assert resolved.mahalanobis_p == 0.01
```

```python
# tests/classification/bert/test_text_cleaning.py
from classiflow.classification.bert.text_cleaning import clean_text, detect_foreign_municipality
from classiflow.classification.config_classification import ClassificationConfig

_ROSARIO_CONFIG = ClassificationConfig(ood_trained_municipality="rosario")


class TestCleanText:
    def test_strips_form_feed_and_nbsp(self) -> None:
        assert clean_text("a\fb\xa0c") == "a b c"

    def test_collapses_triple_newlines(self) -> None:
        assert clean_text("a\n\n\n\nb") == "a\n\nb"

    def test_strips_markdown_table_separator_rows(self) -> None:
        assert clean_text("| --- | --- |") == ""


class TestDetectForeignMunicipality:
    def test_returns_none_when_only_trained_municipality_named(self) -> None:
        text = "La Municipalidad de Rosario informa..."
        assert detect_foreign_municipality(text, _ROSARIO_CONFIG) is None

    def test_returns_match_for_a_different_municipality(self) -> None:
        text = "La Municipalidad de Cordoba informa una nueva ordenanza."
        match = detect_foreign_municipality(text, _ROSARIO_CONFIG)
        assert match is not None
        assert match.name == "Cordoba"
        assert "Cordoba" in match.context

    def test_returns_none_when_no_municipalidad_phrase_present(self) -> None:
        assert detect_foreign_municipality("Texto sin mención alguna.", _ROSARIO_CONFIG) is None
```

- [x] **Step 3: Run tests to verify they fail**

Run: `pytest tests/classification/bert -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.classification.bert'`

- [x] **Step 4: Add `ClassificationArtifactError` to `exceptions.py`**

Append to `src/classiflow/classification/exceptions.py`:

```python
@dataclass
class ClassificationArtifactError(ClassificationError):
    reason: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Classification artifact error: {self.reason}"
```

- [x] **Step 5: Port `embeddings.py`**

```python
# src/classiflow/classification/bert/embeddings.py
"""Ported verbatim from bert_tunning's src/embeddings.py -- self-contained, no
bert_tunning-specific schema dependencies. Not currently called by any Classiflow node
(SecondOpinionNode does its own single-document tokenize+forward pass, matching
bert_tunning's own inference/classify.py -- these batched helpers exist for parity with
the source and for future bulk-calibration tooling, not a live call path today."""

from collections.abc import Iterator
from typing import NamedTuple

import numpy as np
import numpy.typing as npt
import torch
from transformers import BatchEncoding, PreTrainedTokenizerBase


class LoadedModel(NamedTuple):
    model: torch.nn.Module
    tokenizer: PreTrainedTokenizerBase
    device: str


def _batched_inputs(
    loaded: LoadedModel, texts: list[str], *, max_length: int, batch_size: int
) -> Iterator[BatchEncoding]:
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        yield loaded.tokenizer(
            batch,
            truncation=True,
            padding="max_length",
            max_length=max_length,
            return_tensors="pt",
        ).to(loaded.device)


def _cls_embedding(hidden_state: torch.Tensor) -> npt.NDArray[np.float64]:
    return hidden_state[:, 0, :].cpu().numpy().astype(np.float64)


def extract_embeddings(
    loaded: LoadedModel,
    texts: list[str],
    *,
    max_length: int,
    batch_size: int = 16,
) -> npt.NDArray[np.float64]:
    loaded.model.eval()
    batches: list[npt.NDArray[np.float64]] = []
    with torch.no_grad():
        for inputs in _batched_inputs(loaded, texts, max_length=max_length, batch_size=batch_size):
            hidden = loaded.model.base_model(**inputs).last_hidden_state  # type: ignore[operator]
            batches.append(_cls_embedding(hidden))
    return np.vstack(batches)


def extract_embeddings_and_predictions(
    loaded: LoadedModel,
    texts: list[str],
    *,
    max_length: int,
    batch_size: int = 16,
) -> tuple[npt.NDArray[np.float64], list[int]]:
    loaded.model.eval()
    embedding_batches: list[npt.NDArray[np.float64]] = []
    predicted_ids: list[int] = []
    with torch.no_grad():
        for inputs in _batched_inputs(loaded, texts, max_length=max_length, batch_size=batch_size):
            outputs = loaded.model(**inputs, output_hidden_states=True)
            embedding_batches.append(_cls_embedding(outputs.hidden_states[-1]))
            predicted_ids.extend(outputs.logits.argmax(dim=-1).cpu().tolist())
    return np.vstack(embedding_batches), predicted_ids
```

- [x] **Step 6: Port `ood_stats.py`**

```python
# src/classiflow/classification/bert/ood_stats.py
"""Ported from bert_tunning's src/ood.py -- inference-time subset only. See this task's
description for what was deliberately left out (training/calibration functions)."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NamedTuple

import numpy as np
import numpy.typing as npt
from numpy.lib.npyio import NpzFile
from scipy.stats import chi2
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_distances

from classiflow.classification.bert.text_cleaning import clean_text
from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.exceptions import ClassificationArtifactError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingStats:
    pca_mean: npt.NDArray[np.float64]
    pca_components: npt.NDArray[np.float64]
    centroids: npt.NDArray[np.float64]
    covariance_inv: npt.NDArray[np.float64]
    cosine_calibration_mean: float
    cosine_calibration_std: float
    knn_train_embeddings: npt.NDArray[np.float64]
    knn_train_labels: list[int]


@dataclass(frozen=True)
class LexicalStats:
    vocabulary_terms: list[str] = field(default_factory=list)
    idf: npt.NDArray[np.float64] = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    centroids: npt.NDArray[np.float64] = field(
        default_factory=lambda: np.zeros((0, 0), dtype=np.float64)
    )
    cosine_calibration_mean: float = 0.0
    cosine_calibration_std: float = 1.0

    def is_fitted(self) -> bool:
        return bool(self.vocabulary_terms)


@dataclass(frozen=True)
class CalibratedThresholds:
    mahalanobis_p: float | None = None
    cosine: float | None = None
    knn_distance: float | None = None
    tfidf_cosine: float | None = None
    mahalanobis_status: Literal["not_calibrated", "calibrated", "refused_degenerate"] = (
        "not_calibrated"
    )


@dataclass(frozen=True)
class ArtifactMetadata:
    model_type: str
    model_hidden_size: int


@dataclass(frozen=True)
class OodArtifact:
    format_version: int
    class_names: list[str]
    embedding: EmbeddingStats
    lexical: LexicalStats = field(default_factory=LexicalStats)
    thresholds: CalibratedThresholds = field(default_factory=CalibratedThresholds)
    metadata: ArtifactMetadata | None = None


def _project(embedding: npt.NDArray[np.float64], stats: OodArtifact) -> npt.NDArray[np.float64]:
    return (embedding - stats.embedding.pca_mean) @ stats.embedding.pca_components.T


def _cosine_min_distance_raw(
    point: npt.NDArray[np.float64], centroids: npt.NDArray[np.float64]
) -> float:
    return float(cosine_distances(point.reshape(1, -1), centroids).min())


def build_tfidf_vectorizer(stats: OodArtifact) -> TfidfVectorizer | None:
    # Reconstructs a fixed-vocabulary vectorizer from the two arrays load_stats round-trips
    # through ood_stats.npz -- bit-identical .transform() output to the vectorizer
    # bert_tunning originally fit. None when this model's ood_stats.npz predates the
    # TF-IDF signal (vocabulary_terms empty).
    if not stats.lexical.is_fitted():
        return None
    vocabulary = {term: i for i, term in enumerate(stats.lexical.vocabulary_terms)}
    vectorizer = TfidfVectorizer(vocabulary=vocabulary)
    vectorizer.idf_ = stats.lexical.idf
    return vectorizer


def tfidf_cosine_z_score(text: str, stats: OodArtifact, vectorizer: TfidfVectorizer) -> float:
    point = vectorizer.transform([clean_text(text)]).toarray()[0]
    cosine_raw = _cosine_min_distance_raw(point, stats.lexical.centroids)
    lexical = stats.lexical
    return (cosine_raw - lexical.cosine_calibration_mean) / lexical.cosine_calibration_std


def mahalanobis_min_distance(embedding: npt.NDArray[np.float64], stats: OodArtifact) -> float:
    point = _project(embedding, stats)
    diffs = stats.embedding.centroids - point
    distances = np.einsum("kd,de,ke->k", diffs, stats.embedding.covariance_inv, diffs)
    return float(np.min(distances))


def cosine_min_distance(embedding: npt.NDArray[np.float64], stats: OodArtifact) -> float:
    point = _project(embedding, stats)
    return _cosine_min_distance_raw(point, stats.embedding.centroids)


def mahalanobis_chi2_p_value_from_distance(squared_distance: float, stats: OodArtifact) -> float:
    degrees_of_freedom = stats.embedding.centroids.shape[1]
    return float(chi2.sf(squared_distance, df=degrees_of_freedom))


def empirical_survival_p_value(distance: float, reference: npt.NDArray[np.float64]) -> float:
    # Standard permutation-test empirical p-value: fraction of `reference` values at least
    # as extreme as `distance`, +1/+1 corrected so the result is never exactly 0. Raises on
    # an empty reference rather than fail-open-returning 1.0 -- silently "maximally normal"
    # would be backwards for an anomaly-detection signal.
    if len(reference) == 0:
        msg = "empirical_survival_p_value: reference array is empty, cannot rank against it"
        raise ValueError(msg)
    exceed_count = int(np.sum(reference >= distance))
    return (exceed_count + 1) / (len(reference) + 1)


def compute_train_mahalanobis_distances(stats: OodArtifact) -> npt.NDArray[np.float64]:
    # Squared Mahalanobis distance from every training document to its OWN TRUE class
    # centroid (via knn_train_labels), not the nearest one -- the reference distribution
    # mahalanobis_empirical_p_value ranks a query point's nearest-centroid distance against.
    labels_arr = np.asarray(stats.embedding.knn_train_labels)
    distances = np.empty(len(stats.embedding.knn_train_embeddings), dtype=np.float64)
    for i, point in enumerate(stats.embedding.knn_train_embeddings):
        centroid = stats.embedding.centroids[labels_arr[i]]
        diff = centroid - point
        distances[i] = float(diff @ stats.embedding.covariance_inv @ diff)
    return distances


def mahalanobis_empirical_p_value(
    embedding: npt.NDArray[np.float64],
    stats: OodArtifact,
    train_distances: npt.NDArray[np.float64],
) -> float:
    distance = mahalanobis_min_distance(embedding, stats)
    return empirical_survival_p_value(distance, train_distances)


def cosine_z_score(embedding: npt.NDArray[np.float64], stats: OodArtifact) -> float:
    cosine_raw = cosine_min_distance(embedding, stats)
    mean, std = stats.embedding.cosine_calibration_mean, stats.embedding.cosine_calibration_std
    return (cosine_raw - mean) / std


# ponytail: bert_tunning's own fixed default (Settings.OOD_KNN_NEIGHBORS), never
# overridden by any committed model -- hardcoded here rather than plumbed through
# ClassificationConfig/classification.yaml, which the spec doesn't ask to add a key for.
# Add a config field if a future model ever needs a different value.
_KNN_NEIGHBORS = 10


def knn_mean_distance(
    embedding: npt.NDArray[np.float64],
    stats: OodArtifact,
    predicted_label_id: int,
    *,
    k: int = _KNN_NEIGHBORS,
) -> float:
    # Mean Euclidean distance, in PCA space, to the k nearest training documents that share
    # the predicted class. NaN if the predicted class has zero training points -- callers
    # must treat NaN as anomalous (fail-closed), since `nan > threshold` silently is False.
    point = _project(embedding, stats)
    labels_arr = np.array(stats.embedding.knn_train_labels)
    class_points = stats.embedding.knn_train_embeddings[labels_arr == predicted_label_id]
    if class_points.shape[0] == 0:
        log.warning(
            "knn_mean_distance: class %d has zero training points — returning NaN",
            predicted_label_id,
        )
        return float("nan")
    k_eff = min(k, class_points.shape[0])
    distances = np.linalg.norm(class_points - point, axis=1)
    nearest = np.partition(distances, k_eff - 1)[:k_eff]
    return float(nearest.mean())


class OodThresholds(NamedTuple):
    mahalanobis_p: float
    cosine_z: float
    knn_distance: float
    tfidf_cosine_z: float


def resolve_ood_thresholds(stats: OodArtifact, config: ClassificationConfig) -> OodThresholds:
    # Falls back to config.ood_* per-field, only for whichever threshold this model's own
    # ood_stats.npz hasn't calibrated (None) -- a fully-calibrated stats file never reads
    # config at all.
    return OodThresholds(
        mahalanobis_p=(
            stats.thresholds.mahalanobis_p
            if stats.thresholds.mahalanobis_p is not None
            else config.ood_mahalanobis_p_threshold
        ),
        cosine_z=(
            stats.thresholds.cosine
            if stats.thresholds.cosine is not None
            else config.ood_cosine_threshold
        ),
        knn_distance=(
            stats.thresholds.knn_distance
            if stats.thresholds.knn_distance is not None
            else config.ood_knn_distance_threshold
        ),
        tfidf_cosine_z=(
            stats.thresholds.tfidf_cosine
            if stats.thresholds.tfidf_cosine is not None
            else config.ood_tfidf_cosine_threshold
        ),
    )


class OodCalibrationStatus(NamedTuple):
    mahalanobis: Literal["calibrated", "not_calibrated", "refused_degenerate"]
    cosine: Literal["calibrated", "not_calibrated"]
    knn_distance: Literal["calibrated", "not_calibrated"]
    tfidf_cosine: Literal["calibrated", "not_calibrated"] | None


def resolve_ood_calibration_status(stats: OodArtifact) -> OodCalibrationStatus:
    thresholds = stats.thresholds
    return OodCalibrationStatus(
        mahalanobis=thresholds.mahalanobis_status,
        cosine="calibrated" if thresholds.cosine is not None else "not_calibrated",
        knn_distance="calibrated" if thresholds.knn_distance is not None else "not_calibrated",
        tfidf_cosine=(
            None
            if not stats.lexical.is_fitted()
            else ("calibrated" if thresholds.tfidf_cosine is not None else "not_calibrated")
        ),
    )


def _optional_threshold(data: npt.NDArray[np.float64]) -> float | None:
    value = float(data)
    return None if np.isnan(value) else value


def _optional_str(data: npt.NDArray[np.str_]) -> str | None:
    value = str(data)
    return None if value == "" else value


def _optional_int(data: npt.NDArray[np.int_]) -> int | None:
    value = int(data)
    return None if value == -1 else value


def _threshold_status(
    data: npt.NDArray[np.str_],
) -> Literal["not_calibrated", "calibrated", "refused_degenerate"]:
    value = str(data)
    if value in {"not_calibrated", "calibrated", "refused_degenerate"}:
        return value  # type: ignore[return-value]
    msg = f"ood_stats.npz has an unrecognized mahalanobis_threshold_status: {value!r}"
    raise ClassificationArtifactError(reason=msg)


def _load_embedding_stats(data: NpzFile) -> EmbeddingStats:
    return EmbeddingStats(
        pca_mean=data["pca_mean"],
        pca_components=data["pca_components"],
        centroids=data["centroids"],
        covariance_inv=data["covariance_inv"],
        cosine_calibration_mean=float(data["cosine_calibration_mean"]),
        cosine_calibration_std=float(data["cosine_calibration_std"]),
        knn_train_embeddings=data["knn_train_embeddings"],
        knn_train_labels=data["knn_train_labels"].tolist(),
    )


def _load_lexical_stats(data: NpzFile) -> LexicalStats:
    # "in data.files", not data.get() -- NpzFile has no .get(). Lets a pre-TF-IDF
    # ood_stats.npz (missing these keys entirely) still load with lexical scoring disabled.
    if "tfidf_vocabulary_terms" not in data.files:
        return LexicalStats()
    return LexicalStats(
        vocabulary_terms=data["tfidf_vocabulary_terms"].tolist(),
        idf=data["tfidf_idf"],
        centroids=data["tfidf_centroids"],
        cosine_calibration_mean=float(data["tfidf_cosine_calibration_mean"]),
        cosine_calibration_std=float(data["tfidf_cosine_calibration_std"]),
    )


def _load_thresholds(data: NpzFile) -> CalibratedThresholds:
    return CalibratedThresholds(
        mahalanobis_p=(
            _optional_threshold(data["mahalanobis_p_threshold"])
            if "mahalanobis_p_threshold" in data.files
            else None
        ),
        cosine=(
            _optional_threshold(data["cosine_threshold"])
            if "cosine_threshold" in data.files
            else None
        ),
        knn_distance=(
            _optional_threshold(data["knn_distance_threshold"])
            if "knn_distance_threshold" in data.files
            else None
        ),
        tfidf_cosine=(
            _optional_threshold(data["tfidf_threshold"])
            if "tfidf_threshold" in data.files
            else None
        ),
        mahalanobis_status=(
            _threshold_status(data["mahalanobis_threshold_status"])
            if "mahalanobis_threshold_status" in data.files
            else "not_calibrated"
        ),
    )


def _load_metadata(data: NpzFile) -> ArtifactMetadata | None:
    if "model_type" not in data.files or "model_hidden_size" not in data.files:
        return None
    model_type = _optional_str(data["model_type"])
    model_hidden_size = _optional_int(data["model_hidden_size"])
    if model_type is None or model_hidden_size is None:
        return None
    return ArtifactMetadata(model_type=model_type, model_hidden_size=model_hidden_size)


def load_stats(path: Path) -> OodArtifact:
    data = np.load(str(path), allow_pickle=False)
    format_version = int(data["format_version"]) if "format_version" in data.files else 1
    return OodArtifact(
        format_version=format_version,
        class_names=data["class_names"].tolist(),
        embedding=_load_embedding_stats(data),
        lexical=_load_lexical_stats(data),
        thresholds=_load_thresholds(data),
        metadata=_load_metadata(data),
    )
```

- [x] **Step 7: Port `svm_reviewer.py`**

```python
# src/classiflow/classification/bert/svm_reviewer.py
"""Ported from bert_tunning's src/svm_reviewer.py -- inference-time subset only
(load_svm_classifiers, svm_scores, svm_top_label). Training functions
(fit_svm_classifiers, save_svm_classifiers, evaluate_svm_classifiers,
fit_and_evaluate_svm_reviewer) are not ported -- see this task's description."""

from pathlib import Path

import joblib
import numpy as np
import numpy.typing as npt
from sklearn.svm import SVC


def load_svm_classifiers(path: Path) -> dict[str, SVC] | None:
    if not path.exists():
        return None
    classifiers: dict[str, SVC] = joblib.load(path)
    return classifiers


def svm_scores(embedding: npt.NDArray[np.float64], classifiers: dict[str, SVC]) -> dict[str, float]:
    # Each class's one-vs-rest decision-function margin for this embedding -- positive
    # means inside that class's SVM boundary, negative means outside. Not a probability,
    # not calibrated -- raw evidence for the caller to weigh itself.
    point = embedding.reshape(1, -1)
    return {name: float(svc.decision_function(point)[0]) for name, svc in classifiers.items()}


def svm_top_label(scores: dict[str, float]) -> str:
    return max(scores, key=lambda name: scores[name])
```

- [x] **Step 8: Port `smell_thresholds.py`**

```python
# src/classiflow/classification/bert/smell_thresholds.py
"""Ported from bert_tunning's src/smell_thresholds.py -- load + resolve only
(save_smell_thresholds is a training/calibration-time write path, not ported).
smell_thresholds.json is a second, deliberately decoupled threshold profile used only to
compute smell flags, never in_distribution/review_route directly."""

import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from classiflow.classification.bert.ood_stats import OodThresholds

log = logging.getLogger(__name__)

_FILENAME = "smell_thresholds.json"
SmellSignalKey = Literal["mahalanobis_p", "cosine", "knn_distance", "tfidf_cosine", "svm_margin"]


class SmellThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    thresholds: dict[SmellSignalKey, float] = {}
    mahalanobis_status: Literal["not_calibrated", "calibrated", "refused_degenerate"] = (
        "not_calibrated"
    )


def load_smell_thresholds(model_path: str) -> SmellThresholds:
    path = Path(model_path) / _FILENAME
    if not path.exists():
        log.info(
            "No smell_thresholds.json found at %s — smell thresholds fall back to this "
            "model's decision thresholds",
            path,
        )
        return SmellThresholds()
    return SmellThresholds.model_validate_json(path.read_text())


def resolve_smell_thresholds(
    smell_thresholds: SmellThresholds, decision_thresholds: OodThresholds
) -> OodThresholds:
    # Per-key fallback to the DECISION thresholds (not ClassificationConfig.ood_* directly)
    # when a key is missing -- an empty dict (no smell_thresholds.json, or a key never
    # customized) falls back to every decision-threshold value, so a model with no
    # smell_thresholds.json produces identical smells to the plain decision breakdown.
    thresholds = smell_thresholds.thresholds
    return OodThresholds(
        mahalanobis_p=thresholds.get("mahalanobis_p", decision_thresholds.mahalanobis_p),
        cosine_z=thresholds.get("cosine", decision_thresholds.cosine_z),
        knn_distance=thresholds.get("knn_distance", decision_thresholds.knn_distance),
        tfidf_cosine_z=thresholds.get("tfidf_cosine", decision_thresholds.tfidf_cosine_z),
    )
```

- [x] **Step 9: Port `text_cleaning.py`**

```python
# src/classiflow/classification/bert/text_cleaning.py
"""Ported from bert_tunning's src/ingestion/_text.py -- pure regex/stdlib, no
adaptation needed beyond reading the trained-municipality name from
ClassificationConfig instead of bert_tunning's own Settings singleton."""

import re
from typing import NamedTuple

from classiflow.classification.config_classification import ClassificationConfig

_MUNICIPALIDAD_DE_RE = re.compile(
    # [\s|]+ instead of \s+ throughout -- MarkItDown renders some PDF letterheads as
    # single-cell markdown tables, splitting "Municipalidad de la Ciudad de X" with a
    # stray "|". Treating "|" as just another separator stops it from being captured
    # as part of the name.
    r"municipalidad[\s|]+de[\s|]+(?:la[\s|]+)?(?:ciudad[\s|]+de[\s|]+)?([^\s,.;:()|\n]+)",
    re.IGNORECASE,
)
_CONTEXT_CHARS = 40


class ForeignMunicipalityMatch(NamedTuple):
    name: str
    context: str


def clean_text(text: str) -> str:
    text = text.replace("\f", " ").replace("\xa0", " ")
    text = re.sub(r"\|[-: ]+\|[-: |]+", "", text)
    text = re.sub(r"^\|.*\|$", "", text, flags=re.MULTILINE)
    text = re.sub(r"#+ ", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def detect_foreign_municipality(
    text: str, config: ClassificationConfig
) -> ForeignMunicipalityMatch | None:
    reference = config.ood_trained_municipality
    for match in _MUNICIPALIDAD_DE_RE.finditer(text):
        name = match.group(1)
        if not name.lower().startswith(reference.lower()):
            start = max(0, match.start() - _CONTEXT_CHARS)
            end = min(len(text), match.end() + _CONTEXT_CHARS)
            context = " ".join(text[start:end].split())
            return ForeignMunicipalityMatch(name=name, context=context)
    return None
```

```python
# src/classiflow/classification/bert/__init__.py
```
(empty for now — populated with re-exports once Task 8's `classifier.py` needs a public surface)

- [x] **Step 10: Run tests to verify they pass**

Run: `pytest tests/classification/bert -v`
Expected: PASS

- [x] **Step 11: Commit**

```bash
git add pyproject.toml src/classiflow/classification/exceptions.py src/classiflow/classification/bert/ tests/classification/bert/
git commit -m "feat: port bert_tunning's OOD/SVM/text-cleaning inference math"
```

---

## Task 7: Second Opinion Agent, part 2 — `OodScorer` port

Ports `bert_tunning`'s `src/inference/ood_scorer.py` (verified by reading it directly). `Settings.OOD_ALLOW_UNCALIBRATED_FALLBACK` becomes a hardcoded module constant (`_ALLOW_UNCALIBRATED_FALLBACK = True`), same reasoning as Task 6's `_KNN_NEIGHBORS` — both committed production models rely on this exact fallback today, and neither spec asks for it to be configurable. `OodMetrics` becomes a `BaseEntity` (unlike Task 6's `OodArtifact`/stats containers, this one genuinely crosses into `ClassificationState`/`ClassificationRecord`, so it follows the domain-object convention). `BertTunningError` becomes `ClassificationArtifactError` (Task 6).

**Files:**
- Create: `src/classiflow/classification/bert/ood_scorer.py`
- Create: `tests/classification/bert/test_ood_scorer.py`

**Interfaces:**
- Consumes: everything from Task 6's `ood_stats.py` and `smell_thresholds.py`, `classiflow.classification.config_classification.ClassificationConfig`, `classiflow.classification.exceptions.ClassificationArtifactError`, `classiflow.domain.base.BaseEntity`.
- Produces: `OodMetrics(BaseEntity)` (`mahalanobis_p_value`, `mahalanobis_p_value_theoretical`, `cosine_z`, `knn_distance`, `tfidf_cosine_z: float | None`, `in_distribution: bool`, `mahalanobis_calibration_status`, `cosine_calibration_status`, `knn_distance_calibration_status`, `tfidf_calibration_status: ... | None`, `smells: list[str]`). `OodScorer` — `OodScorer.load(model_path: str) -> OodScorer | None` (staticmethod), `.validate(id2label, model_type, model_hidden_size) -> None` (raises `ClassificationArtifactError`), `.warn_if_uncalibrated() -> None`, `.score(text, embedding, pred_idx, config, smell_thresholds=...) -> OodMetrics | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/classification/bert/test_ood_scorer.py
from pathlib import Path

import numpy as np
import pytest

from classiflow.classification.bert.ood_scorer import OodMetrics, OodScorer
from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.exceptions import ClassificationArtifactError


def _write_minimal_stats(path: Path, *, with_thresholds: bool = False) -> None:
    np.savez(
        str(path),
        format_version=2,
        class_names=np.array(["class_a", "class_b"]),
        pca_mean=np.zeros(2),
        pca_components=np.eye(2),
        centroids=np.array([[0.0, 0.0], [10.0, 10.0]]),
        covariance_inv=np.eye(2),
        cosine_calibration_mean=0.5,
        cosine_calibration_std=0.1,
        knn_train_embeddings=np.array([[0.1, 0.1], [0.2, 0.2], [10.1, 10.1], [10.2, 10.2]]),
        knn_train_labels=np.array([0, 0, 1, 1]),
        mahalanobis_p_threshold=(0.01 if with_thresholds else np.nan),
        cosine_threshold=(5.0 if with_thresholds else np.nan),
        knn_distance_threshold=(3.0 if with_thresholds else np.nan),
        tfidf_threshold=np.nan,
        mahalanobis_threshold_status=("calibrated" if with_thresholds else "not_calibrated"),
        model_type="bert",
        model_hidden_size=4,
    )


class TestOodScorerLoad:
    def test_returns_none_when_no_stats_file(self, tmp_path: Path) -> None:
        assert OodScorer.load(str(tmp_path)) is None

    def test_loads_when_stats_file_present(self, tmp_path: Path) -> None:
        _write_minimal_stats(tmp_path / "ood_stats.npz")
        assert OodScorer.load(str(tmp_path)) is not None


class TestOodScorerValidate:
    def test_raises_on_class_name_mismatch(self, tmp_path: Path) -> None:
        _write_minimal_stats(tmp_path / "ood_stats.npz")
        scorer = OodScorer.load(str(tmp_path))
        assert scorer is not None
        with pytest.raises(ClassificationArtifactError, match="do not match"):
            scorer.validate({0: "class_a", 1: "wrong_name"}, "bert", 4)

    def test_raises_on_model_identity_mismatch(self, tmp_path: Path) -> None:
        _write_minimal_stats(tmp_path / "ood_stats.npz")
        scorer = OodScorer.load(str(tmp_path))
        assert scorer is not None
        with pytest.raises(ClassificationArtifactError, match="different model architecture"):
            scorer.validate({0: "class_a", 1: "class_b"}, "bert", 999)

    def test_passes_for_matching_model(self, tmp_path: Path) -> None:
        _write_minimal_stats(tmp_path / "ood_stats.npz")
        scorer = OodScorer.load(str(tmp_path))
        assert scorer is not None
        scorer.validate({0: "class_a", 1: "class_b"}, "bert", 4)  # must not raise


class TestOodScorerScore:
    def test_returns_metrics_for_in_distribution_point(self, tmp_path: Path) -> None:
        _write_minimal_stats(tmp_path / "ood_stats.npz")
        scorer = OodScorer.load(str(tmp_path))
        assert scorer is not None
        config = ClassificationConfig(
            ood_mahalanobis_p_threshold=0.001,
            ood_cosine_threshold=13.0,
            ood_knn_distance_threshold=5.0,
        )
        metrics = scorer.score("texto de prueba", np.array([0.15, 0.15]), pred_idx=0, config=config)
        assert metrics is not None
        assert isinstance(metrics, OodMetrics)
        assert metrics.in_distribution is True

    def test_flags_anomalous_point_via_mahalanobis(self, tmp_path: Path) -> None:
        _write_minimal_stats(tmp_path / "ood_stats.npz")
        scorer = OodScorer.load(str(tmp_path))
        assert scorer is not None
        config = ClassificationConfig(ood_mahalanobis_p_threshold=0.9)  # near-impossible to pass
        metrics = scorer.score(
            "texto de prueba", np.array([500.0, 500.0]), pred_idx=0, config=config
        )
        assert metrics is not None
        assert metrics.in_distribution is False
        assert "low_mahalanobis_p" in metrics.smells
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/classification/bert/test_ood_scorer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.classification.bert.ood_scorer'`

- [ ] **Step 3: Port `ood_scorer.py`**

```python
# src/classiflow/classification/bert/ood_scorer.py
"""Ported from bert_tunning's src/inference/ood_scorer.py -- the four embedding/lexical
out-of-distribution signals (Mahalanobis, cosine, k-NN, TF-IDF), combined into one
per-document score() call."""

import logging
from functools import cached_property
from pathlib import Path
from typing import Literal, NamedTuple

import numpy as np
import numpy.typing as npt
from pydantic import Field
from sklearn.feature_extraction.text import TfidfVectorizer

from classiflow.classification.bert.ood_stats import (
    OodArtifact,
    OodCalibrationStatus,
    OodThresholds,
    build_tfidf_vectorizer,
    compute_train_mahalanobis_distances,
    cosine_z_score,
    empirical_survival_p_value,
    knn_mean_distance,
    load_stats,
    mahalanobis_chi2_p_value_from_distance,
    mahalanobis_min_distance,
    resolve_ood_calibration_status,
    resolve_ood_thresholds,
    tfidf_cosine_z_score,
)
from classiflow.classification.bert.smell_thresholds import (
    SmellThresholds,
    resolve_smell_thresholds,
)
from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.exceptions import ClassificationArtifactError
from classiflow.domain.base import BaseEntity

log = logging.getLogger(__name__)


class OodMetrics(BaseEntity):
    mahalanobis_p_value: float
    mahalanobis_p_value_theoretical: float
    cosine_z: float
    knn_distance: float
    tfidf_cosine_z: float | None = None
    in_distribution: bool
    mahalanobis_calibration_status: Literal[
        "calibrated", "not_calibrated", "refused_degenerate"
    ] = "calibrated"
    cosine_calibration_status: Literal["calibrated", "not_calibrated"] = "calibrated"
    knn_distance_calibration_status: Literal["calibrated", "not_calibrated"] = "calibrated"
    tfidf_calibration_status: Literal["calibrated", "not_calibrated"] | None = None
    smells: list[str] = Field(default_factory=list)


class OodScores(NamedTuple):
    mahalanobis_p: float
    cosine_z: float
    knn_distance: float
    tfidf_cosine_z: float = float("nan")


_ALL_CALIBRATED = OodCalibrationStatus(
    mahalanobis="calibrated",
    cosine="calibrated",
    knn_distance="calibrated",
    tfidf_cosine="calibrated",
)
_NO_SMELL_THRESHOLDS = SmellThresholds()
# ponytail: bert_tunning's own fixed default (Settings.OOD_ALLOW_UNCALIBRATED_FALLBACK) --
# both committed production models rely on this fallback today, and neither spec asks for
# it to be configurable. Promote to a ClassificationConfig field if a future model needs
# strict per-model calibration enforcement.
_ALLOW_UNCALIBRATED_FALLBACK = True


class OodSignalBreakdown(NamedTuple):
    mahalanobis: bool
    cosine: bool
    knn_distance: bool
    tfidf: bool


def _signal_breakdown(
    scores: OodScores,
    thresholds: OodThresholds,
    calibration_status: OodCalibrationStatus,
    *,
    allow_uncalibrated_fallback: bool,
) -> OodSignalBreakdown:
    maha_blocked = (
        not allow_uncalibrated_fallback and calibration_status.mahalanobis == "not_calibrated"
    )
    maha_anomalous = not maha_blocked and scores.mahalanobis_p < thresholds.mahalanobis_p
    cosine_blocked = (
        not allow_uncalibrated_fallback and calibration_status.cosine == "not_calibrated"
    )
    cosine_anomalous = not cosine_blocked and scores.cosine_z > thresholds.cosine_z
    knn_blocked = (
        not allow_uncalibrated_fallback and calibration_status.knn_distance == "not_calibrated"
    )
    # NaN means the predicted class had zero training points -- fail-closed (anomalous).
    knn_anomalous = not knn_blocked and (
        bool(np.isnan(scores.knn_distance)) or scores.knn_distance > thresholds.knn_distance
    )
    tfidf_blocked = (
        not allow_uncalibrated_fallback and calibration_status.tfidf_cosine == "not_calibrated"
    )
    # Opposite NaN polarity from knn_anomalous, deliberately -- NaN here means this
    # model's ood_stats.npz predates the TF-IDF signal entirely (fail-open), not that this
    # document's signal failed to compute.
    tfidf_anomalous = not tfidf_blocked and (
        not np.isnan(scores.tfidf_cosine_z) and scores.tfidf_cosine_z > thresholds.tfidf_cosine_z
    )
    return OodSignalBreakdown(maha_anomalous, cosine_anomalous, knn_anomalous, tfidf_anomalous)


_SMELL_NAMES = {
    "mahalanobis": "low_mahalanobis_p",
    "cosine": "high_cosine_z",
    "knn_distance": "high_knn_distance",
    "tfidf": "high_tfidf_z",
}


def _smells_from_breakdown(breakdown: OodSignalBreakdown) -> list[str]:
    return [name for field_name, name in _SMELL_NAMES.items() if getattr(breakdown, field_name)]


def _breakdown(
    scores: OodScores, thresholds: OodThresholds, calibration_status: OodCalibrationStatus
) -> OodSignalBreakdown:
    return _signal_breakdown(
        scores,
        thresholds,
        calibration_status,
        allow_uncalibrated_fallback=_ALLOW_UNCALIBRATED_FALLBACK,
    )


class OodScorer:
    """Owns everything derived from a loaded ood_stats.npz: validation against the model
    it's paired with, the uncalibrated-threshold warning, and per-document scoring. One
    instance per SecondOpinionNode's loaded model, built once via load()."""

    def __init__(self, stats: OodArtifact) -> None:
        self._stats = stats

    @staticmethod
    def load(model_path: str) -> "OodScorer | None":
        stats_path = Path(model_path) / "ood_stats.npz"
        if not stats_path.exists():
            log.info("No ood_stats.npz found at %s — OOD scoring disabled", stats_path)
            return None
        log.info("Loaded OOD stats from %s", stats_path)
        return OodScorer(load_stats(stats_path))

    def validate(self, id2label: dict[int, str], model_type: str, model_hidden_size: int) -> None:
        self._validate_class_mapping(id2label)
        self._validate_model_identity(model_type, model_hidden_size)

    def _validate_class_mapping(self, id2label: dict[int, str]) -> None:
        # ood_stats.npz's class_names must match this model's id2label by count AND
        # ordered index, since knn_mean_distance() indexes stats.knn_train_labels
        # directly by the model's own predicted label id.
        expected = [id2label[i] for i in range(len(id2label))]
        if self._stats.class_names != expected:
            msg = (
                f"ood_stats.npz class_names {self._stats.class_names} do not match "
                f"this model's id2label {expected} (order matters, not just the set)."
            )
            raise ClassificationArtifactError(reason=msg)

    def _validate_model_identity(self, model_type: str, model_hidden_size: int) -> None:
        metadata = self._stats.metadata
        if metadata is None:
            return
        mismatched = (
            metadata.model_type != model_type or metadata.model_hidden_size != model_hidden_size
        )
        if mismatched:
            msg = (
                f"ood_stats.npz was computed from model_type={metadata.model_type!r}, "
                f"hidden_size={metadata.model_hidden_size}, but the loaded model is "
                f"model_type={model_type!r}, hidden_size={model_hidden_size} -- this "
                "ood_stats.npz belongs to a different model architecture."
            )
            raise ClassificationArtifactError(reason=msg)

    def warn_if_uncalibrated(self) -> None:
        status = resolve_ood_calibration_status(self._stats)
        uncalibrated = [
            name
            for name, value in (
                ("mahalanobis_p_threshold", status.mahalanobis),
                ("cosine_threshold", status.cosine),
                ("knn_distance_threshold", status.knn_distance),
                ("tfidf_threshold", status.tfidf_cosine),
            )
            if value == "not_calibrated"
        ]
        if uncalibrated:
            log.warning(
                "ood_stats.npz has no per-model value for %s — falling back to "
                "ClassificationConfig.ood_* (calibrated for a specific model, not "
                "necessarily this one).",
                ", ".join(uncalibrated),
            )
        if status.mahalanobis == "refused_degenerate":
            log.info(
                "mahalanobis_p_threshold falls back to config.ood_mahalanobis_p_threshold "
                "because bert_tunning's degenerate-threshold guard correctly refused to "
                "persist a floor-adjacent value for this model — expected, no action needed."
            )

    @cached_property
    def _train_mahalanobis_distances(self) -> npt.NDArray[np.float64]:
        return compute_train_mahalanobis_distances(self._stats)

    @cached_property
    def _tfidf_vectorizer(self) -> "TfidfVectorizer | None":
        return build_tfidf_vectorizer(self._stats)

    def score(
        self,
        text: str,
        embedding: npt.NDArray[np.float64],
        pred_idx: int,
        config: ClassificationConfig,
        smell_thresholds: SmellThresholds = _NO_SMELL_THRESHOLDS,
    ) -> OodMetrics | None:
        train_distances = self._train_mahalanobis_distances
        if len(train_distances) == 0:
            log.warning(
                "ood_stats.npz has no k-NN training data (empty knn_train_embeddings) — "
                "OOD scoring disabled for this prediction"
            )
            return None
        tfidf_z = (
            tfidf_cosine_z_score(text, self._stats, self._tfidf_vectorizer)
            if self._tfidf_vectorizer is not None
            else float("nan")
        )
        squared_distance = mahalanobis_min_distance(embedding, self._stats)
        scores = OodScores(
            mahalanobis_p=empirical_survival_p_value(squared_distance, train_distances),
            cosine_z=cosine_z_score(embedding, self._stats),
            knn_distance=knn_mean_distance(embedding, self._stats, pred_idx),
            tfidf_cosine_z=tfidf_z,
        )
        maha_p_theoretical = mahalanobis_chi2_p_value_from_distance(squared_distance, self._stats)
        decision_thresholds = resolve_ood_thresholds(self._stats, config)
        calibration_status = resolve_ood_calibration_status(self._stats)

        breakdown = _breakdown(scores, decision_thresholds, calibration_status)
        smell_signal_thresholds = resolve_smell_thresholds(smell_thresholds, decision_thresholds)
        smell_breakdown = _breakdown(scores, smell_signal_thresholds, calibration_status)

        return OodMetrics(
            mahalanobis_p_value=round(scores.mahalanobis_p, 6),
            mahalanobis_p_value_theoretical=round(maha_p_theoretical, 6),
            cosine_z=round(scores.cosine_z, 4),
            knn_distance=round(scores.knn_distance, 4),
            tfidf_cosine_z=(
                None if np.isnan(scores.tfidf_cosine_z) else round(scores.tfidf_cosine_z, 4)
            ),
            in_distribution=not any(breakdown),
            mahalanobis_calibration_status=calibration_status.mahalanobis,
            cosine_calibration_status=calibration_status.cosine,
            knn_distance_calibration_status=calibration_status.knn_distance,
            tfidf_calibration_status=calibration_status.tfidf_cosine,
            smells=_smells_from_breakdown(smell_breakdown),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/classification/bert/test_ood_scorer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/classiflow/classification/bert/ood_scorer.py tests/classification/bert/test_ood_scorer.py
git commit -m "feat: port bert_tunning's OodScorer"
```

---

## Task 8: Second Opinion Agent, part 3 — `BertClassifier` + label mapping

Ports `bert_tunning`'s `src/inference/classify.py` (verified by reading it directly), **without** `decide_review_route`, `ConfidenceTier`, `OodEvidence` — Classiflow's own Confidence Gate node (Task 12) and Smells/Risk node (Task 11) fully replace that decision layer, per this spec's Decision 5 and the task framing ("Classiflow only wants the classification/scoring parts, NOT bert_tunning's own confidence-gate/routing logic"). `label_mapping.py` is new — the BETO-to-Classiflow `_LABEL_NORMALIZE` map from the BERT spec's Decision 5.

**Files:**
- Modify: `src/classiflow/classification/domain/results.py`
- Create: `src/classiflow/classification/bert/label_mapping.py`
- Create: `src/classiflow/classification/bert/classifier.py`
- Create: `tests/classification/bert/test_label_mapping.py`
- Create: `tests/classification/bert/test_classifier.py`

**Interfaces:**
- Consumes: everything from Tasks 6–7, `classiflow.classification.config_classification.ClassificationConfig`, `classiflow.classification.exceptions.ClassificationArtifactError`.
- Produces: `SecondOpinionResult(BaseEntity)` (`label: str`, `confidence: float`, `all_scores: dict[str, float]`, `svm_scores: dict[str, float]`, `svm_predicted_label: str`, `svm_agrees_with_prediction: bool`, `ood_metrics: OodMetrics | None`) in `domain/results.py`. `classification.bert.label_mapping.{normalize_bert_label(bert_label: str) -> str | None, classifier_disagreement(primary_label: str, second_opinion_label: str) -> bool}`. `classification.bert.classifier.{TransformerModelConfig, TransformerModelOutput, TransformerModel, BertClassifier}` — `BertClassifier(model_path, config, *, tokenizer=None, model=None)`, `.predict(text: str) -> SecondOpinionResult`.

- [x] **Step 1: Write the failing tests**

```python
# tests/classification/bert/test_label_mapping.py
from classiflow.classification.bert.label_mapping import (
    classifier_disagreement,
    normalize_bert_label,
)


class TestNormalizeBertLabel:
    def test_maps_known_beto_label_to_classiflow_taxonomy(self) -> None:
        assert normalize_bert_label("ordenanza") == "ordenanzas"
        assert normalize_bert_label("decreto") == "decretos"
        assert normalize_bert_label("resolucion_concejo_municipal") == (
            "resoluciones_concejo_municipal"
        )

    def test_otro_normalizes_to_none(self) -> None:
        assert normalize_bert_label("otro") is None

    def test_unrecognized_label_normalizes_to_none(self) -> None:
        assert normalize_bert_label("not_a_real_beto_label") is None


class TestClassifierDisagreement:
    def test_agreement_when_labels_match(self) -> None:
        assert classifier_disagreement("ordenanzas", "ordenanza") is False

    def test_disagreement_when_labels_differ(self) -> None:
        assert classifier_disagreement("decretos", "ordenanza") is True

    def test_no_disagreement_when_beto_label_is_otro(self) -> None:
        assert classifier_disagreement("decretos", "otro") is False

    def test_no_disagreement_when_primary_label_outside_beto_taxonomy(self) -> None:
        assert classifier_disagreement("convenios", "ordenanza") is False
        assert classifier_disagreement("compendios_de_boletines", "decreto") is False
```

```python
# tests/classification/bert/test_classifier.py
from pathlib import Path
from unittest.mock import MagicMock, patch

import joblib
import numpy as np
import pytest
import torch
from sklearn.svm import SVC

from classiflow.classification.bert.classifier import BertClassifier
from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.exceptions import ClassificationArtifactError


def _mock_tokenizer() -> MagicMock:
    tokenizer = MagicMock()
    tokenizer.model_max_length = 512
    tokenizer.return_value.to.return_value = {
        "input_ids": torch.zeros(1, 8, dtype=torch.long),
        "attention_mask": torch.ones(1, 8, dtype=torch.long),
    }
    return tokenizer


def _mock_model() -> MagicMock:
    model = MagicMock()
    model.config.id2label = {0: "decreto", 1: "ordenanza"}
    model.config.model_type = "bert"
    model.config.hidden_size = 4
    model.config.max_position_embeddings = 512
    model.return_value.logits = torch.tensor([[0.5, 2.0]])
    model.return_value.hidden_states = [torch.zeros(1, 8, 4)]
    return model


class TestBertClassifierPredict:
    def test_predict_returns_top_label_and_confidence(self, tmp_path: Path) -> None:
        with patch("torch.cuda.is_available", return_value=False):
            classifier = BertClassifier(
                str(tmp_path),
                ClassificationConfig(),
                tokenizer=_mock_tokenizer(),
                model=_mock_model(),
            )
        result = classifier.predict("Ordenanza de prueba")
        assert result.label == "ordenanza"
        assert result.all_scores.keys() == {"decreto", "ordenanza"}
        assert result.svm_scores == {}
        assert result.svm_agrees_with_prediction is True
        assert result.ood_metrics is None  # no ood_stats.npz present in tmp_path

    def test_disables_ood_and_svm_when_artifacts_absent(self, tmp_path: Path) -> None:
        with patch("torch.cuda.is_available", return_value=False):
            classifier = BertClassifier(
                str(tmp_path),
                ClassificationConfig(),
                tokenizer=_mock_tokenizer(),
                model=_mock_model(),
            )
        assert classifier._ood_scorer is None  # noqa: SLF001
        assert classifier._svm_classifiers is None  # noqa: SLF001


class TestBertClassifierSvmClassMappingValidation:
    def test_raises_when_svm_classes_do_not_match_model(self, tmp_path: Path) -> None:
        svc = SVC(kernel="linear")
        svc.fit(np.array([[0.0], [1.0]]), np.array([0, 1]))
        joblib.dump({"wrong_class": svc}, tmp_path / "svm_classifiers.joblib")

        with (
            patch("torch.cuda.is_available", return_value=False),
            pytest.raises(ClassificationArtifactError, match="do not match"),
        ):
            BertClassifier(
                str(tmp_path),
                ClassificationConfig(),
                tokenizer=_mock_tokenizer(),
                model=_mock_model(),
            )
```

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest tests/classification/bert/test_label_mapping.py tests/classification/bert/test_classifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.classification.bert.label_mapping'`

- [x] **Step 3: Add `SecondOpinionResult` to `domain/results.py`**

Append to `src/classiflow/classification/domain/results.py` (add `from classiflow.classification.bert.ood_scorer import OodMetrics` to its imports):

```python
from classiflow.classification.bert.ood_scorer import OodMetrics


class SecondOpinionResult(BaseEntity):
    label: str
    confidence: float
    all_scores: dict[str, float] = Field(default_factory=dict)
    svm_scores: dict[str, float] = Field(default_factory=dict)
    svm_predicted_label: str = ""
    svm_agrees_with_prediction: bool = True
    ood_metrics: OodMetrics | None = None
```

- [x] **Step 4: Implement `label_mapping.py`**

```python
# src/classiflow/classification/bert/label_mapping.py
"""BETO-to-Classiflow label normalization -- see the BERT spec's Decision 5. BETO v2 was
trained on 8 of Classiflow's 10 categories (singular Spanish, not plural snake_case) plus
its own "otro" catch-all with no Classiflow equivalent."""

_LABEL_NORMALIZE: dict[str, str | None] = {
    "boletines": "boletines",
    "declaracion_concejo_municipal": "declaraciones_concejo_municipal",
    "decreto": "decretos",
    "decreto_ordenanza": "decreto_ordenanzas",
    "decretos_concejo_municipal": "decretos_concejo_municipal",
    "ordenanza": "ordenanzas",
    "resolucion": "resoluciones",
    "resolucion_concejo_municipal": "resoluciones_concejo_municipal",
    "otro": None,  # BETO's catch-all -- no Classiflow category equivalent
}
_BETO_TRAINED_LABELS = frozenset(v for v in _LABEL_NORMALIZE.values() if v is not None)


def normalize_bert_label(bert_label: str) -> str | None:
    return _LABEL_NORMALIZE.get(bert_label)


def classifier_disagreement(primary_label: str, second_opinion_label: str) -> bool:
    """primary_label is already in Classiflow's own taxonomy (the primary LLM
    classifier's output); second_opinion_label is BETO's raw label (its own taxonomy).
    False (not forced disagreement) when either label falls outside the mappable set:
    primary_label is convenios/compendios_de_boletines (BETO was never trained on
    these), or BETO's own label is otro. Mirrors bert_tunning's own
    svm_agrees_with_prediction default-True-on-missing-signal pattern rather than
    forcing a disagreement neither classifier can meaningfully confirm or deny."""
    normalized = normalize_bert_label(second_opinion_label)
    if normalized is None or primary_label not in _BETO_TRAINED_LABELS:
        return False
    return normalized != primary_label
```

- [x] **Step 5: Implement `classifier.py`**

```python
# src/classiflow/classification/bert/classifier.py
"""Ported from bert_tunning's src/inference/classify.py -- BertClassifier.predict()
combines tokenization, the BETO forward pass, SVM reviewer scoring, and OOD scoring into
one call. Deliberately NOT ported: decide_review_route, ConfidenceTier, OodEvidence --
bert_tunning's own confidence-gate/routing logic. Classiflow's own Confidence Gate node
(classification/nodes/confidence_gate.py) and Smells/Risk node fully replace that."""

import logging
from pathlib import Path
from typing import Protocol

import numpy as np
import torch
from sklearn.svm import SVC
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    PreTrainedTokenizerBase,
)

from classiflow.classification.bert.ood_scorer import OodScorer
from classiflow.classification.bert.smell_thresholds import load_smell_thresholds
from classiflow.classification.bert.svm_reviewer import load_svm_classifiers, svm_top_label
from classiflow.classification.bert.svm_reviewer import svm_scores as compute_svm_scores
from classiflow.classification.bert.text_cleaning import clean_text
from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.domain.results import SecondOpinionResult
from classiflow.classification.exceptions import ClassificationArtifactError

log = logging.getLogger(__name__)


class TransformerModelConfig(Protocol):
    """The subset of a loaded transformers model's .config this classifier reads."""

    id2label: dict[int, str]
    model_type: str
    hidden_size: int
    max_position_embeddings: int


class TransformerModelOutput(Protocol):
    """The subset of a forward-pass output this classifier reads."""

    logits: torch.Tensor
    hidden_states: tuple[torch.Tensor, ...]


class TransformerModel(Protocol):
    """The subset of a loaded transformers model this classifier depends on -- named
    explicitly instead of typed as Any."""

    config: TransformerModelConfig

    def eval(self) -> "TransformerModel": ...
    def to(self, device: str) -> "TransformerModel": ...
    def __call__(self, **kwargs: torch.Tensor | bool) -> TransformerModelOutput: ...


class BertClassifier:
    def __init__(
        self,
        model_path: str,
        config: ClassificationConfig,
        *,
        tokenizer: PreTrainedTokenizerBase | None = None,
        model: TransformerModel | None = None,
    ) -> None:
        log.info("Loading BETO classifier from %s", model_path)
        self.config = config
        self.tokenizer = tokenizer or AutoTokenizer.from_pretrained(model_path)
        self.model: TransformerModel = model or AutoModelForSequenceClassification.from_pretrained(
            model_path
        )
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.eval()
        self.model.to(self.device)
        self.max_length = min(
            self.tokenizer.model_max_length, self.model.config.max_position_embeddings
        )
        self._ood_scorer = OodScorer.load(model_path)
        if self._ood_scorer is not None:
            self._ood_scorer.validate(
                self.model.config.id2label,
                self.model.config.model_type,
                self.model.config.hidden_size,
            )
            self._ood_scorer.warn_if_uncalibrated()
        self._svm_classifiers = self._load_svm_classifiers(model_path)
        self._validate_svm_classifiers_class_mapping()
        self._smell_thresholds = load_smell_thresholds(model_path)
        log.info("BETO classifier ready on %s (max_length=%d)", self.device, self.max_length)

    @staticmethod
    def _load_svm_classifiers(model_path: str) -> "dict[str, SVC] | None":
        classifiers_path = Path(model_path) / "svm_classifiers.joblib"
        classifiers = load_svm_classifiers(classifiers_path)
        if classifiers is None:
            log.info(
                "No svm_classifiers.joblib found at %s — SVM reviewer disabled",
                classifiers_path,
            )
            return None
        log.info("Loaded SVM reviewer classifiers from %s", classifiers_path)
        return classifiers

    def _validate_svm_classifiers_class_mapping(self) -> None:
        # svm_classifiers.joblib is keyed by class NAME -- only the set needs to match,
        # not the order (unlike ood_stats.npz's class_names, indexed positionally).
        if self._svm_classifiers is None:
            return
        id2label: dict[int, str] = self.model.config.id2label
        expected = set(id2label.values())
        actual = set(self._svm_classifiers.keys())
        if actual != expected:
            msg = (
                f"svm_classifiers.joblib classes {sorted(actual)} do not match this "
                f"model's id2label classes {sorted(expected)} -- svm_scores would be "
                "computed for the wrong classes."
            )
            raise ClassificationArtifactError(reason=msg)

    def predict(self, text: str) -> SecondOpinionResult:
        inputs = self.tokenizer(
            clean_text(text),
            truncation=True,
            padding="max_length",
            max_length=self.max_length,
            return_tensors="pt",
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model(**inputs, output_hidden_states=True)
            probs = torch.softmax(outputs.logits, dim=-1)[0].cpu().numpy()
            cls_embedding = outputs.hidden_states[-1][:, 0, :][0].cpu().numpy().astype(np.float64)

        id2label = self.model.config.id2label
        pred_idx = int(np.argmax(probs))
        confidence = float(probs[pred_idx])
        label = id2label[pred_idx]
        all_scores = {id2label[i]: round(float(p), 4) for i, p in enumerate(probs)}

        if self._svm_classifiers is None:
            svm_scores_result: dict[str, float] = {}
            svm_predicted_label, svm_agrees_with_prediction = "", True
        else:
            svm_scores_result = compute_svm_scores(cls_embedding, self._svm_classifiers)
            svm_predicted_label = svm_top_label(svm_scores_result)
            svm_agrees_with_prediction = svm_predicted_label == label

        ood_metrics = None
        if self._ood_scorer is not None:
            ood_metrics = self._ood_scorer.score(
                text, cls_embedding, pred_idx, self.config, self._smell_thresholds
            )

        return SecondOpinionResult(
            label=label,
            confidence=round(confidence, 4),
            all_scores=all_scores,
            svm_scores=svm_scores_result,
            svm_predicted_label=svm_predicted_label,
            svm_agrees_with_prediction=svm_agrees_with_prediction,
            ood_metrics=ood_metrics,
        )
```

Update `src/classiflow/classification/bert/__init__.py`:

```python
from classiflow.classification.bert.classifier import BertClassifier
from classiflow.classification.bert.label_mapping import (
    classifier_disagreement,
    normalize_bert_label,
)

__all__ = ["BertClassifier", "classifier_disagreement", "normalize_bert_label"]
```

- [x] **Step 6: Run tests to verify they pass**

Run: `pytest tests/classification/bert/test_label_mapping.py tests/classification/bert/test_classifier.py -v`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add src/classiflow/classification/domain/results.py src/classiflow/classification/bert/label_mapping.py src/classiflow/classification/bert/classifier.py src/classiflow/classification/bert/__init__.py tests/classification/bert/test_label_mapping.py tests/classification/bert/test_classifier.py
git commit -m "feat: port BertClassifier and add BETO-to-Classiflow label mapping"
```

---

## Task 9: Second Opinion Agent, part 4 — `SecondOpinionNode` + model artifacts

Wraps Task 8's `BertClassifier` as a `BaseNode`, following `entity_extractor.py`'s node-wrapping pattern (constructor override seam, `_load_bert_classifier` cached singleton loader mirroring `node4_duplicate_control.py`'s `get_sentence_model()`). `classifier_disagreement` is deliberately **not** computed inside this node — it needs both the primary classifier's label (already in coordinator state by the time this node runs) and this node's own output, so the classification coordinator's node-wrapper closure (Task 13) computes it, the same "small glue lives in the coordinator" pattern `enrichment/coordinator.py`'s node closures already use. Also copies the BETO model artifacts from the sibling `bert_tunning` repo (verified absent from Classiflow's `models/` directory) and adds a `Settings.PROJECT_ROOT` export needed to resolve `ClassificationConfig.bert_model_path`'s project-root-relative path.

**Files:**
- Modify: `src/classiflow/settings.py`
- Create: `src/classiflow/classification/nodes/second_opinion.py`
- Modify: `src/classiflow/classification/nodes/__init__.py`
- Create: `tests/classification/test_second_opinion_node.py`

**Interfaces:**
- Consumes: `classiflow.classification.bert.classifier.BertClassifier` (Task 8), `classiflow.classification.domain.results.SecondOpinionResult` (Task 8), `classiflow.classification.config_classification.{ClassificationConfig, get_classification_config}` (Task 4), `classiflow.pipeline.base.BaseNode`, `classiflow.pipeline.context.JobContext`.
- Produces: `Settings.PROJECT_ROOT` (module-level export in `settings.py`, alongside `Settings`). `SecondOpinionNode(BaseNode)` — `__init__(audit, broadcaster, *, classifier=None, config=None)`, `async run(ctx, cleaned_text) -> SecondOpinionResult | None` (returns `None` when `config.second_opinion_enabled` is `False`).

- [x] **Step 1: Confirm the model artifacts are still absent and locate the source**

Run: `Get-ChildItem models\bert_tunning_beto_v2 -ErrorAction SilentlyContinue` from the repo root — expect no output (confirmed absent as of this plan's writing). Source directory (verified on disk): `c:\Users\leona\source\repos\bert_tunning\models\bert_tunning_model_beto_v2\final\` — contains `config.json`, `model.safetensors` (~419MB), `ood_stats.npz` (~1.9MB), `smell_thresholds.json`, `svm_classifiers.joblib` (~2.5MB), `tokenizer.json`, `tokenizer_config.json`, and `training_args.bin` (HF `Trainer` hyperparameters, unused at inference — not copied).

- [x] **Step 2: Copy the model artifacts**

Hand to the user (large binary copy, not a build/verification command, but still not something to run silently in the background):

```powershell
New-Item -ItemType Directory -Force models\bert_tunning_beto_v2 | Out-Null
Copy-Item "c:\Users\leona\source\repos\bert_tunning\models\bert_tunning_model_beto_v2\final\config.json" models\bert_tunning_beto_v2\
Copy-Item "c:\Users\leona\source\repos\bert_tunning\models\bert_tunning_model_beto_v2\final\model.safetensors" models\bert_tunning_beto_v2\
Copy-Item "c:\Users\leona\source\repos\bert_tunning\models\bert_tunning_model_beto_v2\final\ood_stats.npz" models\bert_tunning_beto_v2\
Copy-Item "c:\Users\leona\source\repos\bert_tunning\models\bert_tunning_model_beto_v2\final\smell_thresholds.json" models\bert_tunning_beto_v2\
Copy-Item "c:\Users\leona\source\repos\bert_tunning\models\bert_tunning_model_beto_v2\final\svm_classifiers.joblib" models\bert_tunning_beto_v2\
Copy-Item "c:\Users\leona\source\repos\bert_tunning\models\bert_tunning_model_beto_v2\final\tokenizer.json" models\bert_tunning_beto_v2\
Copy-Item "c:\Users\leona\source\repos\bert_tunning\models\bert_tunning_model_beto_v2\final\tokenizer_config.json" models\bert_tunning_beto_v2\
```

No new `.gitignore` entry needed — `models/**` (minus `!models/**/.gitkeep`) already ignores everything under `models/`, the same pattern every other Classiflow model directory already relies on.

- [x] **Step 3: Write the failing test**

```python
# tests/classification/test_second_opinion_node.py
from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.domain.results import SecondOpinionResult
from classiflow.classification.nodes.second_opinion import SecondOpinionNode
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-second-opinion-001"


class _FakeClassifier:
    def __init__(self, result: SecondOpinionResult) -> None:
        self._result = result

    def predict(self, text: str) -> SecondOpinionResult:
        return self._result


class TestSecondOpinionNodeRun:
    async def test_returns_prediction_when_enabled(self) -> None:
        fake_result = SecondOpinionResult(label="ordenanza", confidence=0.8)
        node = SecondOpinionNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            classifier=_FakeClassifier(fake_result),
            config=ClassificationConfig(second_opinion_enabled=True),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, "texto de prueba")
        assert result is not None
        assert result.label == "ordenanza"

    async def test_returns_none_when_disabled(self) -> None:
        node = SecondOpinionNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            classifier=_FakeClassifier(SecondOpinionResult(label="x", confidence=0.5)),
            config=ClassificationConfig(second_opinion_enabled=False),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, "texto de prueba")
        assert result is None

    async def test_emits_started_then_passed_when_enabled(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = SecondOpinionNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            classifier=_FakeClassifier(SecondOpinionResult(label="ordenanza", confidence=0.8)),
            config=ClassificationConfig(second_opinion_enabled=True),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        await node.run(ctx, "texto de prueba")
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"
```

- [x] **Step 4: Run test to verify it fails**

Run: `pytest tests/classification/test_second_opinion_node.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.classification.nodes.second_opinion'`

- [x] **Step 5: Add `PROJECT_ROOT` to `settings.py`**

In `src/classiflow/settings.py`, add after `Settings = _Settings()`:

```python
# Exposed for callers that need to resolve a project-root-relative path themselves
# (e.g. ClassificationConfig.bert_model_path, which the BERT spec's classification.yaml
# deliberately stores relative to the project root rather than baking an absolute path
# into a config file every clone would need to edit).
PROJECT_ROOT = _PROJECT_ROOT
```

- [x] **Step 6: Implement `SecondOpinionNode`**

```python
# src/classiflow/classification/nodes/second_opinion.py
import asyncio
from functools import lru_cache
from typing import Protocol, cast, runtime_checkable

from classiflow.classification.bert.classifier import BertClassifier
from classiflow.classification.config_classification import (
    ClassificationConfig,
    get_classification_config,
)
from classiflow.classification.domain.results import SecondOpinionResult
from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService
from classiflow.settings import PROJECT_ROOT


@runtime_checkable
class _Classifier(Protocol):
    def predict(self, text: str) -> SecondOpinionResult: ...


@lru_cache(maxsize=1)
def _load_bert_classifier(model_path: str) -> BertClassifier:
    # Same cached-singleton-loader shape as node4_duplicate_control.py's
    # get_sentence_model() -- the BETO weights + OOD/SVM artifacts are expensive to load
    # (~425MB) and are read fresh from config only on the first call.
    return BertClassifier(model_path, get_classification_config())


class SecondOpinionNode(BaseNode):
    @property
    def name(self) -> str:
        return "classification_second_opinion"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        classifier: "_Classifier | None" = None,
        config: ClassificationConfig | None = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.classifier: _Classifier | None = classifier
        self.config: ClassificationConfig = (
            config if config is not None else get_classification_config()
        )

    async def run(self, ctx: JobContext, cleaned_text: str) -> SecondOpinionResult | None:
        if not self.config.second_opinion_enabled:
            return None
        start = await self._emit_started(ctx)
        result = await asyncio.to_thread(self._predict, cleaned_text)
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
                "label": result.label,
                "confidence": result.confidence,
                "svm_agrees_with_prediction": result.svm_agrees_with_prediction,
            }),
        )
        return result

    def _predict(self, cleaned_text: str) -> SecondOpinionResult:
        classifier: _Classifier
        if self.classifier is not None:
            classifier = self.classifier
        else:
            classifier = cast(
                "_Classifier",
                _load_bert_classifier(str(PROJECT_ROOT / self.config.bert_model_path)),
            )
        return classifier.predict(cleaned_text)
```

Update `src/classiflow/classification/nodes/__init__.py`:

```python
from classiflow.classification.nodes.primary_classifier import PrimaryClassifierNode
from classiflow.classification.nodes.second_opinion import SecondOpinionNode

__all__ = ["PrimaryClassifierNode", "SecondOpinionNode"]
```

- [x] **Step 7: Run test to verify it passes**

Run: `pytest tests/classification/test_second_opinion_node.py -v`
Expected: PASS

- [x] **Step 8: Commit**

```bash
git add src/classiflow/settings.py src/classiflow/classification/nodes/second_opinion.py src/classiflow/classification/nodes/__init__.py tests/classification/test_second_opinion_node.py
git commit -m "feat: add SecondOpinionNode wrapping the ported BETO classifier"
```

(The copied `models/bert_tunning_beto_v2/` files from Step 2 are gitignored per Step 2's note — nothing further to stage for them.)

---

## Task 10: Foreign Municipality Detection node

Pure-logic `BaseNode` wrapping Task 6's `detect_foreign_municipality`, per `tasks/plan_stage4.md`'s Foreign Municipality Detection section and this spec's Decision 5 (unchanged from `plan_stage4.md`).

**Files:**
- Create: `src/classiflow/classification/nodes/foreign_municipality.py`
- Modify: `src/classiflow/classification/nodes/__init__.py`
- Create: `tests/classification/test_foreign_municipality_node.py`

**Interfaces:**
- Consumes: `classiflow.classification.bert.text_cleaning.detect_foreign_municipality` (Task 6), `classiflow.classification.config_classification.{ClassificationConfig, get_classification_config}` (Task 4).
- Produces: `ForeignMunicipalityNode(BaseNode)` — `__init__(audit, broadcaster, *, config=None)`, `async run(ctx, cleaned_text) -> str | None`, `detect(cleaned_text) -> str | None` (sync, directly testable; returns `None` when `config.foreign_municipality_enabled` is `False` or no foreign municipality is named).

- [x] **Step 1: Write the failing test**

```python
# tests/classification/test_foreign_municipality_node.py
from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.nodes.foreign_municipality import ForeignMunicipalityNode
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-foreign-municipality-001"


def _node(config: ClassificationConfig) -> ForeignMunicipalityNode:
    return ForeignMunicipalityNode(
        audit=AuditService(InMemoryAuditRepository()), broadcaster=EventBroadcaster(), config=config
    )


class TestForeignMunicipalityDetect:
    def test_returns_none_for_trained_municipality(self) -> None:
        node = _node(
            ClassificationConfig(
                foreign_municipality_enabled=True, ood_trained_municipality="rosario"
            )
        )
        assert node.detect("La Municipalidad de Rosario informa...") is None

    def test_returns_name_for_a_different_municipality(self) -> None:
        node = _node(
            ClassificationConfig(
                foreign_municipality_enabled=True, ood_trained_municipality="rosario"
            )
        )
        assert node.detect("La Municipalidad de Cordoba informa...") == "Cordoba"

    def test_returns_none_when_disabled(self) -> None:
        node = _node(ClassificationConfig(foreign_municipality_enabled=False))
        assert node.detect("La Municipalidad de Cordoba informa...") is None


class TestForeignMunicipalityRun:
    async def test_run_emits_started_then_passed(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = ForeignMunicipalityNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            config=ClassificationConfig(foreign_municipality_enabled=True),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, "La Municipalidad de Cordoba informa...")
        assert result == "Cordoba"
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/classification/test_foreign_municipality_node.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.classification.nodes.foreign_municipality'`

- [x] **Step 3: Implement the node**

```python
# src/classiflow/classification/nodes/foreign_municipality.py
from classiflow.classification.bert.text_cleaning import detect_foreign_municipality
from classiflow.classification.config_classification import (
    ClassificationConfig,
    get_classification_config,
)
from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService


class ForeignMunicipalityNode(BaseNode):
    @property
    def name(self) -> str:
        return "classification_foreign_municipality"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        config: ClassificationConfig | None = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.config: ClassificationConfig = (
            config if config is not None else get_classification_config()
        )

    async def run(self, ctx: JobContext, cleaned_text: str) -> str | None:
        start = await self._emit_started(ctx)
        result = self.detect(cleaned_text)
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
                "foreign_municipality": result,
            }),
        )
        return result

    def detect(self, cleaned_text: str) -> str | None:
        if not self.config.foreign_municipality_enabled:
            return None
        match = detect_foreign_municipality(cleaned_text, self.config)
        return match.name if match is not None else None
```

Update `src/classiflow/classification/nodes/__init__.py`:

```python
from classiflow.classification.nodes.foreign_municipality import ForeignMunicipalityNode
from classiflow.classification.nodes.primary_classifier import PrimaryClassifierNode
from classiflow.classification.nodes.second_opinion import SecondOpinionNode

__all__ = ["ForeignMunicipalityNode", "PrimaryClassifierNode", "SecondOpinionNode"]
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/classification/test_foreign_municipality_node.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/classiflow/classification/nodes/foreign_municipality.py src/classiflow/classification/nodes/__init__.py tests/classification/test_foreign_municipality_node.py
git commit -m "feat: add foreign municipality detection node"
```

---

## Task 11: Smells + Risk Score node

Pure logic, no LLM. Weights table and formula per `tasks/plan_stage4.md` (spec Decision 5, unchanged): `unreadable_document`:3, `classifier_disagreement`:3, `foreign_municipality`:2, `low_svm_margin`:2, `low_confidence`:1; `risk_score = sum(weight for smell in fired_smells)`; `smell_review_suggested = risk_score > config.smell_review_risk_threshold`.

`unreadable_document` is defined here as `cleaned_text` being empty/whitespace-only after Stage 3's cleaning — by the time this coordinator runs, Stage 1's own extraction-failure case (`plan_stage4.md`'s literal "Stage 2 returned `text=None`") can no longer occur, since `_run_classification` (Task 16) only ever runs after a *successful* enrichment; an empty `cleaned_text` is the closest, still-meaningful analog available inside this coordinator's own state. `low_svm_margin` reuses the Second Opinion Agent's own `svm_agrees_with_prediction` flag (Task 8) rather than a numeric SVM-margin threshold — neither spec pins a concrete threshold value for this smell, and BETO's SVM reviewer disagreeing with its own softmax top pick is itself direct evidence the softmax pick's SVM margin isn't dominant.

**Files:**
- Modify: `src/classiflow/classification/domain/results.py`
- Create: `src/classiflow/classification/nodes/smells_risk.py`
- Modify: `src/classiflow/classification/nodes/__init__.py`
- Create: `tests/classification/test_smells_risk_node.py`

**Interfaces:**
- Consumes: `classiflow.classification.config_classification.{ClassificationConfig, get_classification_config}` (Task 4).
- Produces: `SmellsRiskResult(BaseEntity)` (`smells: list[str]`, `risk_score: int`, `smell_review_suggested: bool`) in `domain/results.py`. `SmellsRiskNode(BaseNode)` — `__init__(audit, broadcaster, *, config=None)`, `async run(ctx, *, cleaned_text, confidence, classifier_disagreement, foreign_municipality, svm_agrees_with_prediction) -> SmellsRiskResult`, `compute(...)` (sync, same keyword args, directly testable).

- [x] **Step 1: Write the failing test**

```python
# tests/classification/test_smells_risk_node.py
from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.nodes.smells_risk import SmellsRiskNode
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-smells-risk-001"
_CONFIG = ClassificationConfig(confidence_threshold=0.75, smell_review_risk_threshold=4)


def _node() -> SmellsRiskNode:
    return SmellsRiskNode(
        audit=AuditService(InMemoryAuditRepository()),
        broadcaster=EventBroadcaster(),
        config=_CONFIG,
    )


class TestSmellsRiskCompute:
    def test_no_smells_fire_for_a_clean_confident_document(self) -> None:
        result = _node().compute(
            cleaned_text="Artículo 1º ...",
            confidence=0.9,
            classifier_disagreement=False,
            foreign_municipality=None,
            svm_agrees_with_prediction=True,
        )
        assert result.smells == []
        assert result.risk_score == 0
        assert result.smell_review_suggested is False

    def test_unreadable_document_fires_on_empty_cleaned_text(self) -> None:
        result = _node().compute(
            cleaned_text="   ",
            confidence=0.9,
            classifier_disagreement=False,
            foreign_municipality=None,
            svm_agrees_with_prediction=True,
        )
        assert result.smells == ["unreadable_document"]
        assert result.risk_score == 3

    def test_classifier_disagreement_fires(self) -> None:
        result = _node().compute(
            cleaned_text="texto",
            confidence=0.9,
            classifier_disagreement=True,
            foreign_municipality=None,
            svm_agrees_with_prediction=True,
        )
        assert result.smells == ["classifier_disagreement"]
        assert result.risk_score == 3

    def test_foreign_municipality_fires(self) -> None:
        result = _node().compute(
            cleaned_text="texto",
            confidence=0.9,
            classifier_disagreement=False,
            foreign_municipality="Cordoba",
            svm_agrees_with_prediction=True,
        )
        assert result.smells == ["foreign_municipality"]
        assert result.risk_score == 2

    def test_low_svm_margin_fires(self) -> None:
        result = _node().compute(
            cleaned_text="texto",
            confidence=0.9,
            classifier_disagreement=False,
            foreign_municipality=None,
            svm_agrees_with_prediction=False,
        )
        assert result.smells == ["low_svm_margin"]
        assert result.risk_score == 2

    def test_low_confidence_fires(self) -> None:
        result = _node().compute(
            cleaned_text="texto",
            confidence=0.5,
            classifier_disagreement=False,
            foreign_municipality=None,
            svm_agrees_with_prediction=True,
        )
        assert result.smells == ["low_confidence"]
        assert result.risk_score == 1

    def test_all_smells_fire_together_and_sum_weights(self) -> None:
        result = _node().compute(
            cleaned_text="",
            confidence=0.1,
            classifier_disagreement=True,
            foreign_municipality="Cordoba",
            svm_agrees_with_prediction=False,
        )
        assert set(result.smells) == {
            "unreadable_document",
            "classifier_disagreement",
            "foreign_municipality",
            "low_svm_margin",
            "low_confidence",
        }
        assert result.risk_score == 3 + 3 + 2 + 2 + 1

    def test_boundary_not_exceeding_threshold_is_not_suggested(self) -> None:
        result = _node().compute(
            cleaned_text="texto",
            confidence=0.9,
            classifier_disagreement=False,
            foreign_municipality="Cordoba",
            svm_agrees_with_prediction=False,
        )
        assert result.risk_score == 4  # foreign_municipality(2) + low_svm_margin(2)
        assert result.smell_review_suggested is False  # 4 is not > 4

    def test_boundary_exceeding_threshold_is_suggested(self) -> None:
        result = _node().compute(
            cleaned_text="texto",
            confidence=0.9,
            classifier_disagreement=True,
            foreign_municipality="Cordoba",
            svm_agrees_with_prediction=True,
        )
        assert result.risk_score == 5  # classifier_disagreement(3) + foreign_municipality(2)
        assert result.smell_review_suggested is True  # 5 > 4


class TestSmellsRiskRun:
    async def test_run_emits_started_then_passed(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = SmellsRiskNode(
            audit=AuditService(audit_repo), broadcaster=broadcaster, config=_CONFIG
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        await node.run(
            ctx,
            cleaned_text="texto",
            confidence=0.9,
            classifier_disagreement=False,
            foreign_municipality=None,
            svm_agrees_with_prediction=True,
        )
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/classification/test_smells_risk_node.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.classification.nodes.smells_risk'`

- [x] **Step 3: Add `SmellsRiskResult` to `domain/results.py`**

Append to `src/classiflow/classification/domain/results.py`:

```python
class SmellsRiskResult(BaseEntity):
    smells: list[str] = Field(default_factory=list)
    risk_score: int = 0
    smell_review_suggested: bool = False
```

- [x] **Step 4: Implement the node**

```python
# src/classiflow/classification/nodes/smells_risk.py
"""Pure-logic smell/risk-score computation -- spec Decision 5's weights table,
risk_score = sum(weight of fired smells), smell_review_suggested = risk_score >
config.smell_review_risk_threshold."""

from classiflow.classification.config_classification import (
    ClassificationConfig,
    get_classification_config,
)
from classiflow.classification.domain.results import SmellsRiskResult
from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_SMELL_WEIGHTS = {
    "unreadable_document": 3,
    "classifier_disagreement": 3,
    "foreign_municipality": 2,
    "low_svm_margin": 2,
    "low_confidence": 1,
}


class SmellsRiskNode(BaseNode):
    @property
    def name(self) -> str:
        return "classification_smells_risk"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        config: ClassificationConfig | None = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.config: ClassificationConfig = (
            config if config is not None else get_classification_config()
        )

    async def run(
        self,
        ctx: JobContext,
        *,
        cleaned_text: str,
        confidence: float,
        classifier_disagreement: bool,
        foreign_municipality: str | None,
        svm_agrees_with_prediction: bool,
    ) -> SmellsRiskResult:
        start = await self._emit_started(ctx)
        result = self.compute(
            cleaned_text=cleaned_text,
            confidence=confidence,
            classifier_disagreement=classifier_disagreement,
            foreign_municipality=foreign_municipality,
            svm_agrees_with_prediction=svm_agrees_with_prediction,
        )
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
                "smells": result.smells,
                "risk_score": result.risk_score,
                "smell_review_suggested": result.smell_review_suggested,
            }),
        )
        return result

    def compute(
        self,
        *,
        cleaned_text: str,
        confidence: float,
        classifier_disagreement: bool,
        foreign_municipality: str | None,
        svm_agrees_with_prediction: bool,
    ) -> SmellsRiskResult:
        smells: list[str] = []
        if not cleaned_text.strip():
            smells.append("unreadable_document")
        if classifier_disagreement:
            smells.append("classifier_disagreement")
        if foreign_municipality is not None:
            smells.append("foreign_municipality")
        # ponytail: reuses svm_agrees_with_prediction (already in state) rather than a
        # numeric SVM-margin threshold neither spec pins a value for -- see this task's
        # description.
        if not svm_agrees_with_prediction:
            smells.append("low_svm_margin")
        if confidence < self.config.confidence_threshold:
            smells.append("low_confidence")

        risk_score = sum(_SMELL_WEIGHTS[s] for s in smells)
        return SmellsRiskResult(
            smells=smells,
            risk_score=risk_score,
            smell_review_suggested=risk_score > self.config.smell_review_risk_threshold,
        )
```

Update `src/classiflow/classification/nodes/__init__.py`:

```python
from classiflow.classification.nodes.foreign_municipality import ForeignMunicipalityNode
from classiflow.classification.nodes.primary_classifier import PrimaryClassifierNode
from classiflow.classification.nodes.second_opinion import SecondOpinionNode
from classiflow.classification.nodes.smells_risk import SmellsRiskNode

__all__ = [
    "ForeignMunicipalityNode",
    "PrimaryClassifierNode",
    "SecondOpinionNode",
    "SmellsRiskNode",
]
```

- [x] **Step 5: Run test to verify it passes**

Run: `pytest tests/classification/test_smells_risk_node.py -v`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add src/classiflow/classification/domain/results.py src/classiflow/classification/nodes/smells_risk.py src/classiflow/classification/nodes/__init__.py tests/classification/test_smells_risk_node.py
git commit -m "feat: add smells + risk score node"
```

---

## Task 12: Confidence Gate node

Pure logic. Per `tasks/plan_stage4.md`'s `decide_review_route` and spec Decision 5: `if foreign_municipality or classifier_disagreement: "human_review"`, `elif confidence >= confidence_threshold: "accept"`, `else: "llm_judge"`. `"llm_judge"` is a legitimate, transient value here — Decision 5's clarification that it's "never a persisted or routed terminal state" is enforced downstream, by Routing (Task 14), not by this node.

**Files:**
- Create: `src/classiflow/classification/nodes/confidence_gate.py`
- Modify: `src/classiflow/classification/nodes/__init__.py`
- Create: `tests/classification/test_confidence_gate_node.py`

**Interfaces:**
- Consumes: `classiflow.classification.config_classification.{ClassificationConfig, get_classification_config}` (Task 4).
- Produces: `ConfidenceGateNode(BaseNode)` — `__init__(audit, broadcaster, *, config=None)`, `async run(ctx, *, confidence, foreign_municipality, classifier_disagreement) -> str`, `decide(*, confidence, foreign_municipality, classifier_disagreement) -> str` (sync, directly testable; returns `"accept" | "llm_judge" | "human_review"`).

- [x] **Step 1: Write the failing test**

```python
# tests/classification/test_confidence_gate_node.py
from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.nodes.confidence_gate import ConfidenceGateNode
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-confidence-gate-001"
_CONFIG = ClassificationConfig(confidence_threshold=0.75)


def _node() -> ConfidenceGateNode:
    return ConfidenceGateNode(
        audit=AuditService(InMemoryAuditRepository()),
        broadcaster=EventBroadcaster(),
        config=_CONFIG,
    )


class TestConfidenceGateDecide:
    def test_foreign_municipality_routes_to_human_review_regardless_of_confidence(self) -> None:
        route = _node().decide(
            confidence=0.99, foreign_municipality="Cordoba", classifier_disagreement=False
        )
        assert route == "human_review"

    def test_classifier_disagreement_routes_to_human_review_regardless_of_confidence(self) -> None:
        route = _node().decide(
            confidence=0.99, foreign_municipality=None, classifier_disagreement=True
        )
        assert route == "human_review"

    def test_high_confidence_with_no_flags_accepts(self) -> None:
        route = _node().decide(
            confidence=0.9, foreign_municipality=None, classifier_disagreement=False
        )
        assert route == "accept"

    def test_confidence_exactly_at_threshold_accepts(self) -> None:
        route = _node().decide(
            confidence=0.75, foreign_municipality=None, classifier_disagreement=False
        )
        assert route == "accept"

    def test_low_confidence_with_no_flags_goes_to_llm_judge(self) -> None:
        route = _node().decide(
            confidence=0.5, foreign_municipality=None, classifier_disagreement=False
        )
        assert route == "llm_judge"


class TestConfidenceGateRun:
    async def test_run_emits_started_then_passed(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = ConfidenceGateNode(
            audit=AuditService(audit_repo), broadcaster=broadcaster, config=_CONFIG
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        route = await node.run(
            ctx, confidence=0.9, foreign_municipality=None, classifier_disagreement=False
        )
        assert route == "accept"
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/classification/test_confidence_gate_node.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.classification.nodes.confidence_gate'`

- [x] **Step 3: Implement the node**

```python
# src/classiflow/classification/nodes/confidence_gate.py
"""Pure-logic review-route decision -- spec Decision 5, adapted from
tasks/plan_stage4.md's decide_review_route. "llm_judge" is a legitimate transient
value here; only Routing (Task 14) enforces the two-terminal-state rule."""

from classiflow.classification.config_classification import (
    ClassificationConfig,
    get_classification_config,
)
from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService


class ConfidenceGateNode(BaseNode):
    @property
    def name(self) -> str:
        return "classification_confidence_gate"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        config: ClassificationConfig | None = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.config: ClassificationConfig = (
            config if config is not None else get_classification_config()
        )

    async def run(
        self,
        ctx: JobContext,
        *,
        confidence: float,
        foreign_municipality: str | None,
        classifier_disagreement: bool,
    ) -> str:
        start = await self._emit_started(ctx)
        route = self.decide(
            confidence=confidence,
            foreign_municipality=foreign_municipality,
            classifier_disagreement=classifier_disagreement,
        )
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({"filename": ctx.filename, "review_route": route}),
        )
        return route

    def decide(
        self,
        *,
        confidence: float,
        foreign_municipality: str | None,
        classifier_disagreement: bool,
    ) -> str:
        if foreign_municipality is not None or classifier_disagreement:
            return "human_review"
        if confidence >= self.config.confidence_threshold:
            return "accept"
        return "llm_judge"
```

Update `src/classiflow/classification/nodes/__init__.py`:

```python
from classiflow.classification.nodes.confidence_gate import ConfidenceGateNode
from classiflow.classification.nodes.foreign_municipality import ForeignMunicipalityNode
from classiflow.classification.nodes.primary_classifier import PrimaryClassifierNode
from classiflow.classification.nodes.second_opinion import SecondOpinionNode
from classiflow.classification.nodes.smells_risk import SmellsRiskNode

__all__ = [
    "ConfidenceGateNode",
    "ForeignMunicipalityNode",
    "PrimaryClassifierNode",
    "SecondOpinionNode",
    "SmellsRiskNode",
]
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/classification/test_confidence_gate_node.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/classiflow/classification/nodes/confidence_gate.py src/classiflow/classification/nodes/__init__.py tests/classification/test_confidence_gate_node.py
git commit -m "feat: add confidence gate node"
```

---

## Task 13: LLM Judge — chain + node

Spec Decision 6: single structured LLM call, no tool-use, over the **full** (untruncated) `cleaned_text`, own `Settings.judge_model_path`. Same `BaseEntity`/`.format()`/`RunnableLambda` chain pattern as Task 5, reusing `JudgeOutput` from `domain/results.py` (Task 4) as the chain's output type — same "no duplicate output class" choice as Task 5's `PrimaryClassificationOutput`. The coordinator (Task 15), not this node, decides *whether* to call it (LangGraph conditional edge on `review_route == "llm_judge"`, matching how `ingesta/coordinator.py`'s `add_conditional_edges` already expresses branching in this codebase) and translates `JudgeOutput.accept` into `"accept"`/`"human_review"` plus `judged_by_llm=True` in the state update.

**Files:**
- Modify: `src/classiflow/classification/exceptions.py`
- Create: `src/classiflow/classification/prompts/llm_judge.py`
- Modify: `src/classiflow/classification/prompts/__init__.py`
- Create: `src/classiflow/classification/nodes/llm_judge.py`
- Modify: `src/classiflow/classification/nodes/__init__.py`
- Create: `tests/classification/test_llm_judge_chain.py`
- Create: `tests/classification/test_llm_judge_node.py`

**Interfaces:**
- Consumes: `classiflow.classification.domain.results.JudgeOutput` (Task 4), `classiflow.ingesta.llm_provider.{get_llm_langchain, MockLlm}`, `classiflow.ingesta.exceptions.LlmProviderError`, `Settings.judge_model_path` (Task 4).
- Produces: `classiflow.classification.exceptions.LlmJudgeFailedError(reason: str)`. `JudgeInput(BaseEntity)` (`cleaned_text: str`, `primary_label: str`, `primary_confidence: float`, `second_opinion_label: str | None = None`, `smells: list[str] = []`, `risk_score: int = 0`, `foreign_municipality: str | None = None`), `build_judge_chain(llm: BaseLLM) -> Runnable[JudgeInput, JudgeOutput]`. `LlmJudgeNode(BaseNode)` — `__init__(audit, broadcaster, *, judge_chain=None)`, `async run(ctx, judge_input) -> JudgeOutput` (raises `LlmJudgeFailedError` on chain failure), `judge(judge_input) -> JudgeOutput` (sync, directly testable).

- [x] **Step 1: Write the failing tests**

```python
# tests/classification/test_llm_judge_chain.py
import pytest

from classiflow.classification.prompts.llm_judge import JudgeInput, build_judge_chain
from classiflow.ingesta.llm_provider import MockLlm

_VALID_RESPONSE = '{"accept": true, "reasoning": "label matches the document content"}'
_MALFORMED_RESPONSE = "not json at all"


def _input(**overrides: object) -> JudgeInput:
    defaults: dict[str, object] = {
        "cleaned_text": "Artículo 1º — texto completo sin truncar ...",
        "primary_label": "ordenanzas",
        "primary_confidence": 0.6,
    }
    defaults.update(overrides)
    return JudgeInput.model_validate(defaults)


class TestBuildJudgeChain:
    def test_parses_valid_response(self) -> None:
        chain = build_judge_chain(MockLlm(response=_VALID_RESPONSE))
        output = chain.invoke(_input())
        assert output.accept is True
        assert output.reasoning == "label matches the document content"

    def test_raises_value_error_on_malformed_response(self) -> None:
        chain = build_judge_chain(MockLlm(response=_MALFORMED_RESPONSE))
        with pytest.raises(ValueError, match="No valid JSON object"):
            chain.invoke(_input())
```

```python
# tests/classification/test_llm_judge_node.py
import pytest

from classiflow.classification.exceptions import LlmJudgeFailedError
from classiflow.classification.nodes.llm_judge import LlmJudgeNode
from classiflow.classification.prompts.llm_judge import JudgeInput, build_judge_chain
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-llm-judge-001"
_VALID_RESPONSE = '{"accept": false, "reasoning": "second opinion strongly disagrees"}'
_JUDGE_INPUT = JudgeInput(
    cleaned_text="Artículo 1º — texto completo sin truncar ...",
    primary_label="ordenanzas",
    primary_confidence=0.6,
)


class TestLlmJudgeJudge:
    def test_judge_returns_output_on_valid_response(self) -> None:
        node = LlmJudgeNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            judge_chain=build_judge_chain(MockLlm(response=_VALID_RESPONSE)),
        )
        result = node.judge(_JUDGE_INPUT)
        assert result.accept is False

    def test_judge_raises_domain_error_on_malformed_response(self) -> None:
        node = LlmJudgeNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            judge_chain=build_judge_chain(MockLlm(response="not json")),
        )
        with pytest.raises(LlmJudgeFailedError, match="No valid JSON object"):
            node.judge(_JUDGE_INPUT)


class TestLlmJudgeRun:
    async def test_run_emits_started_then_passed(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = LlmJudgeNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            judge_chain=build_judge_chain(MockLlm(response=_VALID_RESPONSE)),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, _JUDGE_INPUT)
        assert result.accept is False
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"

    async def test_run_emits_failed_and_reraises_on_error(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = LlmJudgeNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            judge_chain=build_judge_chain(MockLlm(response="not json")),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        with pytest.raises(LlmJudgeFailedError):
            await node.run(ctx, _JUDGE_INPUT)
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "failed"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest tests/classification/test_llm_judge_chain.py tests/classification/test_llm_judge_node.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.classification.prompts.llm_judge'`

- [x] **Step 3: Add `LlmJudgeFailedError` to `exceptions.py`**

Append to `src/classiflow/classification/exceptions.py`:

```python
@dataclass
class LlmJudgeFailedError(ClassificationError):
    reason: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"LLM judge failed: {self.reason}"
```

- [x] **Step 4: Implement the chain**

```python
# src/classiflow/classification/prompts/llm_judge.py
import contextlib
import json
import re

from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import Field

from classiflow.classification.domain.results import JudgeOutput
from classiflow.domain.base import BaseEntity


class JudgeInput(BaseEntity):
    cleaned_text: str  # full, untruncated -- unlike PrimaryClassificationInput
    primary_label: str
    primary_confidence: float
    second_opinion_label: str | None = None
    smells: list[str] = Field(default_factory=list)
    risk_score: int = 0
    foreign_municipality: str | None = None


_TEMPLATE = """\
Task: you are a careful reviewer for document classification decisions made by the \
Municipalidad de Rosario's automated pipeline. A primary classifier labeled this \
document but was not confident enough to auto-accept. Decide whether to ACCEPT the \
primary classifier's label or send the document to HUMAN_REVIEW.

Document text: {cleaned_text}

Primary classifier's label: {primary_label} (confidence: {primary_confidence})
Second opinion label (BETO model, may be null if disabled): {second_opinion_label}
Smells detected: {smells}
Risk score: {risk_score}
Foreign municipality detected: {foreign_municipality}

Answer with a single JSON object and nothing else.

JSON:
{{"accept": "true or false -- true means the primary label is correct and safe to accept", \
"reasoning": "one short sentence justifying your decision"}}"""

# Matches a single non-nested JSON object -- same approach as
# enrichment/prompts/entity_extraction.py's _JSON_RE.
_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _extract(text: str) -> JudgeOutput:
    for m in _JSON_RE.finditer(text):
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            return JudgeOutput.model_validate(json.loads(m.group()))
    msg = f"No valid JSON object found in LLM output: {text!r}"
    raise ValueError(msg)


def _format_prompt(chain_input: JudgeInput) -> str:
    return _TEMPLATE.format(
        cleaned_text=chain_input.cleaned_text,
        primary_label=chain_input.primary_label,
        primary_confidence=chain_input.primary_confidence,
        second_opinion_label=chain_input.second_opinion_label,
        smells=", ".join(chain_input.smells) or "none",
        risk_score=chain_input.risk_score,
        foreign_municipality=chain_input.foreign_municipality or "none",
    )


def build_judge_chain(llm: BaseLLM) -> Runnable[JudgeInput, JudgeOutput]:
    return RunnableLambda(_format_prompt) | llm | StrOutputParser() | RunnableLambda(_extract)
```

```python
# src/classiflow/classification/prompts/__init__.py
from classiflow.classification.prompts.llm_judge import JudgeInput, build_judge_chain
from classiflow.classification.prompts.primary_classification import (
    PrimaryClassificationInput,
    build_classification_chain,
)

__all__ = [
    "JudgeInput",
    "PrimaryClassificationInput",
    "build_classification_chain",
    "build_judge_chain",
]
```

- [x] **Step 5: Implement the node**

```python
# src/classiflow/classification/nodes/llm_judge.py
import asyncio
from typing import Protocol, cast, runtime_checkable

from classiflow.classification.domain.results import JudgeOutput
from classiflow.classification.exceptions import LlmJudgeFailedError
from classiflow.classification.prompts.llm_judge import JudgeInput, build_judge_chain
from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.exceptions import LlmProviderError
from classiflow.ingesta.llm_provider import get_llm_langchain
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService
from classiflow.settings import Settings


@runtime_checkable
class _JudgeChain(Protocol):
    def invoke(self, inp: JudgeInput, **kwargs: object) -> JudgeOutput: ...


class LlmJudgeNode(BaseNode):
    @property
    def name(self) -> str:
        return "classification_llm_judge"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        judge_chain: "_JudgeChain | None" = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.judge_chain: _JudgeChain | None = judge_chain

    async def run(self, ctx: JobContext, judge_input: JudgeInput) -> JudgeOutput:
        start = await self._emit_started(ctx)
        try:
            result = await asyncio.to_thread(self.judge, judge_input)
        except LlmJudgeFailedError as exc:
            await self._emit_and_audit(
                ctx,
                start,
                passed=False,
                detail=AuditDetail.model_validate({"filename": ctx.filename, "error": str(exc)}),
            )
            raise
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
                "accept": result.accept,
                "reasoning": result.reasoning,
            }),
        )
        return result

    def judge(self, judge_input: JudgeInput) -> JudgeOutput:
        try:
            if self.judge_chain is not None:
                chain: _JudgeChain = self.judge_chain
            else:
                chain = cast(
                    "_JudgeChain", build_judge_chain(get_llm_langchain(Settings.judge_model_path))
                )
            return chain.invoke(judge_input)
        except (ValueError, LlmProviderError, OSError, RuntimeError) as exc:
            raise LlmJudgeFailedError(reason=str(exc)) from exc
```

Update `src/classiflow/classification/nodes/__init__.py`:

```python
from classiflow.classification.nodes.confidence_gate import ConfidenceGateNode
from classiflow.classification.nodes.foreign_municipality import ForeignMunicipalityNode
from classiflow.classification.nodes.llm_judge import LlmJudgeNode
from classiflow.classification.nodes.primary_classifier import PrimaryClassifierNode
from classiflow.classification.nodes.second_opinion import SecondOpinionNode
from classiflow.classification.nodes.smells_risk import SmellsRiskNode

__all__ = [
    "ConfidenceGateNode",
    "ForeignMunicipalityNode",
    "LlmJudgeNode",
    "PrimaryClassifierNode",
    "SecondOpinionNode",
    "SmellsRiskNode",
]
```

- [x] **Step 6: Run tests to verify they pass**

Run: `pytest tests/classification/test_llm_judge_chain.py tests/classification/test_llm_judge_node.py -v`
Expected: PASS — both files are `MockLlm`-based, so this passes with no real model file present.

- [x] **Step 7: Download the Judge model (manual, one-time — needed only to exercise the real node)**

`Settings.JUDGE_MODEL_PATH` defaults to `models/gemma-4-E4B-it-Q4_K_M.gguf` (set when
`JUDGE_MODEL_PATH` was introduced in Task 4), distinct from `_DEFAULT_MODEL`
(Phi-4-mini-instruct) used everywhere else — a bigger model is worth the extra
inference cost here since the Judge only runs on the minority of documents the
primary classifier already couldn't confidently resolve. That file does not exist
under `models/` yet. Nothing in this task's own automated tests needs it (both test
files above build their chain from `MockLlm`, never `get_llm_langchain`), but it must
be present before `LlmJudgeNode`/`build_judge_chain` can be exercised for real — e.g.
manually via a notebook, or once Task 15's coordinator wires it into an end-to-end run.

Hand to the user (per this project's convention — do not download or run yourself):
verify a Gemma 4 E4B instruction-tuned GGUF build (e.g. from the `unsloth/gemma-4-E4B-it-GGUF`
family on Hugging Face) against the installed `llama-cpp-python` version's supported
GGUF/quantization format, then save it as `models/gemma-4-E4B-it-Q4_K_M.gguf` (gitignored
per the existing `models/**` + `.gitkeep` pattern — no commit needed for the model file
itself).

- [x] **Step 8: Commit**

```bash
git add src/classiflow/classification/exceptions.py src/classiflow/classification/prompts/ src/classiflow/classification/nodes/llm_judge.py src/classiflow/classification/nodes/__init__.py tests/classification/test_llm_judge_chain.py tests/classification/test_llm_judge_node.py
git commit -m "feat: add LLM judge chain and node"
```

---

## Task 14: Routing node

Spec Decision 8: deterministic `BaseNode`, not LLM/tool-using. Bundles the run's full accumulated decision into a single `RoutingInput(BaseEntity)` rather than an 18-parameter `run()` signature — the spec's own illustrative `run(ctx, filename, label, review_route)` snippet elides the rest of what its own comment says the audit entry needs (confidence, smells, risk_score, smell_review_suggested), and this task treats that snippet as illustrative, not literal, resolving it into a real, typed signature. **Persistence design decision, resolving an ambiguity between Decision 8's constructor signature (`classification_repo: IClassificationRecordRepository`, present but unused in the spec's own abbreviated `run()` body) and Decision 9's two call sites**: `RoutingNode.run()` itself performs an **upsert** of `ClassificationRecord` — `find_by_job_id`, update if found, else create — so it's safe to call from both the automatic coordinator run (Task 15, no existing record yet) and the human-decision endpoint (Task 17, updating the record an earlier automatic run already created). This also means Task 16's `_run_classification` does **not** need its own separate persistence step — the coordinator's own terminal Routing node already saves the record as part of `.ainvoke()`.

**Files:**
- Modify: `src/classiflow/classification/domain/results.py`
- Create: `src/classiflow/classification/nodes/routing.py`
- Modify: `src/classiflow/classification/nodes/__init__.py`
- Create: `tests/classification/test_routing_node.py`

**Interfaces:**
- Consumes: `classiflow.storage.document_storage.IDocumentStorage` (Task 1), `classiflow.domain.repositories.classification_record.IClassificationRecordRepository` (Task 3), `classiflow.database.models.ClassificationRecord` (Task 3).
- Produces: `RoutingInput(BaseEntity)` (`job_id: str`, `filename: str`, `enriched_id: int`, `label: str`, `confidence: float`, `all_scores: dict[str, float] = {}`, `second_opinion_label: str | None = None`, `second_opinion_confidence: float = 0.0`, `classifier_disagreement: bool = False`, `ood_metrics: dict[str, object] | None = None`, `svm_scores: dict[str, float] = {}`, `svm_agrees_with_prediction: bool = True`, `review_route: str`, `smells: list[str] = []`, `risk_score: int = 0`, `smell_review_suggested: bool = False`, `foreign_municipality: str | None = None`, `judged_by_llm: bool = False`, `human_overridden: bool = False`) in `domain/results.py`. `RoutingNode(BaseNode)` — `__init__(audit, broadcaster, storage, classification_repo)`, `async run(ctx, routing_input: RoutingInput) -> RoutingResult`.

- [x] **Step 1: Write the failing test**

```python
# tests/classification/test_routing_node.py
from classiflow.classification.domain.results import RoutingInput
from classiflow.classification.nodes.routing import RoutingNode
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.database.repositories.classification_record import (
    InMemoryClassificationRecordRepository,
)
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-routing-001"


class _FakeStorage:
    def __init__(self) -> None:
        self.moved: list[tuple[str, str, str]] = []

    async def save_staged(self, job_id: str, filename: str, file_bytes: bytes) -> str:
        raise NotImplementedError

    async def move_to_final(self, job_id: str, filename: str, subdirectory: str) -> str:
        self.moved.append((job_id, filename, subdirectory))
        return f"/storage/documents/{subdirectory}/{job_id}_{filename}"


def _routing_input(**overrides: object) -> RoutingInput:
    defaults: dict[str, object] = {
        "job_id": _JOB_ID,
        "filename": "doc.pdf",
        "enriched_id": 1,
        "label": "ordenanzas",
        "confidence": 0.9,
        "review_route": "accept",
    }
    defaults.update(overrides)
    return RoutingInput.model_validate(defaults)


class TestRoutingNodeRun:
    async def test_accept_moves_to_classified_subdirectory(self) -> None:
        storage = _FakeStorage()
        node = RoutingNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            storage=storage,
            classification_repo=InMemoryClassificationRecordRepository(),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, _routing_input(review_route="accept", label="ordenanzas"))
        assert storage.moved == [(_JOB_ID, "doc.pdf", "classified/ordenanzas")]
        assert "classified/ordenanzas" in result.stored_path

    async def test_human_review_moves_to_review_subdirectory(self) -> None:
        storage = _FakeStorage()
        node = RoutingNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            storage=storage,
            classification_repo=InMemoryClassificationRecordRepository(),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, _routing_input(review_route="human_review"))
        assert storage.moved == [(_JOB_ID, "doc.pdf", "review/human_review")]
        assert "review/human_review" in result.stored_path

    async def test_persists_classification_record(self) -> None:
        repo = InMemoryClassificationRecordRepository()
        node = RoutingNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            storage=_FakeStorage(),
            classification_repo=repo,
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        await node.run(
            ctx, _routing_input(label="ordenanzas", confidence=0.9, review_route="accept")
        )
        record = await repo.find_by_job_id(_JOB_ID)
        assert record is not None
        assert record.label == "ordenanzas"
        assert record.stored_path is not None

    async def test_second_call_updates_the_same_record_not_a_duplicate(self) -> None:
        repo = InMemoryClassificationRecordRepository()
        node = RoutingNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            storage=_FakeStorage(),
            classification_repo=repo,
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        await node.run(ctx, _routing_input(review_route="human_review"))
        await node.run(
            ctx, _routing_input(review_route="accept", label="ordenanzas", human_overridden=True)
        )
        record = await repo.find_by_job_id(_JOB_ID)
        assert record is not None
        assert record.review_route == "accept"
        assert record.human_overridden is True
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/classification/test_routing_node.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.classification.nodes.routing'`

- [x] **Step 3: Add `RoutingInput` to `domain/results.py`**

Append to `src/classiflow/classification/domain/results.py`:

```python
class RoutingInput(BaseEntity):
    job_id: str
    filename: str
    enriched_id: int
    label: str
    confidence: float
    all_scores: dict[str, float] = Field(default_factory=dict)
    second_opinion_label: str | None = None
    second_opinion_confidence: float = 0.0
    classifier_disagreement: bool = False
    ood_metrics: dict[str, object] | None = None
    svm_scores: dict[str, float] = Field(default_factory=dict)
    svm_agrees_with_prediction: bool = True
    review_route: str
    smells: list[str] = Field(default_factory=list)
    risk_score: int = 0
    smell_review_suggested: bool = False
    foreign_municipality: str | None = None
    judged_by_llm: bool = False
    human_overridden: bool = False
```

- [x] **Step 4: Implement the node**

```python
# src/classiflow/classification/nodes/routing.py
from classiflow.classification.domain.results import RoutingInput, RoutingResult
from classiflow.database.models import ClassificationRecord
from classiflow.database.repositories.audit import AuditDetail
from classiflow.domain.repositories.classification_record import IClassificationRecordRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService
from classiflow.storage.document_storage import IDocumentStorage

_ACCEPT_ROUTE = "accept"
_HUMAN_REVIEW_SUBDIRECTORY = "review/human_review"


class RoutingNode(BaseNode):
    @property
    def name(self) -> str:
        return "classification_routing"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        storage: IDocumentStorage,
        classification_repo: IClassificationRecordRepository,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.storage = storage
        self.classification_repo = classification_repo

    async def run(self, ctx: JobContext, routing_input: RoutingInput) -> RoutingResult:
        start = await self._emit_started(ctx)
        subdirectory = (
            f"classified/{routing_input.label}"
            if routing_input.review_route == _ACCEPT_ROUTE
            else _HUMAN_REVIEW_SUBDIRECTORY
        )
        stored_path = await self.storage.move_to_final(
            routing_input.job_id, routing_input.filename, subdirectory
        )
        await self._save_record(routing_input, stored_path)
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({
                "filename": routing_input.filename,
                "label": routing_input.label,
                "confidence": routing_input.confidence,
                "review_route": routing_input.review_route,
                "smells": routing_input.smells,
                "risk_score": routing_input.risk_score,
                "smell_review_suggested": routing_input.smell_review_suggested,
                "stored_path": stored_path,
            }),
        )
        return RoutingResult(stored_path=stored_path)

    async def _save_record(self, routing_input: RoutingInput, stored_path: str) -> None:
        # Upsert, not always-insert -- this node is called from two places (spec
        # Decision 9): automatically, once, from the classification coordinator; and
        # again from the human-decision endpoint for a job already routed to
        # human_review. The second call updates the SAME row (new
        # label/review_route/human_overridden/stored_path) instead of inserting a
        # duplicate.
        record = await self.classification_repo.find_by_job_id(routing_input.job_id)
        if record is None:
            record = ClassificationRecord(
                job_id=routing_input.job_id, enriched_id=routing_input.enriched_id
            )
        record.enriched_id = routing_input.enriched_id
        record.label = routing_input.label
        record.confidence = routing_input.confidence
        record.all_scores = routing_input.all_scores
        record.second_opinion_label = routing_input.second_opinion_label
        record.second_opinion_confidence = routing_input.second_opinion_confidence
        record.classifier_disagreement = routing_input.classifier_disagreement
        record.ood_metrics = routing_input.ood_metrics
        record.svm_scores = routing_input.svm_scores
        record.svm_agrees_with_prediction = routing_input.svm_agrees_with_prediction
        record.review_route = routing_input.review_route
        record.smells = routing_input.smells
        record.risk_score = routing_input.risk_score
        record.smell_review_suggested = routing_input.smell_review_suggested
        record.foreign_municipality = routing_input.foreign_municipality
        record.judged_by_llm = routing_input.judged_by_llm
        record.stored_path = stored_path
        record.human_overridden = routing_input.human_overridden
        await self.classification_repo.save(record)
```

Update `src/classiflow/classification/nodes/__init__.py`:

```python
from classiflow.classification.nodes.confidence_gate import ConfidenceGateNode
from classiflow.classification.nodes.foreign_municipality import ForeignMunicipalityNode
from classiflow.classification.nodes.llm_judge import LlmJudgeNode
from classiflow.classification.nodes.primary_classifier import PrimaryClassifierNode
from classiflow.classification.nodes.routing import RoutingNode
from classiflow.classification.nodes.second_opinion import SecondOpinionNode
from classiflow.classification.nodes.smells_risk import SmellsRiskNode

__all__ = [
    "ConfidenceGateNode",
    "ForeignMunicipalityNode",
    "LlmJudgeNode",
    "PrimaryClassifierNode",
    "RoutingNode",
    "SecondOpinionNode",
    "SmellsRiskNode",
]
```

- [x] **Step 5: Run test to verify it passes**

Run: `pytest tests/classification/test_routing_node.py -v`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add src/classiflow/classification/domain/results.py src/classiflow/classification/nodes/routing.py src/classiflow/classification/nodes/__init__.py tests/classification/test_routing_node.py
git commit -m "feat: add routing node"
```

---

## Task 15: Classification coordinator (LangGraph)

Wires Tasks 5 and 9–14 into one graph: `primary_classifier → second_opinion → foreign_municipality → smells_risk → confidence_gate → (conditional: llm_judge or routing directly) → [llm_judge →] routing → END`. Follows `enrichment/coordinator.py`'s `_dump()`/`*Update` pattern for the linear stretch, and `ingesta/coordinator.py`'s `add_conditional_edges` pattern for the one real branch (`confidence_gate` → `llm_judge` only when `review_route == "llm_judge"`, else straight to `routing`) — this coordinator needs both patterns, unlike either single-purpose predecessor. `classifier_disagreement` (spec Decision 5) is computed in the `_second_opinion` closure, not inside `SecondOpinionNode` itself (Task 9's design note), since it needs both the already-known primary label and this node's own output.

**Files:**
- Create: `src/classiflow/classification/coordinator.py`
- Create: `tests/classification/test_coordinator.py`

**Interfaces:**
- Consumes: all seven nodes from Tasks 5, 9–14; `ClassificationState`, `ClassificationUpdate` (Task 4); `JudgeInput` (Task 13); `RoutingInput` (Task 14); `classiflow.classification.bert.label_mapping.classifier_disagreement` (Task 8); `classiflow.pipeline.context.JobContext`.
- Produces: `build_classification_coordinator(primary_classifier, second_opinion, foreign_municipality, smells_risk, confidence_gate, llm_judge, routing) -> CompiledStateGraph`. Compiled graph's `.ainvoke(ClassificationState) -> ClassificationState` with `label`, `confidence`, `all_scores`, `review_route`, `judged_by_llm`, `stored_path` (plus whichever optional fields fired) all populated on success.

- [x] **Step 1: Write the failing test**

```python
# tests/classification/test_coordinator.py
from pathlib import Path

from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.coordinator import build_classification_coordinator
from classiflow.classification.domain.results import SecondOpinionResult
from classiflow.classification.domain.state import ClassificationState
from classiflow.classification.nodes import (
    ConfidenceGateNode,
    ForeignMunicipalityNode,
    LlmJudgeNode,
    PrimaryClassifierNode,
    RoutingNode,
    SecondOpinionNode,
    SmellsRiskNode,
)
from classiflow.classification.prompts.llm_judge import build_judge_chain
from classiflow.classification.prompts.primary_classification import build_classification_chain
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.database.repositories.classification_record import (
    InMemoryClassificationRecordRepository,
)
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.services.audit.service import AuditService
from classiflow.storage.document_storage import LocalDiskStorage

_HIGH_CONFIDENCE_RESPONSE = '{"label": "ordenanzas", "confidence": 0.95, "reasoning": "..."}'
_LOW_CONFIDENCE_RESPONSE = '{"label": "ordenanzas", "confidence": 0.3, "reasoning": "..."}'
_JUDGE_ACCEPT_RESPONSE = '{"accept": true, "reasoning": "confirmed"}'


class _NoSecondOpinionClassifier:
    def predict(self, text: str) -> SecondOpinionResult:
        msg = "should not be called when second_opinion_enabled is False"
        raise AssertionError(msg)


def _build_graph(
    primary_response: str, tmp_path: Path, *, judge_response: str = _JUDGE_ACCEPT_RESPONSE
) -> tuple[object, InMemoryClassificationRecordRepository]:
    audit = AuditService(InMemoryAuditRepository())
    broadcaster = EventBroadcaster()
    config = ClassificationConfig(second_opinion_enabled=False, foreign_municipality_enabled=True)
    repo = InMemoryClassificationRecordRepository()
    storage = LocalDiskStorage(root=str(tmp_path))

    primary = PrimaryClassifierNode(
        audit=audit,
        broadcaster=broadcaster,
        classification_chain=build_classification_chain(MockLlm(response=primary_response)),
        config=config,
    )
    second_opinion = SecondOpinionNode(
        audit=audit, broadcaster=broadcaster, classifier=_NoSecondOpinionClassifier(), config=config
    )
    foreign_municipality = ForeignMunicipalityNode(
        audit=audit, broadcaster=broadcaster, config=config
    )
    smells_risk = SmellsRiskNode(audit=audit, broadcaster=broadcaster, config=config)
    confidence_gate = ConfidenceGateNode(audit=audit, broadcaster=broadcaster, config=config)
    llm_judge = LlmJudgeNode(
        audit=audit,
        broadcaster=broadcaster,
        judge_chain=build_judge_chain(MockLlm(response=judge_response)),
    )
    routing = RoutingNode(
        audit=audit, broadcaster=broadcaster, storage=storage, classification_repo=repo
    )
    graph = build_classification_coordinator(
        primary,
        second_opinion,
        foreign_municipality,
        smells_risk,
        confidence_gate,
        llm_judge,
        routing,
    )
    return graph, repo


class TestClassificationCoordinatorAcceptPath:
    async def test_high_confidence_document_is_accepted_and_routed(self, tmp_path: Path) -> None:
        graph, repo = _build_graph(_HIGH_CONFIDENCE_RESPONSE, tmp_path)
        initial: ClassificationState = {
            "job_id": "coord-accept-001",
            "filename": "ordenanza.pdf",
            "cleaned_text": "Artículo 1º — texto de una ordenanza de Rosario.",
            "enriched_id": 1,
        }
        result = await graph.ainvoke(initial)

        assert result["review_route"] == "accept"
        assert result["judged_by_llm"] is False
        assert "classified/ordenanzas" in result["stored_path"]

        record = await repo.find_by_job_id("coord-accept-001")
        assert record is not None
        assert record.review_route == "accept"


class TestClassificationCoordinatorLlmJudgePath:
    async def test_low_confidence_routes_through_judge_to_accept(self, tmp_path: Path) -> None:
        graph, repo = _build_graph(_LOW_CONFIDENCE_RESPONSE, tmp_path)
        initial: ClassificationState = {
            "job_id": "coord-judge-001",
            "filename": "ordenanza.pdf",
            "cleaned_text": "Artículo 1º — texto de una ordenanza de Rosario.",
            "enriched_id": 1,
        }
        result = await graph.ainvoke(initial)

        assert result["review_route"] == "accept"
        assert result["judged_by_llm"] is True

        record = await repo.find_by_job_id("coord-judge-001")
        assert record is not None
        assert record.judged_by_llm is True


class TestClassificationCoordinatorHumanReviewPath:
    async def test_foreign_municipality_routes_to_human_review(self, tmp_path: Path) -> None:
        graph, repo = _build_graph(_HIGH_CONFIDENCE_RESPONSE, tmp_path)
        initial: ClassificationState = {
            "job_id": "coord-human-001",
            "filename": "ordenanza.pdf",
            "cleaned_text": "La Municipalidad de Cordoba informa...",
            "enriched_id": 1,
        }
        result = await graph.ainvoke(initial)

        assert result["review_route"] == "human_review"
        assert "review/human_review" in result["stored_path"]

        record = await repo.find_by_job_id("coord-human-001")
        assert record is not None
        assert record.review_route == "human_review"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/classification/test_coordinator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.classification.coordinator'`

- [x] **Step 3: Implement the coordinator**

```python
# src/classiflow/classification/coordinator.py
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from classiflow.classification.bert.label_mapping import classifier_disagreement
from classiflow.classification.domain.results import RoutingInput
from classiflow.classification.domain.state import ClassificationState, ClassificationUpdate
from classiflow.classification.nodes.confidence_gate import ConfidenceGateNode
from classiflow.classification.nodes.foreign_municipality import ForeignMunicipalityNode
from classiflow.classification.nodes.llm_judge import LlmJudgeNode
from classiflow.classification.nodes.primary_classifier import PrimaryClassifierNode
from classiflow.classification.nodes.routing import RoutingNode
from classiflow.classification.nodes.second_opinion import SecondOpinionNode
from classiflow.classification.nodes.smells_risk import SmellsRiskNode
from classiflow.classification.prompts.llm_judge import JudgeInput
from classiflow.pipeline.context import JobContext

ClassificationUpdateValue = (
    str | float | int | bool | dict[str, float] | dict[str, object] | list[str]
)

_LLM_JUDGE_ROUTE = "llm_judge"


def _dump(update: ClassificationUpdate) -> dict[str, ClassificationUpdateValue]:
    return {k: v for k, v in update if v is not None}


def build_classification_coordinator(
    primary_classifier: PrimaryClassifierNode,
    second_opinion: SecondOpinionNode,
    foreign_municipality: ForeignMunicipalityNode,
    smells_risk: SmellsRiskNode,
    confidence_gate: ConfidenceGateNode,
    llm_judge: LlmJudgeNode,
    routing: RoutingNode,
) -> CompiledStateGraph:  # type: ignore[type-arg]
    async def _primary_classifier(
        state: ClassificationState,
    ) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await primary_classifier.run(ctx, state["cleaned_text"])
        return _dump(
            ClassificationUpdate(
                label=result.label, confidence=result.confidence, all_scores=result.all_scores
            )
        )

    async def _second_opinion(state: ClassificationState) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await second_opinion.run(ctx, state["cleaned_text"])
        if result is None:
            return {}
        return _dump(
            ClassificationUpdate(
                second_opinion_label=result.label,
                second_opinion_confidence=result.confidence,
                classifier_disagreement=classifier_disagreement(state["label"], result.label),
                ood_metrics=(
                    result.ood_metrics.model_dump() if result.ood_metrics is not None else None
                ),
                svm_scores=result.svm_scores,
                svm_agrees_with_prediction=result.svm_agrees_with_prediction,
            )
        )

    async def _foreign_municipality(
        state: ClassificationState,
    ) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await foreign_municipality.run(ctx, state["cleaned_text"])
        return _dump(ClassificationUpdate(foreign_municipality=result))

    async def _smells_risk(state: ClassificationState) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await smells_risk.run(
            ctx,
            cleaned_text=state["cleaned_text"],
            confidence=state["confidence"],
            classifier_disagreement=state.get("classifier_disagreement", False),
            foreign_municipality=state.get("foreign_municipality"),
            svm_agrees_with_prediction=state.get("svm_agrees_with_prediction", True),
        )
        return _dump(
            ClassificationUpdate(
                smells=result.smells,
                risk_score=result.risk_score,
                smell_review_suggested=result.smell_review_suggested,
            )
        )

    async def _confidence_gate(state: ClassificationState) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        route = await confidence_gate.run(
            ctx,
            confidence=state["confidence"],
            foreign_municipality=state.get("foreign_municipality"),
            classifier_disagreement=state.get("classifier_disagreement", False),
        )
        return _dump(ClassificationUpdate(review_route=route))

    async def _llm_judge(state: ClassificationState) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        judge_input = JudgeInput(
            cleaned_text=state["cleaned_text"],
            primary_label=state["label"],
            primary_confidence=state["confidence"],
            second_opinion_label=state.get("second_opinion_label"),
            smells=state.get("smells", []),
            risk_score=state.get("risk_score", 0),
            foreign_municipality=state.get("foreign_municipality"),
        )
        result = await llm_judge.run(ctx, judge_input)
        review_route = "accept" if result.accept else "human_review"
        return _dump(ClassificationUpdate(review_route=review_route, judged_by_llm=True))

    async def _routing(state: ClassificationState) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        routing_input = RoutingInput(
            job_id=state["job_id"],
            filename=state["filename"],
            enriched_id=state["enriched_id"],
            label=state["label"],
            confidence=state["confidence"],
            all_scores=state.get("all_scores", {}),
            second_opinion_label=state.get("second_opinion_label"),
            second_opinion_confidence=state.get("second_opinion_confidence", 0.0),
            classifier_disagreement=state.get("classifier_disagreement", False),
            ood_metrics=state.get("ood_metrics"),
            svm_scores=state.get("svm_scores", {}),
            svm_agrees_with_prediction=state.get("svm_agrees_with_prediction", True),
            review_route=state["review_route"],
            smells=state.get("smells", []),
            risk_score=state.get("risk_score", 0),
            smell_review_suggested=state.get("smell_review_suggested", False),
            foreign_municipality=state.get("foreign_municipality"),
            judged_by_llm=state.get("judged_by_llm", False),
        )
        result = await routing.run(ctx, routing_input)
        return _dump(ClassificationUpdate(stored_path=result.stored_path))

    def _route_after_gate(state: ClassificationState) -> str:
        return _LLM_JUDGE_ROUTE if state.get("review_route") == _LLM_JUDGE_ROUTE else "routing"

    graph: StateGraph = StateGraph(ClassificationState)  # type: ignore[type-arg]
    graph.add_node("primary_classifier", _primary_classifier)
    graph.add_node("second_opinion", _second_opinion)
    graph.add_node("foreign_municipality", _foreign_municipality)
    graph.add_node("smells_risk", _smells_risk)
    graph.add_node("confidence_gate", _confidence_gate)
    graph.add_node("llm_judge", _llm_judge)
    graph.add_node("routing", _routing)

    graph.set_entry_point("primary_classifier")
    graph.add_edge("primary_classifier", "second_opinion")
    graph.add_edge("second_opinion", "foreign_municipality")
    graph.add_edge("foreign_municipality", "smells_risk")
    graph.add_edge("smells_risk", "confidence_gate")
    graph.add_conditional_edges(
        "confidence_gate", _route_after_gate, {"llm_judge": "llm_judge", "routing": "routing"}
    )
    graph.add_edge("llm_judge", "routing")
    graph.add_edge("routing", END)

    return graph.compile()
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/classification/test_coordinator.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/classiflow/classification/coordinator.py tests/classification/test_coordinator.py
git commit -m "feat: add Stage 4 classification coordinator"
```

---

## Task 16: `PipelineService._run_classification` integration + DI wiring

Spec Decision 10: chains straight from a successful `_run_enrichment()` into `_run_classification()`, mirroring Stage 3's own automatic-trigger shape. Since Task 14's `RoutingNode` already persists the `ClassificationRecord` internally (as part of `.ainvoke()`), `_run_classification` itself only needs to build the initial state and run the coordinator — no separate persistence step. Fixes one small pre-existing gap this task's own test exposes: `InMemoryEnrichedRecordRepository.save()` never assigned `EnrichedRecord.id` (fine until now, since nothing previously read it — Stage 4's `ClassificationRecord.enriched_id` FK is the first thing that does).

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/classiflow/database/repositories/enriched_record.py`
- Modify: `src/classiflow/services/pipeline/service.py`
- Modify: `src/classiflow/injections/production.py`
- Modify: `src/classiflow/injections/test.py`
- Modify: `src/classiflow/api/dependencies.py`
- Create: `tests/shared/test_pipeline_service_classification.py`

**Interfaces:**
- Consumes: `classiflow.classification.coordinator.build_classification_coordinator` (Task 15), `classiflow.classification.domain.state.ClassificationState` (Task 4), all seven classification nodes (Tasks 5, 9–14), `classiflow.domain.repositories.classification_record.IClassificationRecordRepository` (Task 3).
- Produces: `PipelineService.__init__(..., classification_coordinator: CompiledStateGraph)` (new 8th param). `PipelineService._run_classification(job_id, filename, enriched_record) -> None`, called from `_run()` only when `_run_enrichment`'s return value is not `None`. `Container.classification_chain`, `Container.judge_chain` (production.py). `get_classification_record_repo`, `get_primary_classifier`, `get_second_opinion`, `get_foreign_municipality`, `get_smells_risk`, `get_confidence_gate`, `get_llm_judge`, `get_routing`, `get_classification_coordinator` (`api/dependencies.py`).

- [x] **Step 1: Fix `InMemoryEnrichedRecordRepository` to assign `id` on save**

In `src/classiflow/database/repositories/enriched_record.py`, update `InMemoryEnrichedRecordRepository`:

```python
class InMemoryEnrichedRecordRepository:
    def __init__(self) -> None:
        self._records: dict[str, EnrichedRecord] = {}
        self._next_id = 1

    async def save(self, record: EnrichedRecord) -> None:
        # Mirrors what a real SqlEnrichedRecordRepository.save() gets for free from
        # AsyncSession.flush() -- an autoincrement id. Nothing read record.id before
        # Task 16 (ClassificationRecord.enriched_id is the first FK that does), so this
        # was a latent gap, not previously a bug in practice.
        if record.id is None:
            record.id = self._next_id
            self._next_id += 1
        self._records[record.job_id] = record

    async def find_by_job_id(self, job_id: str) -> EnrichedRecord | None:
        return self._records.get(job_id)
```

- [x] **Step 2: Write the failing integration test**

```python
# tests/shared/test_pipeline_service_classification.py
import asyncio
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
from fastapi import BackgroundTasks

from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.coordinator import build_classification_coordinator
from classiflow.classification.nodes import (
    ConfidenceGateNode,
    ForeignMunicipalityNode,
    LlmJudgeNode,
    PrimaryClassifierNode,
    RoutingNode,
    SecondOpinionNode,
    SmellsRiskNode,
)
from classiflow.classification.prompts.llm_judge import build_judge_chain
from classiflow.classification.prompts.primary_classification import build_classification_chain
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.database.repositories.classification_record import (
    InMemoryClassificationRecordRepository,
)
from classiflow.database.repositories.document_steps import InMemoryDocumentStepsRepository
from classiflow.database.repositories.enriched_record import InMemoryEnrichedRecordRepository
from classiflow.database.repositories.hash import InMemoryHashRepository
from classiflow.database.repositories.job import InMemoryJobRepository
from classiflow.enrichment.coordinator import build_enrichment_coordinator
from classiflow.enrichment.nodes import EntityExtractorNode, MetadataEnricherNode, TextCleanerNode
from classiflow.enrichment.prompts.entity_extraction import build_entity_extraction_chain
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.coordinator import build_coordinator
from classiflow.ingesta.domain import ExtractionResult
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.ingesta.nodes import (
    ContentValidationNode,
    DuplicateControlNode,
    ExtractionStep,
    FileReceptionNode,
    FormatValidationNode,
)
from classiflow.ingesta.nodes.node4_duplicate_control import EmbeddingStore
from classiflow.ingesta.prompts import build_content_chain
from classiflow.services.audit.service import AuditService
from classiflow.services.pipeline.service import PipelineService
from classiflow.storage.document_storage import LocalDiskStorage

_SPANISH_TEXT = (
    "El Concejo Municipal de Rosario sanciona la siguiente ordenanza: "
    "Artículo 1º — Apruébase el presupuesto municipal para el ejercicio fiscal "
    "correspondiente al año en curso, conforme al detalle que se adjunta."
)
_MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"xref\n0 1\n0000000000 65535 f\ntrailer\n<< /Size 1 >>\nstartxref\n9\n%%EOF"
)
_SLM_LEGITIMATE = '{"is_legitimate": true, "confidence": 0.92, "reasoning": "ok"}'
_VALID_ENTITY_RESPONSE = (
    '{"doc_type_hint": "ordenanza", "number": "1", "year": 2024, '
    '"issuing_body": "Concejo Municipal", "signatories": [], "article_count": 1}'
)
_HIGH_CONFIDENCE_PRIMARY_RESPONSE = (
    '{"label": "ordenanzas", "confidence": 0.95, "reasoning": "clear match"}'
)
_JUDGE_ACCEPT_RESPONSE = '{"accept": true, "reasoning": "ok"}'


def _stub_embed(_text: str) -> npt.NDArray[np.float32]:
    return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


@dataclass
class _MockIsoCode:
    name: str


@dataclass
class _MockLanguage:
    iso_code_639_1: _MockIsoCode


class _MockDetector:
    def __init__(self, iso_code: str) -> None:
        self._iso_code = iso_code

    def detect_language_of(self, _text: str) -> _MockLanguage:
        return _MockLanguage(_MockIsoCode(self._iso_code))


@dataclass
class _ServiceUnderTest:
    service: PipelineService
    job_repo: InMemoryJobRepository
    classification_record_repo: InMemoryClassificationRecordRepository


def _build_service(tmp_path: Path) -> _ServiceUnderTest:
    audit = AuditService(InMemoryAuditRepository())
    broadcaster = EventBroadcaster()
    storage = LocalDiskStorage(root=str(tmp_path))

    n1 = FileReceptionNode(
        audit=audit, broadcaster=broadcaster, mime_detector=lambda _b: "application/pdf"
    )
    n2 = FormatValidationNode(audit=audit, broadcaster=broadcaster)
    extraction_step = ExtractionStep(
        audit=audit,
        broadcaster=broadcaster,
        text_extractor=lambda *_: ExtractionResult(
            text=_SPANISH_TEXT, extractor_used="test", char_count=len(_SPANISH_TEXT)
        ),
        semaphore=asyncio.Semaphore(10),
    )
    n3 = ContentValidationNode(
        audit=audit,
        broadcaster=broadcaster,
        language_detector=_MockDetector("es"),
        content_chain=build_content_chain(MockLlm(response=_SLM_LEGITIMATE)),
    )
    n4 = DuplicateControlNode(
        hash_repo=InMemoryHashRepository(),
        audit=audit,
        broadcaster=broadcaster,
        embedding_store=EmbeddingStore(dim=4, embed_fn=_stub_embed),
    )
    coordinator = build_coordinator(n1, n2, n3, n4, extraction_step=extraction_step)

    text_cleaner = TextCleanerNode(audit=audit, broadcaster=broadcaster)
    entity_extractor = EntityExtractorNode(
        audit=audit,
        broadcaster=broadcaster,
        entity_chain=build_entity_extraction_chain(MockLlm(response=_VALID_ENTITY_RESPONSE)),
    )
    metadata_enricher = MetadataEnricherNode(audit=audit, broadcaster=broadcaster)
    enrichment_coordinator = build_enrichment_coordinator(
        text_cleaner, entity_extractor, metadata_enricher
    )

    classification_config = ClassificationConfig(second_opinion_enabled=False)
    primary_classifier = PrimaryClassifierNode(
        audit=audit,
        broadcaster=broadcaster,
        classification_chain=build_classification_chain(
            MockLlm(response=_HIGH_CONFIDENCE_PRIMARY_RESPONSE)
        ),
        config=classification_config,
    )
    second_opinion = SecondOpinionNode(
        audit=audit, broadcaster=broadcaster, config=classification_config
    )
    foreign_municipality = ForeignMunicipalityNode(
        audit=audit, broadcaster=broadcaster, config=classification_config
    )
    smells_risk = SmellsRiskNode(audit=audit, broadcaster=broadcaster, config=classification_config)
    confidence_gate = ConfidenceGateNode(
        audit=audit, broadcaster=broadcaster, config=classification_config
    )
    llm_judge = LlmJudgeNode(
        audit=audit,
        broadcaster=broadcaster,
        judge_chain=build_judge_chain(MockLlm(response=_JUDGE_ACCEPT_RESPONSE)),
    )
    classification_record_repo = InMemoryClassificationRecordRepository()
    routing = RoutingNode(
        audit=audit,
        broadcaster=broadcaster,
        storage=storage,
        classification_repo=classification_record_repo,
    )
    classification_coordinator = build_classification_coordinator(
        primary_classifier,
        second_opinion,
        foreign_municipality,
        smells_risk,
        confidence_gate,
        llm_judge,
        routing,
    )

    job_repo = InMemoryJobRepository()
    service = PipelineService(
        job_repo=job_repo,
        document_steps_repo=InMemoryDocumentStepsRepository(),
        enriched_record_repo=InMemoryEnrichedRecordRepository(),
        broadcaster=broadcaster,
        coordinator=coordinator,
        enrichment_coordinator=enrichment_coordinator,
        document_storage=storage,
        classification_coordinator=classification_coordinator,
    )
    return _ServiceUnderTest(
        service=service, job_repo=job_repo, classification_record_repo=classification_record_repo
    )


class TestPipelineServiceClassification:
    async def test_accepted_job_reaches_classification_and_persists_record(
        self, tmp_path: Path
    ) -> None:
        under_test = _build_service(tmp_path)
        background_tasks = BackgroundTasks()
        job_id = await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        job = await under_test.job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status == "accepted"

        record = await under_test.classification_record_repo.find_by_job_id(job_id)
        assert record is not None
        assert record.label == "ordenanzas"
        assert record.review_route == "accept"
        assert record.stored_path is not None
        assert "classified/ordenanzas" in record.stored_path
```

- [x] **Step 3: Run test to verify it fails**

Run: `pytest tests/shared/test_pipeline_service_classification.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'classification_coordinator'`

- [x] **Step 4: Bump `max-args` from 7 to 8**

`PipelineService.__init__` and `get_pipeline_service` both grow to 8 params with `classification_coordinator` added. In `pyproject.toml`, update:

```toml
[tool.ruff.lint.pylint]
# Mirrors [tool.pylint.design] max-args below -- FastAPI's Depends()-per-dependency
# style, and PipelineService's own growing set of injected collaborators (job_repo,
# document_steps_repo, enriched_record_repo, broadcaster, coordinator,
# enrichment_coordinator, document_storage, classification_coordinator), mean
# DI-composing functions/classes legitimately grow one param per wired collaborator.
max-args = 8
```

and:

```toml
[tool.pylint.design]
max-args = 8
max-attributes = 7
max-bool-expr = 5
max-branches = 12
max-complexity = 10
max-locals = 15
max-parents = 7
max-public-methods = 20
max-returns = 6
max-statements = 50
```

- [x] **Step 5: Update `PipelineService`**

In `src/classiflow/services/pipeline/service.py`, add `ClassificationState` to the existing `TYPE_CHECKING` block (mirrors `EnrichmentState`'s own precedent — a type used only in annotations, not at runtime):

```python
if TYPE_CHECKING:
    from classiflow.classification.domain.state import ClassificationState
    from classiflow.enrichment.domain.state import EnrichmentState
```

Update `__init__`:

```python
class PipelineService:
    def __init__(
        self,
        job_repo: IJobRepository,
        document_steps_repo: IDocumentStepsRepository,
        enriched_record_repo: IEnrichedRecordRepository,
        broadcaster: EventBroadcaster,
        coordinator: CompiledStateGraph,  # type: ignore[type-arg]
        enrichment_coordinator: CompiledStateGraph,  # type: ignore[type-arg]
        document_storage: IDocumentStorage,
        classification_coordinator: CompiledStateGraph,  # type: ignore[type-arg]
    ) -> None:
        self._job_repo = job_repo
        self._document_steps_repo = document_steps_repo
        self._enriched_record_repo = enriched_record_repo
        self._broadcaster = broadcaster
        self._coordinator = coordinator
        self._enrichment_coordinator = enrichment_coordinator
        self._document_storage = document_storage
        self._classification_coordinator = classification_coordinator
```

Update `_run` to chain into classification:

```python
    async def _run(self, job_id: str, filename: str, file_bytes: bytes) -> None:
        initial: JobState = {"job_id": job_id, "filename": filename, "file_bytes": file_bytes}
        final_state = cast("JobState", await self._coordinator.ainvoke(initial))

        failed_at_node = await self._persist_steps(job_id, final_state)
        await self._finalize_job(job_id, final_state, failed_at_node)

        if final_state.get("extraction") is not None:
            await self._document_storage.save_staged(job_id, filename, file_bytes)

        if final_state.get("final_status") == "accepted":
            enriched_record = await self._run_enrichment(job_id, filename, final_state)
            if enriched_record is not None:
                await self._run_classification(job_id, filename, enriched_record)

        unload_slm()

        await self._broadcaster.emit(
            NodeEvent(job_id=job_id, node=_PIPELINE_NODE, status=JobStatus.DONE)
        )
```

Add the new method, after `_run_enrichment`:

```python
    async def _run_classification(
        self, job_id: str, filename: str, enriched_record: EnrichedRecord
    ) -> None:
        # No retry-then-review fallback here, unlike _run_enrichment -- neither this
        # spec nor the BERT spec describes one for classification failures. A raised
        # ClassificationError simply propagates out of this background task uncaught;
        # revisit if that turns out to need the same bounded-retry treatment Stage 3
        # got.
        initial: ClassificationState = {
            "job_id": job_id,
            "filename": filename,
            "cleaned_text": enriched_record.cleaned_text,
            "enriched_id": enriched_record.id,
        }
        await self._classification_coordinator.ainvoke(initial)
```

- [x] **Step 6: Wire `Container` (production.py)**

Add imports:

```python
from classiflow.classification.prompts.llm_judge import build_judge_chain
from classiflow.classification.prompts.primary_classification import build_classification_chain
```

Add inside `Container`, after `entity_extraction_chain`:

```python
    # Same Callable-wrapping-a-cache reasoning as the other *_llm providers above.
    classification_llm = providers.Callable(get_llm_langchain, Settings.classification_model_path)
    classification_chain = providers.Callable(build_classification_chain, classification_llm)
    judge_llm = providers.Callable(get_llm_langchain, Settings.judge_model_path)
    judge_chain = providers.Callable(build_judge_chain, judge_llm)
```

- [x] **Step 7: Wire `api/dependencies.py`**

Add imports:

```python
from classiflow.classification.coordinator import build_classification_coordinator
from classiflow.classification.domain.results import PrimaryClassificationOutput
from classiflow.classification.nodes import (
    ConfidenceGateNode,
    ForeignMunicipalityNode,
    LlmJudgeNode,
    PrimaryClassifierNode,
    RoutingNode,
    SecondOpinionNode,
    SmellsRiskNode,
)
from classiflow.classification.prompts.llm_judge import JudgeInput
from classiflow.classification.prompts.primary_classification import PrimaryClassificationInput
from classiflow.database.repositories.classification_record import SqlClassificationRecordRepository
from classiflow.domain.repositories.classification_record import IClassificationRecordRepository
from classiflow.storage.document_storage import IDocumentStorage
```

Add `_ClassificationChain`/`_JudgeChain` to the existing `TYPE_CHECKING` block:

```python
if TYPE_CHECKING:
    from classiflow.classification.domain.results import JudgeOutput
    from classiflow.classification.nodes.llm_judge import _JudgeChain
    from classiflow.classification.nodes.primary_classifier import _ClassificationChain
    from classiflow.enrichment.nodes.entity_extractor import _EntityChain
    from classiflow.ingesta.nodes.node2_format_validation import _FormatChain
    from classiflow.ingesta.nodes.node3_content_validation import _ContentChain
```

Add the dependency functions (after `get_enrichment_coordinator`):

```python
def get_classification_record_repo(session: DbSession) -> IClassificationRecordRepository:
    return SqlClassificationRecordRepository(session)


@inject
def get_primary_classifier(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    classification_chain: Annotated[
        Runnable[PrimaryClassificationInput, PrimaryClassificationOutput],
        Depends(Provide[Container.classification_chain]),
    ],
) -> PrimaryClassifierNode:
    return PrimaryClassifierNode(
        audit=audit_service,
        broadcaster=broadcaster,
        classification_chain=cast("_ClassificationChain", classification_chain),
    )


def get_second_opinion(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> SecondOpinionNode:
    return SecondOpinionNode(audit=audit_service, broadcaster=broadcaster)


def get_foreign_municipality(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> ForeignMunicipalityNode:
    return ForeignMunicipalityNode(audit=audit_service, broadcaster=broadcaster)


def get_smells_risk(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> SmellsRiskNode:
    return SmellsRiskNode(audit=audit_service, broadcaster=broadcaster)


def get_confidence_gate(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> ConfidenceGateNode:
    return ConfidenceGateNode(audit=audit_service, broadcaster=broadcaster)


@inject
def get_llm_judge(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    judge_chain: Annotated[
        Runnable[JudgeInput, "JudgeOutput"], Depends(Provide[Container.judge_chain])
    ],
) -> LlmJudgeNode:
    return LlmJudgeNode(
        audit=audit_service, broadcaster=broadcaster, judge_chain=cast("_JudgeChain", judge_chain)
    )


@inject
def get_routing(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    document_storage: Annotated[IDocumentStorage, Depends(Provide[Container.document_storage])],
    classification_record_repo: Annotated[
        IClassificationRecordRepository, Depends(get_classification_record_repo)
    ],
) -> RoutingNode:
    return RoutingNode(
        audit=audit_service,
        broadcaster=broadcaster,
        storage=document_storage,
        classification_repo=classification_record_repo,
    )


def get_classification_coordinator(
    primary_classifier: Annotated[PrimaryClassifierNode, Depends(get_primary_classifier)],
    second_opinion: Annotated[SecondOpinionNode, Depends(get_second_opinion)],
    foreign_municipality: Annotated[ForeignMunicipalityNode, Depends(get_foreign_municipality)],
    smells_risk: Annotated[SmellsRiskNode, Depends(get_smells_risk)],
    confidence_gate: Annotated[ConfidenceGateNode, Depends(get_confidence_gate)],
    llm_judge: Annotated[LlmJudgeNode, Depends(get_llm_judge)],
    routing: Annotated[RoutingNode, Depends(get_routing)],
) -> CompiledStateGraph:  # type: ignore[type-arg]
    return build_classification_coordinator(
        primary_classifier,
        second_opinion,
        foreign_municipality,
        smells_risk,
        confidence_gate,
        llm_judge,
        routing,
    )
```

Update `get_pipeline_service`:

```python
@inject
def get_pipeline_service(
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    document_steps_repo: Annotated[IDocumentStepsRepository, Depends(get_document_steps_repo)],
    enriched_record_repo: Annotated[IEnrichedRecordRepository, Depends(get_enriched_record_repo)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    coordinator: Annotated[CompiledStateGraph, Depends(get_coordinator)],  # type: ignore[type-arg]
    enrichment_coordinator: Annotated[  # type: ignore[type-arg]
        CompiledStateGraph, Depends(get_enrichment_coordinator)
    ],
    document_storage: Annotated[IDocumentStorage, Depends(Provide[Container.document_storage])],
    classification_coordinator: Annotated[  # type: ignore[type-arg]
        CompiledStateGraph, Depends(get_classification_coordinator)
    ],
) -> PipelineService:
    return PipelineService(
        job_repo=job_repo,
        document_steps_repo=document_steps_repo,
        enriched_record_repo=enriched_record_repo,
        broadcaster=broadcaster,
        coordinator=coordinator,
        enrichment_coordinator=enrichment_coordinator,
        document_storage=document_storage,
        classification_coordinator=classification_coordinator,
    )
```

- [x] **Step 8: Wire `TestContainer` (injections/test.py)**

Add imports:

```python
from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.coordinator import build_classification_coordinator
from classiflow.classification.domain.results import JudgeOutput, PrimaryClassificationOutput
from classiflow.classification.nodes import (
    ConfidenceGateNode,
    ForeignMunicipalityNode,
    LlmJudgeNode,
    PrimaryClassifierNode,
    RoutingNode,
    SecondOpinionNode,
    SmellsRiskNode,
)
from classiflow.classification.prompts.llm_judge import JudgeInput, build_judge_chain
from classiflow.classification.prompts.primary_classification import (
    PrimaryClassificationInput,
    build_classification_chain,
)
from classiflow.database.repositories.classification_record import (
    InMemoryClassificationRecordRepository,
)
```

Add near the other test constants:

```python
_TEST_PRIMARY_RESPONSE = '{"label": "ordenanzas", "confidence": 0.95, "reasoning": "test"}'
_TEST_JUDGE_RESPONSE = '{"accept": true, "reasoning": "test"}'
# ponytail: second_opinion disabled in tests -- avoids loading the real ~425MB BETO
# model (weights + OOD/SVM artifacts) on every test run. SecondOpinionNode already
# treats this as a normal, fully-supported config state (returns None).
_TEST_CLASSIFICATION_CONFIG = ClassificationConfig(second_opinion_enabled=False)


def _test_classification_chain() -> Runnable[
    PrimaryClassificationInput, PrimaryClassificationOutput
]:
    return build_classification_chain(MockLlm(response=_TEST_PRIMARY_RESPONSE))


def _test_judge_chain() -> Runnable[JudgeInput, JudgeOutput]:
    return build_judge_chain(MockLlm(response=_TEST_JUDGE_RESPONSE))
```

Add providers inside `TestContainer`, after `entity_extraction_chain`:

```python
    classification_record_repo = providers.Singleton(InMemoryClassificationRecordRepository)
    classification_chain = providers.Singleton(_test_classification_chain)
    judge_chain = providers.Singleton(_test_judge_chain)
```

Add after `enrichment_coordinator`, before `coordinator`:

```python
    classification_primary_classifier = providers.Factory(
        PrimaryClassifierNode,
        audit=audit_service,
        broadcaster=broadcaster,
        classification_chain=classification_chain,
        config=_TEST_CLASSIFICATION_CONFIG,
    )
    classification_second_opinion = providers.Factory(
        SecondOpinionNode,
        audit=audit_service,
        broadcaster=broadcaster,
        config=_TEST_CLASSIFICATION_CONFIG,
    )
    classification_foreign_municipality = providers.Factory(
        ForeignMunicipalityNode,
        audit=audit_service,
        broadcaster=broadcaster,
        config=_TEST_CLASSIFICATION_CONFIG,
    )
    classification_smells_risk = providers.Factory(
        SmellsRiskNode, audit=audit_service, broadcaster=broadcaster, config=_TEST_CLASSIFICATION_CONFIG
    )
    classification_confidence_gate = providers.Factory(
        ConfidenceGateNode,
        audit=audit_service,
        broadcaster=broadcaster,
        config=_TEST_CLASSIFICATION_CONFIG,
    )
    classification_llm_judge = providers.Factory(
        LlmJudgeNode, audit=audit_service, broadcaster=broadcaster, judge_chain=judge_chain
    )
    classification_routing = providers.Factory(
        RoutingNode,
        audit=audit_service,
        broadcaster=broadcaster,
        storage=document_storage,
        classification_repo=classification_record_repo,
    )
    classification_coordinator = providers.Factory(
        build_classification_coordinator,
        primary_classifier=classification_primary_classifier,
        second_opinion=classification_second_opinion,
        foreign_municipality=classification_foreign_municipality,
        smells_risk=classification_smells_risk,
        confidence_gate=classification_confidence_gate,
        llm_judge=classification_llm_judge,
        routing=classification_routing,
    )
```

Update `pipeline_service`:

```python
    pipeline_service = providers.Factory(
        PipelineService,
        job_repo=job_repo,
        document_steps_repo=document_steps_repo,
        enriched_record_repo=enriched_record_repo,
        broadcaster=broadcaster,
        coordinator=coordinator,
        enrichment_coordinator=enrichment_coordinator,
        document_storage=document_storage,
        classification_coordinator=classification_coordinator,
    )
```

- [x] **Step 9: Run test to verify it passes**

Run: `pytest tests/shared/test_pipeline_service_classification.py -v`
Expected: PASS

- [x] **Step 10: Run the full existing test suite (regression check)**

Run: `pytest tests -v`
Expected: PASS across the board, including `tests/api` (the new DI wiring resolves correctly through `get_pipeline_service`).

- [x] **Step 11: Commit**

```bash
git add pyproject.toml src/classiflow/database/repositories/enriched_record.py src/classiflow/services/pipeline/service.py src/classiflow/injections/production.py src/classiflow/injections/test.py src/classiflow/api/dependencies.py tests/shared/test_pipeline_service_classification.py
git commit -m "feat: trigger Stage 4 classification automatically after enrichment"
```

---

## Task 17: Human-review decision API

Spec Decision 9. `GET /classification/review-queue` lists `ClassificationRecord` rows via `list_needing_human_review()` (Task 3). `POST /classification/{job_id}/decision` is guarded on `review_route == "human_review"`, records its own audit entry (via `AuditService`, distinct from `RoutingNode`'s own "classification_routing" audit entry — this one captures who decided and their notes, information `RoutingNode` never sees), then builds a `RoutingInput` from the existing record's already-accumulated fields (confidence, scores, smells, ...) with `label`/`review_route="accept"`/`human_overridden=True` overridden, and calls `RoutingNode.run(...)` directly — reusing Task 14's upsert design, so this second call updates the same row rather than inserting a duplicate. Follows `api/routes/pipeline/endpoints.py`'s exact existing route/DI/auth pattern. `Job.status` is never touched by this endpoint, per Decision 9's closing paragraph — only `ClassificationRecord` changes.

**Files:**
- Create: `src/classiflow/api/routes/classification/__init__.py`
- Create: `src/classiflow/api/routes/classification/schemas.py`
- Create: `src/classiflow/api/routes/classification/endpoints.py`
- Create: `src/classiflow/api/error_handlers/classification.py`
- Modify: `src/classiflow/api/error_handlers/types.py`
- Modify: `src/classiflow/api/routes/registry.py`
- Modify: `tests/api/conftest.py`
- Create: `tests/api/routes/test_classification.py`

**Interfaces:**
- Consumes: `classiflow.classification.exceptions.{ClassificationRecordNotFoundError, ClassificationNotInReviewError}` (Task 4), `classiflow.classification.domain.results.RoutingInput` (Task 14), `classiflow.classification.nodes.routing.RoutingNode` (Task 14), `classiflow.api.dependencies.{get_classification_record_repo, get_routing, get_job_repo, get_audit_service, get_current_user, CurrentUser}` (Task 16 and existing).
- Produces: `ReviewQueueItem(BaseSchema)`, `ClassificationDecisionRequest(BaseSchema)` (`schemas.py`). `GET /classification/review-queue -> list[ReviewQueueItem]`. `POST /classification/{job_id}/decision` (body `ClassificationDecisionRequest`) `-> None`.

- [x] **Step 1: Write the failing test**

Extract `TestContainer()` construction into its own fixture in `tests/api/conftest.py` so this task's tests can seed data directly into the same in-memory repos the `client` fixture wires up (existing `client` fixture body is otherwise unchanged — only the `test_container = TestContainer()` line moves out):

```python
# tests/api/conftest.py -- add near the top of the file
from classiflow.api.dependencies import get_classification_record_repo
from classiflow.domain.repositories.classification_record import IClassificationRecordRepository
from classiflow.injections.test import TestContainer


@pytest.fixture(scope="module")
def test_container() -> TestContainer:
    return TestContainer()


@pytest.fixture(scope="module")
def client(test_container: TestContainer) -> TestClient:
    container = Container()
    container.override(test_container)
    container.wire(packages=["classiflow"])

    allowed = AllowedUser(email=_TEST_EMAIL, is_active=True, is_blocked=False)
    test_container.user_repo().seed(allowed)

    def _job_repo_override() -> IJobRepository:
        return test_container.job_repo()

    def _document_steps_repo_override() -> IDocumentStepsRepository:
        return test_container.document_steps_repo()

    def _human_decision_repo_override() -> IHumanDecisionRepository:
        return test_container.human_decision_repo()

    def _classification_record_repo_override() -> IClassificationRecordRepository:
        return test_container.classification_record_repo()

    def _pipeline_service_override() -> PipelineService:
        return test_container.pipeline_service()

    app = create_app()
    app.dependency_overrides[get_job_repo] = _job_repo_override
    app.dependency_overrides[get_document_steps_repo] = _document_steps_repo_override
    app.dependency_overrides[get_human_decision_repo] = _human_decision_repo_override
    app.dependency_overrides[get_classification_record_repo] = _classification_record_repo_override
    app.dependency_overrides[get_pipeline_service] = _pipeline_service_override

    return TestClient(app)
```

(`test_container = TestContainer()` is removed from inside the old `client` function body — it's now the `test_container` fixture's own return value, injected as a parameter instead.)

```python
# tests/api/routes/test_classification.py
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from classiflow.database.models import ClassificationRecord, Job
from classiflow.injections.test import TestContainer

pytestmark = pytest.mark.usefixtures("_jwt_secret")


async def _seed_human_review_job(test_container: TestContainer, job_id: str, filename: str) -> None:
    await test_container.job_repo().create(Job(job_id=job_id, filename=filename, status="accepted"))
    await test_container.classification_record_repo().save(
        ClassificationRecord(
            job_id=job_id,
            enriched_id=1,
            label="ordenanzas",
            confidence=0.4,
            all_scores={"ordenanzas": 0.4},
            second_opinion_label=None,
            second_opinion_confidence=0.0,
            classifier_disagreement=False,
            ood_metrics=None,
            svm_scores={},
            svm_agrees_with_prediction=True,
            review_route="human_review",
            smells=["low_confidence"],
            risk_score=1,
            smell_review_suggested=False,
            foreign_municipality=None,
            judged_by_llm=False,
            stored_path=None,
            human_overridden=False,
        )
    )
    storage = test_container.document_storage()
    await storage.save_staged(job_id, filename, b"%PDF-1.4 fake bytes")
    await storage.move_to_final(job_id, filename, "review/human_review")


class TestReviewQueueEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/classification/review-queue")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    async def test_lists_records_needing_human_review(
        self, client: TestClient, auth_headers: dict[str, str], test_container: TestContainer
    ) -> None:
        await _seed_human_review_job(test_container, "review-job-001", "doc.pdf")

        response = client.get("/classification/review-queue", headers=auth_headers)
        assert response.status_code == HTTPStatus.OK
        job_ids = [item["jobId"] for item in response.json()]
        assert "review-job-001" in job_ids


class TestClassificationDecisionEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.post("/classification/no-such-job/decision", json={"label": "ordenanzas"})
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unknown_job_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/classification/no-such-job/decision",
            json={"label": "ordenanzas"},
            headers=auth_headers,
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    async def test_record_not_in_review_returns_409(
        self, client: TestClient, auth_headers: dict[str, str], test_container: TestContainer
    ) -> None:
        await _seed_human_review_job(test_container, "already-accepted-001", "doc.pdf")
        repo = test_container.classification_record_repo()
        record = await repo.find_by_job_id("already-accepted-001")
        assert record is not None
        record.review_route = "accept"
        await repo.save(record)

        response = client.post(
            "/classification/already-accepted-001/decision",
            json={"label": "ordenanzas"},
            headers=auth_headers,
        )
        assert response.status_code == HTTPStatus.CONFLICT

    async def test_accepted_decision_moves_file_and_flips_human_overridden(
        self, client: TestClient, auth_headers: dict[str, str], test_container: TestContainer
    ) -> None:
        await _seed_human_review_job(test_container, "decide-me-001", "doc.pdf")

        response = client.post(
            "/classification/decide-me-001/decision",
            json={"label": "decretos", "notes": "reviewed manually"},
            headers=auth_headers,
        )
        assert response.status_code == HTTPStatus.OK

        repo = test_container.classification_record_repo()
        record = await repo.find_by_job_id("decide-me-001")
        assert record is not None
        assert record.label == "decretos"
        assert record.review_route == "accept"
        assert record.human_overridden is True
        assert record.stored_path is not None
        assert "classified/decretos" in record.stored_path

        queue = client.get("/classification/review-queue", headers=auth_headers).json()
        assert "decide-me-001" not in [item["jobId"] for item in queue]
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/routes/test_classification.py -v`
Expected: FAIL with a 404 for `/classification/review-queue` (router doesn't exist yet) once `_jwt_secret`/auth passes.

- [x] **Step 3: Implement `schemas.py`**

```python
# src/classiflow/api/routes/classification/schemas.py
from datetime import datetime

from classiflow.api.schemas import BaseSchema
from classiflow.database.models import ClassificationRecord


class ReviewQueueItem(BaseSchema):
    job_id: str
    label: str | None
    confidence: float
    review_route: str
    smells: list[str]
    risk_score: int
    smell_review_suggested: bool
    foreign_municipality: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, record: ClassificationRecord) -> "ReviewQueueItem":
        return cls(
            job_id=record.job_id,
            label=record.label,
            confidence=record.confidence,
            review_route=record.review_route,
            smells=record.smells,
            risk_score=record.risk_score,
            smell_review_suggested=record.smell_review_suggested,
            foreign_municipality=record.foreign_municipality,
            created_at=record.created_at,
        )


class ClassificationDecisionRequest(BaseSchema):
    label: str
    notes: str | None = None
```

- [x] **Step 4: Implement `endpoints.py`**

```python
# src/classiflow/api/routes/classification/endpoints.py
from typing import Annotated

from fastapi import APIRouter, Depends

from classiflow.api.dependencies import (
    CurrentUser,
    get_audit_service,
    get_classification_record_repo,
    get_current_user,
    get_job_repo,
    get_routing,
)
from classiflow.api.routes.classification.schemas import (
    ClassificationDecisionRequest,
    ReviewQueueItem,
)
from classiflow.classification.domain.results import RoutingInput
from classiflow.classification.exceptions import (
    ClassificationNotInReviewError,
    ClassificationRecordNotFoundError,
)
from classiflow.classification.nodes.routing import RoutingNode
from classiflow.database.repositories.audit import AuditDetail
from classiflow.domain.repositories.classification_record import IClassificationRecordRepository
from classiflow.domain.repositories.job import IJobRepository
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService
from classiflow.services.pipeline.exceptions import JobNotFoundError

router = APIRouter(
    prefix="/classification", tags=["classification"], dependencies=[Depends(get_current_user)]
)

_HUMAN_REVIEW_ROUTE = "human_review"
_ACCEPT_ROUTE = "accept"


@router.get("/review-queue")
async def review_queue(
    classification_repo: Annotated[
        IClassificationRecordRepository, Depends(get_classification_record_repo)
    ],
) -> list[ReviewQueueItem]:
    records = await classification_repo.list_needing_human_review()
    return [ReviewQueueItem.from_model(r) for r in records]


@router.post("/{job_id}/decision")
async def submit_classification_decision(
    job_id: str,
    body: ClassificationDecisionRequest,
    current_user: CurrentUser,
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    classification_repo: Annotated[
        IClassificationRecordRepository, Depends(get_classification_record_repo)
    ],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    routing: Annotated[RoutingNode, Depends(get_routing)],
) -> None:
    record = await classification_repo.find_by_job_id(job_id)
    if record is None:
        raise ClassificationRecordNotFoundError(job_id)
    if record.review_route != _HUMAN_REVIEW_ROUTE:
        raise ClassificationNotInReviewError(job_id, record.review_route)

    job = await job_repo.find_by_job_id(job_id)
    if job is None:
        # Defensive only -- ClassificationRecord.job_id FK (ondelete="CASCADE") means a
        # record can't outlive its Job in practice; this satisfies mypy's None-check on
        # job.filename below without asserting away a real (if unreachable) failure mode.
        raise JobNotFoundError(job_id)

    await audit_service.record(
        job_id,
        "classification_decision",
        "human_decision",
        detail=AuditDetail.model_validate({
            "label": body.label,
            "notes": body.notes,
            "decided_by": current_user.email,
        }),
    )

    routing_input = RoutingInput(
        job_id=job_id,
        filename=job.filename,
        enriched_id=record.enriched_id,
        label=body.label,
        confidence=record.confidence,
        all_scores=record.all_scores,
        second_opinion_label=record.second_opinion_label,
        second_opinion_confidence=record.second_opinion_confidence,
        classifier_disagreement=record.classifier_disagreement,
        ood_metrics=record.ood_metrics,
        svm_scores=record.svm_scores,
        svm_agrees_with_prediction=record.svm_agrees_with_prediction,
        review_route=_ACCEPT_ROUTE,
        smells=record.smells,
        risk_score=record.risk_score,
        smell_review_suggested=record.smell_review_suggested,
        foreign_municipality=record.foreign_municipality,
        judged_by_llm=record.judged_by_llm,
        human_overridden=True,
    )
    ctx = JobContext(job_id=job_id, filename=job.filename)
    await routing.run(ctx, routing_input)
```

```python
# src/classiflow/api/routes/classification/__init__.py
from classiflow.api.routes.classification.endpoints import router

__all__ = ["router"]
```

- [x] **Step 5: Register the error handlers**

```python
# src/classiflow/api/error_handlers/classification.py
from fastapi import Request
from fastapi.responses import JSONResponse

from classiflow.classification.exceptions import (
    ClassificationNotInReviewError,
    ClassificationRecordNotFoundError,
)


def handle_classification_record_not_found_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ClassificationRecordNotFoundError)
    return JSONResponse(status_code=404, content={"detail": str(exc)})


def handle_classification_not_in_review_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ClassificationNotInReviewError)
    return JSONResponse(status_code=409, content={"detail": str(exc)})
```

Update `src/classiflow/api/error_handlers/types.py`:

```python
from classiflow.api.error_handlers.classification import (
    handle_classification_not_in_review_error,
    handle_classification_record_not_found_error,
)
from classiflow.classification.exceptions import (
    ClassificationNotInReviewError,
    ClassificationRecordNotFoundError,
)

EXCEPTION_HANDLERS: dict[type[Exception], ExceptionHandler] = {
    NotAllowedError: handle_not_allowed_error,
    OAuthError: handle_oauth_error,
    AuthError: handle_auth_error,
    ModelNotFoundError: handle_model_not_found,
    ModelLoadError: handle_model_load_error,
    LlmProviderError: handle_llm_provider_error,
    JobNotFoundError: handle_job_not_found_error,
    JobNotInReviewError: handle_job_not_in_review_error,
    ClassificationRecordNotFoundError: handle_classification_record_not_found_error,
    ClassificationNotInReviewError: handle_classification_not_in_review_error,
}
```

(Both new imports added alongside the existing ones at the top of the file -- the rest of `types.py` is unchanged.)

- [x] **Step 6: Register the router**

Update `src/classiflow/api/routes/registry.py`:

```python
from fastapi import APIRouter

from classiflow.api.routes.auth import router as auth_router
from classiflow.api.routes.classification import router as classification_router
from classiflow.api.routes.health import router as health_router
from classiflow.api.routes.pipeline import router as pipeline_router

ROUTERS: list[APIRouter] = [health_router, auth_router, pipeline_router, classification_router]
```

- [x] **Step 7: Run test to verify it passes**

Run: `pytest tests/api/routes/test_classification.py -v`
Expected: PASS

- [x] **Step 8: Run the full existing test suite (regression check on the conftest.py refactor)**

Run: `pytest tests -v`
Expected: PASS across the board — `tests/api/routes/test_pipeline.py` and `tests/api/test_auth.py` are unaffected by the `client`/`test_container` fixture split (same runtime behavior, just constructed one layer apart).

- [x] **Step 9: Commit**

```bash
git add src/classiflow/api/routes/classification/ src/classiflow/api/error_handlers/classification.py src/classiflow/api/error_handlers/types.py src/classiflow/api/routes/registry.py tests/api/conftest.py tests/api/routes/test_classification.py
git commit -m "feat: add human-review decision API for Stage 4 classification"
```

---

## Task 18: T22 — bulk document ingest endpoint

Re-scoped into Stage 4 per spec Decision 3 (`tasks/todo.md` T22, previously `[ ]` pending under Stage 1). `POST /pipeline/ingest-bulk` creates one `Job` row per submitted file immediately and returns `202` + the list of `job_id`s, matching `POST /pipeline/ingest`'s "don't block the response" contract. A new `Settings.MAX_CONCURRENT_JOBS`-bounded `asyncio.Semaphore` gates actual coordinator execution for **both** bulk and single-file jobs (T22's own acceptance criteria: "goes through a bounded asyncio.Semaphore ... for consistency") — it needs no staging-specific logic of its own, since Task 2 already put `save_staged` inside the shared `_run()` path both endpoints call through.

**Files:**
- Modify: `src/classiflow/settings.py`
- Modify: `pyproject.toml`
- Modify: `src/classiflow/services/pipeline/service.py`
- Modify: `src/classiflow/injections/production.py`
- Modify: `src/classiflow/injections/test.py`
- Modify: `src/classiflow/api/dependencies.py`
- Modify: `src/classiflow/api/routes/pipeline/endpoints.py`
- Modify: `src/classiflow/api/routes/pipeline/schemas.py`
- Create: `tests/shared/test_pipeline_service_concurrency.py`
- Modify: `tests/api/routes/test_pipeline.py`

**Interfaces:**
- Consumes: nothing new from earlier tasks in this plan — this task only touches Stage 1's own `PipelineService`/pipeline endpoints, reusing Task 2's staging call already in `_run()`.
- Produces: `Settings.max_concurrent_jobs`. `PipelineService.__init__(..., job_semaphore: asyncio.Semaphore)` (9th param). `BulkIngestResponse(BaseSchema)` (`job_ids: list[str]`). `POST /pipeline/ingest-bulk -> BulkIngestResponse`.

- [x] **Step 1: Write the failing concurrency-cap test**

```python
# tests/shared/test_pipeline_service_concurrency.py
import asyncio
from typing import cast

from langgraph.graph.state import CompiledStateGraph

from classiflow.database.repositories.document_steps import InMemoryDocumentStepsRepository
from classiflow.database.repositories.enriched_record import InMemoryEnrichedRecordRepository
from classiflow.database.repositories.job import InMemoryJobRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.services.pipeline.service import PipelineService
from classiflow.storage.document_storage import IDocumentStorage


class _ConcurrencyTrackingCoordinator:
    def __init__(self, sleep_seconds: float) -> None:
        self._sleep_seconds = sleep_seconds
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = asyncio.Lock()

    async def ainvoke(self, state: dict[str, object]) -> dict[str, object]:
        async with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(self._sleep_seconds)
        async with self._lock:
            self.in_flight -= 1
        return {
            "job_id": state["job_id"],
            "filename": state["filename"],
            "final_status": "rejected",
            "rejection_reason": "test",
        }


class TestPipelineServiceConcurrencyCap:
    async def test_semaphore_caps_concurrent_coordinator_runs(self) -> None:
        coordinator = _ConcurrencyTrackingCoordinator(sleep_seconds=0.05)
        service = PipelineService(
            job_repo=InMemoryJobRepository(),
            document_steps_repo=InMemoryDocumentStepsRepository(),
            enriched_record_repo=InMemoryEnrichedRecordRepository(),
            broadcaster=EventBroadcaster(),
            coordinator=cast("CompiledStateGraph", coordinator),
            enrichment_coordinator=cast(
                "CompiledStateGraph", None
            ),  # unused: final_status != accepted
            document_storage=cast("IDocumentStorage", None),  # unused: extraction key absent
            classification_coordinator=cast("CompiledStateGraph", None),  # unused: not accepted
            job_semaphore=asyncio.Semaphore(2),
        )
        await asyncio.gather(*[service._run(f"job-{i}", "doc.pdf", b"x") for i in range(5)])
        assert coordinator.max_in_flight <= 2
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/shared/test_pipeline_service_concurrency.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'job_semaphore'`

- [x] **Step 3: Add `Settings.MAX_CONCURRENT_JOBS`**

In `src/classiflow/settings.py`, add after `JUDGE_MODEL_PATH`:

```python
    MAX_CONCURRENT_JOBS: int = int(os.getenv("MAX_CONCURRENT_JOBS", "8"))
```

and add after the `judge_model_path` property:

```python
    @property
    def max_concurrent_jobs(self) -> int:
        return self.MAX_CONCURRENT_JOBS
```

- [x] **Step 4: Bump `max-args` from 8 to 9**

`PipelineService.__init__` and `get_pipeline_service` both grow to 9 params with `job_semaphore` added. In `pyproject.toml`, bump both occurrences from Task 16's Step 4 to `9`, updating the comment's collaborator list to add `job_semaphore`:

```toml
[tool.ruff.lint.pylint]
# Mirrors [tool.pylint.design] max-args below -- FastAPI's Depends()-per-dependency
# style, and PipelineService's own growing set of injected collaborators (job_repo,
# document_steps_repo, enriched_record_repo, broadcaster, coordinator,
# enrichment_coordinator, document_storage, classification_coordinator,
# job_semaphore), mean DI-composing functions/classes legitimately grow one param per
# wired collaborator.
max-args = 9
```

```toml
[tool.pylint.design]
max-args = 9
```

- [x] **Step 5: Update `PipelineService`**

In `src/classiflow/services/pipeline/service.py`, update imports:

```python
import asyncio
```

Update `__init__` and wrap `_run`'s body in the semaphore:

```python
class PipelineService:
    def __init__(
        self,
        job_repo: IJobRepository,
        document_steps_repo: IDocumentStepsRepository,
        enriched_record_repo: IEnrichedRecordRepository,
        broadcaster: EventBroadcaster,
        coordinator: CompiledStateGraph,  # type: ignore[type-arg]
        enrichment_coordinator: CompiledStateGraph,  # type: ignore[type-arg]
        document_storage: IDocumentStorage,
        classification_coordinator: CompiledStateGraph,  # type: ignore[type-arg]
        job_semaphore: asyncio.Semaphore,
    ) -> None:
        self._job_repo = job_repo
        self._document_steps_repo = document_steps_repo
        self._enriched_record_repo = enriched_record_repo
        self._broadcaster = broadcaster
        self._coordinator = coordinator
        self._enrichment_coordinator = enrichment_coordinator
        self._document_storage = document_storage
        self._classification_coordinator = classification_coordinator
        self._job_semaphore = job_semaphore

    async def _run(self, job_id: str, filename: str, file_bytes: bytes) -> None:
        async with self._job_semaphore:
            initial: JobState = {"job_id": job_id, "filename": filename, "file_bytes": file_bytes}
            final_state = cast("JobState", await self._coordinator.ainvoke(initial))

            failed_at_node = await self._persist_steps(job_id, final_state)
            await self._finalize_job(job_id, final_state, failed_at_node)

            if final_state.get("extraction") is not None:
                await self._document_storage.save_staged(job_id, filename, file_bytes)

            if final_state.get("final_status") == "accepted":
                enriched_record = await self._run_enrichment(job_id, filename, final_state)
                if enriched_record is not None:
                    await self._run_classification(job_id, filename, enriched_record)

            unload_slm()

            await self._broadcaster.emit(
                NodeEvent(job_id=job_id, node=_PIPELINE_NODE, status=JobStatus.DONE)
            )
```

(`start()` is unchanged — it still just creates the `Job` row and schedules `_run` as a background task; the semaphore throttles how many `_run()` bodies actually execute concurrently once FastAPI's background-task runner starts them, not how many get scheduled.)

- [x] **Step 6: Run test to verify it passes**

Run: `pytest tests/shared/test_pipeline_service_concurrency.py -v`
Expected: PASS

- [x] **Step 7: Wire `job_semaphore` into `Container` (production.py)**

Add a module-level function directly after the existing `_extraction_concurrency_limit`, matching its exact shape:

```python
def _job_concurrency_limit() -> int:
    return Settings.max_concurrent_jobs
```

Add inside `Container`, after `extraction_semaphore`:

```python
    job_semaphore = providers.Singleton(asyncio.Semaphore, providers.Callable(_job_concurrency_limit))
```

- [x] **Step 8: Wire `job_semaphore` into `TestContainer` (injections/test.py)**

Add inside `TestContainer`, after `extraction_semaphore`:

```python
    # Generous cap -- shouldn't gate tests, just needs to satisfy the now-required param.
    job_semaphore = providers.Singleton(asyncio.Semaphore, 100)
```

Update `pipeline_service`:

```python
    pipeline_service = providers.Factory(
        PipelineService,
        job_repo=job_repo,
        document_steps_repo=document_steps_repo,
        enriched_record_repo=enriched_record_repo,
        broadcaster=broadcaster,
        coordinator=coordinator,
        enrichment_coordinator=enrichment_coordinator,
        document_storage=document_storage,
        classification_coordinator=classification_coordinator,
        job_semaphore=job_semaphore,
    )
```

- [x] **Step 9: Wire `job_semaphore` into `api/dependencies.py`'s `get_pipeline_service`**

```python
@inject
def get_pipeline_service(
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    document_steps_repo: Annotated[IDocumentStepsRepository, Depends(get_document_steps_repo)],
    enriched_record_repo: Annotated[IEnrichedRecordRepository, Depends(get_enriched_record_repo)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    coordinator: Annotated[CompiledStateGraph, Depends(get_coordinator)],  # type: ignore[type-arg]
    enrichment_coordinator: Annotated[  # type: ignore[type-arg]
        CompiledStateGraph, Depends(get_enrichment_coordinator)
    ],
    document_storage: Annotated[IDocumentStorage, Depends(Provide[Container.document_storage])],
    classification_coordinator: Annotated[  # type: ignore[type-arg]
        CompiledStateGraph, Depends(get_classification_coordinator)
    ],
    job_semaphore: Annotated[asyncio.Semaphore, Depends(Provide[Container.job_semaphore])],
) -> PipelineService:
    return PipelineService(
        job_repo=job_repo,
        document_steps_repo=document_steps_repo,
        enriched_record_repo=enriched_record_repo,
        broadcaster=broadcaster,
        coordinator=coordinator,
        enrichment_coordinator=enrichment_coordinator,
        document_storage=document_storage,
        classification_coordinator=classification_coordinator,
        job_semaphore=job_semaphore,
    )
```

- [x] **Step 10: Write the failing endpoint test**

Add to `tests/api/routes/test_pipeline.py`:

```python
class TestBulkIngestEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.post(
            "/pipeline/ingest-bulk", files=[("files", ("a.pdf", _MINIMAL_PDF, "application/pdf"))]
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_returns_one_job_id_per_file(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_NODE3_GET_LLM, lambda _path: MockLlm(response=_SLM_LEGITIMATE))
        files = [
            ("files", ("bulk-a.pdf", _MINIMAL_PDF, "application/pdf")),
            ("files", ("bulk-b.pdf", _MINIMAL_PDF, "application/pdf")),
            ("files", ("bulk-c.pdf", _MINIMAL_PDF, "application/pdf")),
        ]
        response = client.post("/pipeline/ingest-bulk", files=files, headers=auth_headers)
        assert response.status_code == HTTPStatus.ACCEPTED
        job_ids = response.json()["jobIds"]
        assert len(job_ids) == len(files)
        assert len(set(job_ids)) == len(files)  # no duplicate job_ids
```

- [x] **Step 11: Run test to verify it fails**

Run: `pytest tests/api/routes/test_pipeline.py -k BulkIngest -v`
Expected: FAIL with a 404 (`/pipeline/ingest-bulk` doesn't exist yet)

- [x] **Step 12: Implement the endpoint**

Add to `src/classiflow/api/routes/pipeline/schemas.py`:

```python
class BulkIngestResponse(BaseSchema):
    job_ids: list[str]
```

Add to `src/classiflow/api/routes/pipeline/endpoints.py` (update the `schemas` import to include `BulkIngestResponse`):

```python
@router.post("/ingest-bulk", status_code=202)
async def ingest_bulk(
    files: list[UploadFile],
    background_tasks: BackgroundTasks,
    pipeline: Annotated[PipelineService, Depends(get_pipeline_service)],
) -> BulkIngestResponse:
    job_ids = []
    for file in files:
        filename = file.filename or "unknown"
        file_bytes = await file.read()
        job_ids.append(await pipeline.start(background_tasks, filename, file_bytes))
    return BulkIngestResponse(job_ids=job_ids)
```

- [x] **Step 13: Run test to verify it passes**

Run: `pytest tests/api/routes/test_pipeline.py -k BulkIngest -v`
Expected: PASS

- [x] **Step 14: Run the full existing test suite (final regression check)**

Run: `pytest tests -v`
Expected: PASS across the board.

- [x] **Step 15: Commit**

```bash
git add src/classiflow/settings.py pyproject.toml src/classiflow/services/pipeline/service.py src/classiflow/injections/production.py src/classiflow/injections/test.py src/classiflow/api/dependencies.py src/classiflow/api/routes/pipeline/endpoints.py src/classiflow/api/routes/pipeline/schemas.py tests/shared/test_pipeline_service_concurrency.py tests/api/routes/test_pipeline.py
git commit -m "feat: add bounded-concurrency bulk document ingest endpoint (T22)"
```

---

## Self-Review

**Spec coverage** — every decision in `docs/superpowers/specs/2026-08-18-classification-routing-design.md` maps to a task:

| Spec item | Task(s) |
|---|---|
| Decision 1 — `IDocumentStorage` / `LocalDiskStorage` | 1 |
| Decision 2 — stage bytes in `_run()` | 2 |
| Decision 3 — T22 re-scoped in | 18 |
| Decision 4 — Primary Classification Agent | 5 |
| Decision 5 — Second Opinion (BERT spec), Foreign Municipality, Smells/Risk, Confidence Gate, `"llm_judge"` never persisted | 6–9, 10, 11, 12, 14 |
| Decision 6 — LLM Judge, no tool-use | 13 |
| Decision 7 — Gemma 4 swap via `Settings.*_MODEL_PATH` | 4, 5, 13 (config fields only — no code gate needed, confirmed no other action required) |
| Decision 8 — Routing Agent, two terminal destinations | 14 |
| Decision 9 — human-review queue + decision endpoint, `Job.status` untouched | 17 |
| Decision 10 — automatic chaining, `_run_enrichment` returns `EnrichedRecord \| None` | 2, 16 |
| `ClassificationRecord` field list (BERT spec + this spec's 3 additions) | 3 |
| File layout (`storage/`, `classification/{config,exceptions,domain,bert,prompts,nodes,coordinator}`) | 1, 3–15 |
| `config/classification.yaml` / `Settings` additions | 1, 4, 18 |
| `.gitignore` — `storage/documents/**` | 1 |
| Testing section (per-node unit tests, `TestLocalDiskStorage`, coordinator-level accept/human_review + follow-up decision test, `PipelineService._run()` integration test incl. negative staging case) | 1, 5, 10–15, 16, 17 |

**Gap found and fixed during this pass**: the spec's Testing section explicitly asks for proof that "a job that fails Stage 1-3 validation never gets staged" — the original Task 2 draft only covered the positive (staged) case. Added `TestPipelineServiceStaging.test_job_rejected_before_extraction_is_never_staged` using a fake pre-extraction-rejecting coordinator, isolated from the real 4-node coordinator's own content-sniffing internals.

**Design gap found and resolved**: Decision 1's `move_to_final` (as originally drafted in Task 1) assumed the source file is always still in `staging/`. Decision 9's human-review → accept flow calls `move_to_final` a **second** time on a file Routing already moved to `review/human_review/` once — the file is no longer in `staging/` by then. Fixed `LocalDiskStorage._move_to_final_sync` (Task 1) to locate the file via a glob across the whole storage root rather than a fixed `staging/` path, and added a regression test for the two-hop case. This also confirmed the design decision written into Task 14: `RoutingNode.run()` performs an upsert of `ClassificationRecord` (find-or-create, not always-insert), reconciling Decision 8's constructor signature (`classification_repo` present but unused in the spec's own illustrative `run()` body) with Decision 9's two call sites needing to update the same row.

**Placeholder scan**: searched for `TBD`, `TODO`, bare `...` outside legitimate Protocol/exception stub bodies and prose, `"similar to Task N"` without inline code, and generic "add error handling" phrasing. None found in code steps; every code block is complete, runnable, and copy-pasteable. One spot (Task 2) originally used `...` to mean "unchanged code" inside a Python code block — rewritten to show the complete function bodies instead, since the exact current file contents were already known from reading the real repo.

**Type/signature consistency**, spot-checked across all 18 tasks:
- `IDocumentStorage.{save_staged, move_to_final}` argument order (`job_id, filename, ...`) is identical at every call site (Tasks 1, 2, 9, 14, 17, 18).
- `ClassificationState`'s required fields (`job_id`, `filename`, `cleaned_text`, `enriched_id`) match every literal construction site (Tasks 15, 16) — `enriched_id` was missing from the initial Task 4 draft and added during this review, since Task 14's `RoutingInput`/Task 3's `ClassificationRecord.enriched_id` FK both need it from the start of the coordinator run.
- `ClassificationUpdate`'s optional fields are an exact 1:1 match with `ClassificationState`'s optional fields.
- `RoutingInput`'s 18 fields match `ClassificationRecord`'s persisted columns (minus `id`/`created_at`, both DB/auto-managed) and are constructed identically (by field name) in both call sites (Task 15's coordinator closure, Task 17's endpoint).
- `PrimaryClassificationOutput`, `SecondOpinionResult`, `OodMetrics`, `SmellsRiskResult`, `JudgeOutput`, `RoutingResult` field names are consistent between their `domain/results.py` definitions (Tasks 4, 7, 8, 11) and every node/coordinator that reads them (Tasks 5, 9, 11, 13, 15).
- `PipelineService.__init__`'s growing parameter list (7 → 8 → 9 across Tasks 2, 16, 18) and the matching `max-args` bumps in `pyproject.toml` stay in lockstep with `get_pipeline_service`'s own signature at each step.
- `classifier_disagreement(primary_label, second_opinion_label)`'s positional argument order (Task 8) matches its one call site (Task 15).

**Open items carried forward (not solved by this plan, noted for whoever picks them up next)**:
- No retry-then-review fallback for classification failures, unlike Stage 3's enrichment retry loop — neither spec describes one; a raised `ClassificationError` propagates out of the background task uncaught (Task 16's `_run_classification` docstring-comment flags this explicitly).
- `low_svm_margin` (Task 11) reuses the Second Opinion Agent's own `svm_agrees_with_prediction` boolean rather than a numeric SVM-margin threshold, since neither spec pins a concrete value for this smell.
- `unreadable_document` (Task 11) is redefined as "empty `cleaned_text` after Stage 3 cleaning," since `plan_stage4.md`'s literal trigger ("Stage 2 returned `text=None`") can no longer occur by the time this coordinator runs (Stage 4 only starts after a *successful* enrichment).
- All five risks already listed in the spec's own "Open items / risks" table (orphaned staged files, unbounded `storage/documents/` growth, `LocalDiskStorage`-only seam, Docker persistent-volume need, Gemma 4/`llama-cpp-python` compatibility drift) are unchanged by this plan and still apply.
