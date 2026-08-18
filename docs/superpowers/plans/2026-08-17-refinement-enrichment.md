# Stage 3 (Refinement & Enrichment) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn every accepted document's raw extracted text into a cleaned, entity-annotated, metadata-enriched `EnrichedRecord` — the exact input Stage 5 (RAG) will embed — automatically and durably, with a bounded retry-then-review fallback when the LLM step fails.

**Architecture:** A new top-level `classiflow/enrichment/` package (mirroring `ingesta/`'s shape) with a 3-node linear LangGraph coordinator (clean → extract entities → enrich metadata). `PipelineService._run()` invokes it automatically right after a job is accepted, passing `final_state["text"]` in memory — no DB re-fetch. `BaseNode` and `JobContext` (currently `ingesta`-owned but genuinely generic) relocate to a new neutral `classiflow/pipeline/` package first, since both `ingesta` and `enrichment` need them without either owning the other.

**Tech Stack:** LangGraph (`StateGraph`), LangChain (`Runnable`/`RunnableLambda`/`StrOutputParser`), Pydantic (`BaseEntity`), SQLAlchemy 2.0 async + Alembic, `dependency_injector`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-17-refinement-enrichment-design.md`

## Global Constraints

- Line length 100, double-quote strings (ruff-enforced).
- mypy strict: never use `Any`. Never use `from __future__ import annotations` — quote forward references (`"MyType"`) instead. Never use `TYPE_CHECKING` unless avoiding a real circular import — the one narrow precedent already in this codebase (`api/dependencies.py`'s `_FormatChain`/`_ContentChain` under `TYPE_CHECKING`) is followed exactly once more for `_EntityChain` in Task 11; introduce no other `TYPE_CHECKING` blocks.
- Domain/value objects (data crossing layers) → `BaseEntity` (`classiflow/domain/base.py`), never plain `BaseModel`. Services/nodes/repositories (hold dependencies or mutable state) → plain `__init__`.
- Exceptions: each service gets its own `exceptions.py` — a plain base class (`class XError(Exception): ...`) plus `@dataclass` subclasses that call `super().__init__(str(self))` in `__post_init__` and define `__str__`. Never raise the base directly; never use bare `except Exception`.
- `__init__.py` files contain only `__version__`, re-exports, and `__all__` — no executable statements.
- `uv run poe check` is the project's single verification gate. **Do not run it yourself** (or any notebook/benchmark command) — hand the exact command to the user and wait, per this project's standing convention. Plain `pytest tests/path::test -v` runs during the test-first loop within a task are fine to run directly.
- Git: never `git add`, `git commit`, `git push`, or open a PR without the user's explicit go-ahead in that message.
- All comments/docstrings/commit messages in English.

---

## Task 1: Relocate `BaseNode` and `JobContext` to a new `classiflow/pipeline/` package

Both are currently `ingesta`-owned but contain nothing ingestion-specific: `BaseNode` only wraps `AuditService`/`EventBroadcaster` into `_emit_started`/`_emit_and_audit`, and `JobContext` is just `{job_id, filename}`. `enrichment/` needs both without depending on `ingesta`, so they move to neutral ground first. This was already called for in the Stage 4 (bert_tunning) design spec but never executed — this task finally does it.

**Files:**
- Create: `src/classiflow/pipeline/__init__.py`
- Create: `src/classiflow/pipeline/base.py`
- Create: `src/classiflow/pipeline/context.py`
- Delete: `src/classiflow/ingesta/nodes/base.py`
- Delete: `src/classiflow/ingesta/domain/context.py`
- Modify: `src/classiflow/ingesta/domain/__init__.py`
- Modify: `src/classiflow/ingesta/nodes/__init__.py`
- Modify: `src/classiflow/ingesta/nodes/extraction_step.py`
- Modify: `src/classiflow/ingesta/nodes/node1_file_reception.py`
- Modify: `src/classiflow/ingesta/nodes/node2_format_validation.py`
- Modify: `src/classiflow/ingesta/nodes/node3_content_validation.py`
- Modify: `src/classiflow/ingesta/nodes/node4_duplicate_control.py`

**Interfaces:**
- Produces: `classiflow.pipeline.base.BaseNode` (unchanged API: `__init__(audit, broadcaster)`, `name` abstract property, `_emit_started(ctx) -> float`, `_emit_and_audit(ctx, start, *, passed, detail) -> None`). `classiflow.pipeline.context.JobContext` (unchanged: `BaseEntity`, frozen, `job_id: str`, `filename: str`).
- Consumes: nothing new — pure relocation of existing code.

- [ ] **Step 1: Confirm no caller bypasses the package-level re-export**

Run: `git grep -n "ingesta.domain.context\|ingesta.nodes.base" -- '*.py'`
Expected: only `src/classiflow/ingesta/domain/__init__.py` and `src/classiflow/ingesta/nodes/__init__.py` (and the files listed above) reference these module paths directly. If anything else does, add it to the Modify list before continuing.

- [ ] **Step 2: Create the `pipeline` package**

```python
# src/classiflow/pipeline/__init__.py
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext

__all__ = ["BaseNode", "JobContext"]
```

```python
# src/classiflow/pipeline/context.py
from pydantic import ConfigDict
from pydantic.alias_generators import to_camel

from classiflow.domain.base import BaseEntity


class JobContext(BaseEntity):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        frozen=True,
    )
    job_id: str
    filename: str
```

```python
# src/classiflow/pipeline/base.py
import time
from abc import abstractmethod

from classiflow.database.repositories.audit import AuditDetail
from classiflow.domain.job import JobStatus, NodeEvent
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService


class BaseNode:
    # Subclasses: if run() does a blocking, CPU-bound call (SLM invocation, embedding
    # computation, OCR, ...), wrap it in `await asyncio.to_thread(...)`. run() is a
    # coroutine that the coordinator awaits directly on the event loop — unlike a plain
    # sync node function, which LangGraph itself auto-dispatches to a thread — so a bare
    # blocking call here freezes every other concurrent request (other jobs, health
    # checks, open SSE streams) for its duration. See node2/node3's SLM calls and
    # node4's embedding calls for the pattern.
    def __init__(self, audit: AuditService, broadcaster: EventBroadcaster) -> None:
        self.audit = audit
        self.broadcaster = broadcaster

    @property
    @abstractmethod
    def name(self) -> str: ...

    async def _emit_started(self, ctx: JobContext) -> float:
        await self.broadcaster.emit(
            NodeEvent(job_id=ctx.job_id, node=self.name, status=JobStatus.STARTED)
        )
        return time.monotonic()

    async def _emit_and_audit(
        self,
        ctx: JobContext,
        start: float,
        *,
        passed: bool,
        detail: AuditDetail,
    ) -> None:
        duration_ms = int((time.monotonic() - start) * 1000)
        status = JobStatus.PASSED if passed else JobStatus.FAILED
        await self.broadcaster.emit(NodeEvent(job_id=ctx.job_id, node=self.name, status=status))
        await self.audit.record(
            ctx.job_id, self.name, status.value, duration_ms=duration_ms, detail=detail
        )
```

- [ ] **Step 3: Delete the old files**

```bash
rm src/classiflow/ingesta/nodes/base.py
rm src/classiflow/ingesta/domain/context.py
```

- [ ] **Step 4: Update `ingesta/domain/__init__.py`'s import**

```python
# src/classiflow/ingesta/domain/__init__.py
from classiflow.domain.base import BaseEntity
from classiflow.pipeline.context import JobContext

from .results import (
    ContentValidationResult,
    DuplicateControlResult,
    ExtractionResult,
    FileReceptionResult,
    FormatDecision,
    FormatValidationResult,
)
from .state import JobState, NodeUpdate

__all__ = [
    "BaseEntity",
    "ContentValidationResult",
    "DuplicateControlResult",
    "ExtractionResult",
    "FileReceptionResult",
    "FormatDecision",
    "FormatValidationResult",
    "JobContext",
    "JobState",
    "NodeUpdate",
]
```

(Only the `.context import JobContext` line changes to `from classiflow.pipeline.context import JobContext`, moved above the relative imports; everything else is unchanged. This keeps `from classiflow.ingesta.domain import JobContext` working for all 35 existing callers.)

- [ ] **Step 5: Update `ingesta/nodes/__init__.py`'s import**

```python
# src/classiflow/ingesta/nodes/__init__.py
from classiflow.ingesta.mime import MimeDetector
from classiflow.ingesta.nodes.extraction_step import ExtractionStep
from classiflow.ingesta.nodes.node1_file_reception import FileReceptionNode
from classiflow.ingesta.nodes.node2_format_validation import FormatValidationNode
from classiflow.ingesta.nodes.node3_content_validation import ContentValidationNode
from classiflow.ingesta.nodes.node4_duplicate_control import DuplicateControlNode
from classiflow.pipeline.base import BaseNode

__all__ = [
    "BaseNode",
    "ContentValidationNode",
    "DuplicateControlNode",
    "ExtractionStep",
    "FileReceptionNode",
    "FormatValidationNode",
    "MimeDetector",
]
```

- [ ] **Step 6: Update the 5 node files' `BaseNode` import**

In each of `extraction_step.py`, `node1_file_reception.py`, `node2_format_validation.py`, `node3_content_validation.py`, `node4_duplicate_control.py`, change:

```python
from classiflow.ingesta.nodes.base import BaseNode
```
to:
```python
from classiflow.pipeline.base import BaseNode
```

No other line in any of these 5 files changes.

- [ ] **Step 7: Run the full existing test suite to confirm the relocation is behavior-preserving**

Run: `pytest tests/ingesta -v`
Expected: PASS — same tests, same results as before this task; only import paths changed.

- [ ] **Step 8: Commit**

```bash
git add src/classiflow/pipeline/ src/classiflow/ingesta/nodes/ src/classiflow/ingesta/domain/__init__.py
git commit -m "refactor: relocate BaseNode and JobContext to new pipeline package"
```

---

## Task 2: Relocate `config_loader.py` to `classiflow/config_loader.py`

`load_yaml_config()` is generic YAML→pydantic loading, not ingestion-specific. `enrichment/config_enrichment.py` (Task 3) needs it without depending on `ingesta`.

**Files:**
- Create: `src/classiflow/config_loader.py`
- Delete: `src/classiflow/ingesta/config_loader.py`
- Modify: `src/classiflow/ingesta/config.py`
- Modify: `src/classiflow/ingesta/config_content.py`
- Modify: `src/classiflow/ingesta/config_duplicate.py`
- Modify: `src/classiflow/ingesta/config_extraction.py`

**Interfaces:**
- Produces: `classiflow.config_loader.load_yaml_config(path: Path, model: type[T]) -> T` (unchanged signature/body — pure relocation).
- Consumes: nothing new.

- [ ] **Step 1: Read the current file to copy verbatim**

Run: `cat src/classiflow/ingesta/config_loader.py` (or read it) — copy its exact contents into the new location; do not change its logic.

- [ ] **Step 2: Move the file**

```bash
git mv src/classiflow/ingesta/config_loader.py src/classiflow/config_loader.py
```

- [ ] **Step 3: Update the 4 importers**

In each of `ingesta/config.py`, `ingesta/config_content.py`, `ingesta/config_duplicate.py`, `ingesta/config_extraction.py`, change:

```python
from classiflow.ingesta.config_loader import load_yaml_config
```
to:
```python
from classiflow.config_loader import load_yaml_config
```

- [ ] **Step 4: Run the full existing test suite**

Run: `pytest tests/ingesta -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/classiflow/config_loader.py src/classiflow/ingesta/config.py src/classiflow/ingesta/config_content.py src/classiflow/ingesta/config_duplicate.py src/classiflow/ingesta/config_extraction.py
git commit -m "refactor: relocate config_loader.py to classiflow.config_loader"
```

---

## Task 3: Settings additions + `config/enrichment.yaml` + `EnrichmentConfig`

**Files:**
- Create: `config/enrichment.yaml`
- Create: `src/classiflow/enrichment/__init__.py`
- Create: `src/classiflow/enrichment/config_enrichment.py`
- Create: `tests/enrichment/__init__.py`
- Create: `tests/enrichment/test_config_enrichment.py`
- Modify: `src/classiflow/settings.py`

**Interfaces:**
- Consumes: `classiflow.config_loader.load_yaml_config` (Task 2).
- Produces: `classiflow.enrichment.config_enrichment.EnrichmentConfig` (fields: `repeated_line_min_count: int = 3`, `max_enrichment_retries: int = 2`), `get_enrichment_config() -> EnrichmentConfig` (`@lru_cache(maxsize=1)`). `Settings.enrichment_model_path: str`, `Settings.enrichment_config_path: str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/enrichment/test_config_enrichment.py
from classiflow.enrichment.config_enrichment import EnrichmentConfig, get_enrichment_config


class TestEnrichmentConfig:
    def test_defaults(self) -> None:
        config = EnrichmentConfig()
        assert config.repeated_line_min_count == 3
        assert config.max_enrichment_retries == 2

    def test_get_enrichment_config_loads_real_yaml(self) -> None:
        config = get_enrichment_config()
        assert isinstance(config, EnrichmentConfig)
        assert config.repeated_line_min_count >= 1
        assert config.max_enrichment_retries >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/enrichment/test_config_enrichment.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.enrichment'`

- [ ] **Step 3: Add Settings fields**

In `src/classiflow/settings.py`, add after `EXTRACTION_CONFIG_PATH`:

```python
    ENRICHMENT_MODEL_PATH: str = _DEFAULT_MODEL
    ENRICHMENT_CONFIG_PATH: str = str(_PROJECT_ROOT / "config" / "enrichment.yaml")
```

and add after the `extraction_config_path` property:

```python
    @property
    def enrichment_model_path(self) -> str:
        return self.ENRICHMENT_MODEL_PATH

    @property
    def enrichment_config_path(self) -> str:
        return self.ENRICHMENT_CONFIG_PATH
```

- [ ] **Step 4: Create `config/enrichment.yaml`**

```yaml
# Stage 3 (Refinement & Enrichment) thresholds.
# enrichment/nodes/text_cleaner.py and PipelineService's retry-then-review
# enrichment trigger use this config.

# A line appearing this many times or more across the document is treated as a
# running header/footer and stripped.
repeated_line_min_count: 3

# How many times the enrichment coordinator retries after a failure (e.g. the
# entity-extraction LLM call erroring) before the job is marked for review.
max_enrichment_retries: 2
```

- [ ] **Step 5: Create the `enrichment` package and config module**

```python
# src/classiflow/enrichment/__init__.py
```
(empty for now — populated with re-exports as later tasks add symbols)

```python
# tests/enrichment/__init__.py
```
(empty, mirrors `tests/ingesta/__init__.py`'s existence as a package marker)

```python
# src/classiflow/enrichment/config_enrichment.py
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from classiflow.config_loader import load_yaml_config
from classiflow.settings import Settings


class EnrichmentConfig(BaseModel):
    repeated_line_min_count: int = 3
    max_enrichment_retries: int = 2


@lru_cache(maxsize=1)
def get_enrichment_config() -> EnrichmentConfig:
    return load_yaml_config(Path(Settings.enrichment_config_path), EnrichmentConfig)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/enrichment/test_config_enrichment.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add config/enrichment.yaml src/classiflow/settings.py src/classiflow/enrichment/ tests/enrichment/
git commit -m "feat: add enrichment settings and config/enrichment.yaml"
```

---

## Task 4: Enrichment domain models and exceptions

**Files:**
- Create: `src/classiflow/enrichment/domain/__init__.py`
- Create: `src/classiflow/enrichment/domain/results.py`
- Create: `src/classiflow/enrichment/domain/state.py`
- Create: `src/classiflow/enrichment/exceptions.py`
- Create: `tests/enrichment/test_domain.py`

**Interfaces:**
- Consumes: `classiflow.domain.base.BaseEntity`.
- Produces: `TextCleaningResult(cleaned_text: str = "")`, `EntityExtractionResult(doc_type_hint, number, year, issuing_body, signatories, article_count)`, `MetadataEnrichmentResult(source, filename, language, sha256, stage2_extractor_used)` — all `BaseEntity`, all fields optional/defaulted. `EnrichmentState` (`TypedDict`, required: `job_id`, `filename`, `text`, `language`, `sha256`, `stage2_extractor_used`; optional: `cleaned_text`, `cleaning`, `entities`, `metadata`). `EnrichmentUpdate` (`BaseEntity`, same optional fields as `EnrichmentState`'s `total=False` part). `EnrichmentError(Exception)` base, `EntityExtractionFailedError(EnrichmentError)` dataclass with `reason: str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/enrichment/test_domain.py
import pytest

from classiflow.enrichment.domain.results import (
    EntityExtractionResult,
    MetadataEnrichmentResult,
    TextCleaningResult,
)
from classiflow.enrichment.domain.state import EnrichmentUpdate
from classiflow.enrichment.exceptions import EntityExtractionFailedError


class TestResultDefaults:
    def test_text_cleaning_result_defaults(self) -> None:
        assert TextCleaningResult().cleaned_text == ""

    def test_entity_extraction_result_defaults(self) -> None:
        result = EntityExtractionResult()
        assert result.doc_type_hint is None
        assert result.signatories == []
        assert result.article_count is None

    def test_metadata_enrichment_result_defaults(self) -> None:
        result = MetadataEnrichmentResult()
        assert result.source == ""
        assert result.language == ""


class TestEnrichmentUpdate:
    def test_dump_excludes_none_fields(self) -> None:
        update = EnrichmentUpdate(cleaned_text="hello")
        dumped = {k: v for k, v in update if v is not None}
        assert dumped == {"cleaned_text": "hello"}


class TestEntityExtractionFailedError:
    def test_message(self) -> None:
        exc = EntityExtractionFailedError(reason="bad json")
        assert str(exc) == "Entity extraction failed: bad json"
        assert isinstance(exc, Exception)

    def test_raises_with_context(self) -> None:
        with pytest.raises(EntityExtractionFailedError, match="bad json"):
            raise EntityExtractionFailedError(reason="bad json")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/enrichment/test_domain.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.enrichment.domain'`

- [ ] **Step 3: Implement `domain/results.py`**

```python
# src/classiflow/enrichment/domain/results.py
from classiflow.domain.base import BaseEntity


class TextCleaningResult(BaseEntity):
    cleaned_text: str = ""


class EntityExtractionResult(BaseEntity):
    doc_type_hint: str | None = None
    number: str | None = None
    year: int | None = None
    issuing_body: str | None = None
    signatories: list[str] = []
    article_count: int | None = None


class MetadataEnrichmentResult(BaseEntity):
    source: str = ""
    filename: str = ""
    language: str = ""
    sha256: str = ""
    stage2_extractor_used: str = ""
```

- [ ] **Step 4: Implement `domain/state.py`**

```python
# src/classiflow/enrichment/domain/state.py
from typing import TypedDict

from classiflow.domain.base import BaseEntity

from .results import EntityExtractionResult, MetadataEnrichmentResult, TextCleaningResult


class _EnrichmentStateRequired(TypedDict):
    job_id: str
    filename: str
    text: str
    language: str
    sha256: str
    stage2_extractor_used: str


class EnrichmentState(_EnrichmentStateRequired, total=False):
    cleaned_text: str
    cleaning: TextCleaningResult
    entities: EntityExtractionResult
    metadata: MetadataEnrichmentResult


class EnrichmentUpdate(BaseEntity):
    """Typed construction for an enrichment coordinator node's partial
    EnrichmentState update — mirrors ingesta/domain/state.py's NodeUpdate pattern."""

    cleaned_text: str | None = None
    cleaning: TextCleaningResult | None = None
    entities: EntityExtractionResult | None = None
    metadata: MetadataEnrichmentResult | None = None
```

- [ ] **Step 5: Implement `domain/__init__.py`**

```python
# src/classiflow/enrichment/domain/__init__.py
from .results import EntityExtractionResult, MetadataEnrichmentResult, TextCleaningResult
from .state import EnrichmentState, EnrichmentUpdate

__all__ = [
    "EnrichmentState",
    "EnrichmentUpdate",
    "EntityExtractionResult",
    "MetadataEnrichmentResult",
    "TextCleaningResult",
]
```

- [ ] **Step 6: Implement `exceptions.py`**

```python
# src/classiflow/enrichment/exceptions.py
from dataclasses import dataclass


class EnrichmentError(Exception): ...


@dataclass
class EntityExtractionFailedError(EnrichmentError):
    reason: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Entity extraction failed: {self.reason}"
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/enrichment/test_domain.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/classiflow/enrichment/domain/ src/classiflow/enrichment/exceptions.py tests/enrichment/test_domain.py
git commit -m "feat: add enrichment domain models and exceptions"
```

---

## Task 5: `EnrichedRecord` DB model, migration, and repository

**Files:**
- Modify: `src/classiflow/database/models.py`
- Create: `alembic/versions/0004_add_enriched_records.py`
- Create: `src/classiflow/domain/repositories/enriched_record.py`
- Modify: `src/classiflow/domain/repositories/__init__.py`
- Create: `src/classiflow/database/repositories/enriched_record.py`
- Modify: `tests/shared/test_repositories.py`

**Interfaces:**
- Produces: `classiflow.database.models.EnrichedRecord` (`id: int` PK autoincrement, `job_id: str` FK→`jobs.job_id`, `cleaned_text: str`, `entities: dict[str, object]`, `metadata_: dict[str, object]` — Python attribute `metadata_` mapped to DB column `"metadata"`, since `metadata` is a reserved `Base.metadata` name on any SQLAlchemy Declarative class — `created_at: datetime`). `classiflow.domain.repositories.enriched_record.IEnrichedRecordRepository` (Protocol: `save(record) -> None`, `find_by_job_id(job_id) -> EnrichedRecord | None`). `SqlEnrichedRecordRepository`, `InMemoryEnrichedRecordRepository`.
- Consumes: `classiflow.database.base.Base`.

- [ ] **Step 1: Write the failing test**

Append to `tests/shared/test_repositories.py` (matching its existing `TestSqlDocumentStepsRepository`/`TestInMemoryDocumentStepsRepository` pattern — check the file's existing imports at the top and add `EnrichedRecord`, `SqlEnrichedRecordRepository`, `InMemoryEnrichedRecordRepository` to them):

```python
def _enriched_record(job_id: str = _JOB) -> EnrichedRecord:
    return EnrichedRecord(
        job_id=job_id,
        cleaned_text="Artículo 1º...",
        entities={"doc_type_hint": "ordenanza"},
        metadata_={"source": "manual_upload"},
    )


class TestSqlEnrichedRecordRepository:
    async def test_save_and_find(self, session: AsyncSession) -> None:
        repo = SqlEnrichedRecordRepository(session)
        await repo.save(_enriched_record())
        record = await repo.find_by_job_id(_JOB)
        assert record is not None
        assert record.cleaned_text == "Artículo 1º..."
        assert record.entities == {"doc_type_hint": "ordenanza"}
        assert record.metadata_ == {"source": "manual_upload"}

    async def test_find_missing_returns_none(self, session: AsyncSession) -> None:
        repo = SqlEnrichedRecordRepository(session)
        assert await repo.find_by_job_id("no-such-job") is None


class TestInMemoryEnrichedRecordRepository:
    async def test_save_and_find(self) -> None:
        repo = InMemoryEnrichedRecordRepository()
        await repo.save(_enriched_record())
        record = await repo.find_by_job_id(_JOB)
        assert record is not None
        assert record.cleaned_text == "Artículo 1º..."

    async def test_find_missing_returns_none(self) -> None:
        repo = InMemoryEnrichedRecordRepository()
        assert await repo.find_by_job_id("no-such-job") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/shared/test_repositories.py -k EnrichedRecord -v`
Expected: FAIL with `ImportError` (nothing exists yet)

- [ ] **Step 3: Add `EnrichedRecord` to `database/models.py`**

Append after the `HumanDecision` class:

```python
class EnrichedRecord(Base):
    __tablename__ = "enriched_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True
    )
    cleaned_text: Mapped[str] = mapped_column(Text, nullable=False)
    entities: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    # Named metadata_ (not metadata) because `metadata` is reserved on every SQLAlchemy
    # Declarative class (Base.metadata is the schema's MetaData object) -- the DB column
    # itself is still named "metadata", only the Python attribute differs.
    metadata_: Mapped[dict[str, object]] = mapped_column("metadata", JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
```

(Check the top of `models.py` for its existing imports — `Mapped`, `mapped_column`, `Integer`, `String`, `Text`, `JSON`, `DateTime`, `ForeignKey`, `func` should already be imported for the other tables; add any missing.)

- [ ] **Step 4: Write the Alembic migration**

```python
# alembic/versions/0004_add_enriched_records.py
"""Add enriched_records table

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-17
"""
import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enriched_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cleaned_text", sa.Text, nullable=False),
        sa.Column("entities", sa.JSON, nullable=False),
        sa.Column("metadata", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_enriched_records_job_id", "enriched_records", ["job_id"])


def downgrade() -> None:
    op.drop_table("enriched_records")
```

- [ ] **Step 5: Write the repository Protocol**

```python
# src/classiflow/domain/repositories/enriched_record.py
from typing import Protocol

from classiflow.database.models import EnrichedRecord


class IEnrichedRecordRepository(Protocol):
    async def save(self, record: EnrichedRecord) -> None: ...
    async def find_by_job_id(self, job_id: str) -> EnrichedRecord | None: ...
```

Add it to `src/classiflow/domain/repositories/__init__.py`'s existing re-exports (check that file's current imports/`__all__` and add `IEnrichedRecordRepository` alongside `IJobRepository`, `IDocumentStepsRepository`, etc., following the same pattern).

- [ ] **Step 6: Write the Sql/InMemory implementations**

```python
# src/classiflow/database/repositories/enriched_record.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.database.models import EnrichedRecord


class SqlEnrichedRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: EnrichedRecord) -> None:
        self._session.add(record)
        await self._session.flush()

    async def find_by_job_id(self, job_id: str) -> EnrichedRecord | None:
        result = await self._session.execute(
            select(EnrichedRecord).where(EnrichedRecord.job_id == job_id)
        )
        return result.scalar_one_or_none()


class InMemoryEnrichedRecordRepository:
    def __init__(self) -> None:
        self._records: dict[str, EnrichedRecord] = {}

    async def save(self, record: EnrichedRecord) -> None:
        self._records[record.job_id] = record

    async def find_by_job_id(self, job_id: str) -> EnrichedRecord | None:
        return self._records.get(job_id)
```

- [ ] **Step 7: Apply the migration to the local dev DB**

Hand to the user (per this project's convention — do not run yourself): `uv run alembic upgrade head`

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/shared/test_repositories.py -k EnrichedRecord -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/classiflow/database/models.py alembic/versions/0004_add_enriched_records.py src/classiflow/domain/repositories/enriched_record.py src/classiflow/domain/repositories/__init__.py src/classiflow/database/repositories/enriched_record.py tests/shared/test_repositories.py
git commit -m "feat: add EnrichedRecord model, migration, and repository"
```

---

## Task 6: Text Cleaner node

Frequency-based repeated-line stripping (not a page-boundary comparison — neither extractor preserves page markers), page-number removal, OCR-noise stripping, Unicode NFC normalization.

**Files:**
- Create: `src/classiflow/enrichment/nodes/__init__.py`
- Create: `src/classiflow/enrichment/nodes/text_cleaner.py`
- Create: `tests/enrichment/test_text_cleaner.py`

**Interfaces:**
- Consumes: `classiflow.pipeline.base.BaseNode`, `classiflow.pipeline.context.JobContext` (Task 1), `classiflow.enrichment.config_enrichment.EnrichmentConfig`/`get_enrichment_config` (Task 3), `classiflow.enrichment.domain.results.TextCleaningResult` (Task 4).
- Produces: `TextCleanerNode(BaseNode)` — `__init__(audit, broadcaster, *, config=None)`, `async run(ctx, text) -> TextCleaningResult`, `clean(text) -> TextCleaningResult` (sync, directly testable).

- [ ] **Step 1: Write the failing test**

```python
# tests/enrichment/test_text_cleaner.py
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.enrichment.config_enrichment import EnrichmentConfig
from classiflow.enrichment.nodes.text_cleaner import TextCleanerNode
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_CONFIG = EnrichmentConfig(repeated_line_min_count=3)


def _node() -> TextCleanerNode:
    return TextCleanerNode(
        audit=AuditService(InMemoryAuditRepository()),
        broadcaster=EventBroadcaster(),
        config=_CONFIG,
    )


class TestTextCleanerClean:
    def test_strips_lines_repeated_3_or_more_times(self) -> None:
        text = "\n".join(
            ["Municipalidad de Rosario", "Artículo 1", "Municipalidad de Rosario",
             "Artículo 2", "Municipalidad de Rosario"]
        )
        result = _node().clean(text)
        assert "Municipalidad de Rosario" not in result.cleaned_text
        assert "Artículo 1" in result.cleaned_text
        assert "Artículo 2" in result.cleaned_text

    def test_keeps_lines_repeated_fewer_than_threshold_times(self) -> None:
        text = "\n".join(["Header", "Body line", "Header"])
        result = _node().clean(text)
        assert "Header" in result.cleaned_text

    def test_strips_page_numbers(self) -> None:
        text = "\n".join(["Contenido real", "Página 3", "5", "3/10"])
        result = _node().clean(text)
        assert "Contenido real" in result.cleaned_text
        assert "Página 3" not in result.cleaned_text
        assert "3/10" not in result.cleaned_text

    def test_normalizes_unicode_to_nfc(self) -> None:
        # "a" + combining acute accent (NFD) vs precomposed "á" (NFC)
        decomposed = "Municipalidad de Rosarió"
        result = _node().clean(decomposed)
        assert result.cleaned_text == "Municipalidad de Rosarió".replace(
            "́", ""
        ) or "́" not in result.cleaned_text

    def test_empty_text_yields_empty_result(self) -> None:
        result = _node().clean("")
        assert result.cleaned_text == ""


class TestTextCleanerRun:
    async def test_run_emits_started_and_passed(self) -> None:
        broadcaster = EventBroadcaster()
        node = TextCleanerNode(
            audit=AuditService(InMemoryAuditRepository()), broadcaster=broadcaster, config=_CONFIG
        )
        ctx = JobContext(job_id="job-1", filename="doc.pdf")
        result = await node.run(ctx, "Artículo 1º — texto de prueba.")
        assert "Artículo 1" in result.cleaned_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/enrichment/test_text_cleaner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.enrichment.nodes'`

- [ ] **Step 3: Implement the node**

```python
# src/classiflow/enrichment/nodes/text_cleaner.py
import re
import unicodedata

from classiflow.database.repositories.audit import AuditDetail
from classiflow.enrichment.config_enrichment import EnrichmentConfig, get_enrichment_config
from classiflow.enrichment.domain.results import TextCleaningResult
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_PAGE_NUMBER_RE = re.compile(r"^(p[aá]gina\s+)?\d+(\s*/\s*\d+)?$", re.IGNORECASE)
# Strips characters that aren't letters (incl. accented Spanish), digits, whitespace,
# or common punctuation seen in municipal act text -- OCR noise typically shows up as
# runs of symbols outside this set.
_NOISE_RE = re.compile(r"[^\w\sáéíóúñÁÉÍÓÚÑüÜ.,;:()\-\"'ºª/%]")


class TextCleanerNode(BaseNode):
    @property
    def name(self) -> str:
        return "enrichment_text_cleaner"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        config: EnrichmentConfig | None = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.config: EnrichmentConfig = config if config is not None else get_enrichment_config()

    async def run(self, ctx: JobContext, text: str) -> TextCleaningResult:
        start = await self._emit_started(ctx)
        result = self.clean(text)
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
                "input_chars": len(text),
                "output_chars": len(result.cleaned_text),
            }),
        )
        return result

    def clean(self, text: str) -> TextCleaningResult:
        lines = text.split("\n")
        counts: dict[str, int] = {}
        for line in lines:
            stripped = line.strip()
            if stripped:
                counts[stripped] = counts.get(stripped, 0) + 1

        kept: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if counts[stripped] >= self.config.repeated_line_min_count:
                continue
            if _PAGE_NUMBER_RE.match(stripped):
                continue
            kept.append(_NOISE_RE.sub("", stripped))

        return TextCleaningResult(cleaned_text=unicodedata.normalize("NFC", "\n".join(kept)))
```

```python
# src/classiflow/enrichment/nodes/__init__.py
from classiflow.enrichment.nodes.text_cleaner import TextCleanerNode

__all__ = ["TextCleanerNode"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/enrichment/test_text_cleaner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/classiflow/enrichment/nodes/ tests/enrichment/test_text_cleaner.py
git commit -m "feat: add Stage 3 text cleaner node"
```

---

## Task 7: Entity-extraction LLM chain

Same pattern as `ingesta/prompts/content_validation.py`: `BaseEntity` input/output, plain `.format()` template, JSON-object regex parse, `Runnable` chain built from a raw `BaseLLM`.

**Files:**
- Create: `src/classiflow/enrichment/prompts/__init__.py`
- Create: `src/classiflow/enrichment/prompts/entity_extraction.py`
- Create: `tests/enrichment/test_entity_extraction_chain.py`

**Interfaces:**
- Consumes: `classiflow.domain.base.BaseEntity`, `classiflow.ingesta.llm_provider.MockLlm` (test only).
- Produces: `EntityExtractionInput(BaseEntity, cleaned_text: str)`, `EntityExtractionOutput(BaseEntity, doc_type_hint, number, year, issuing_body, signatories, article_count)`, `build_entity_extraction_chain(llm: BaseLLM) -> Runnable[EntityExtractionInput, EntityExtractionOutput]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/enrichment/test_entity_extraction_chain.py
import pytest

from classiflow.enrichment.prompts.entity_extraction import (
    EntityExtractionInput,
    build_entity_extraction_chain,
)
from classiflow.ingesta.llm_provider import MockLlm

_VALID_RESPONSE = (
    '{"doc_type_hint": "ordenanza", "number": "6801", "year": 1999, '
    '"issuing_body": "Concejo Municipal", "signatories": ["Hermes Binner"], '
    '"article_count": 3}'
)
_MALFORMED_RESPONSE = "not json at all"


class TestBuildEntityExtractionChain:
    def test_parses_valid_response(self) -> None:
        chain = build_entity_extraction_chain(MockLlm(response=_VALID_RESPONSE))
        output = chain.invoke(EntityExtractionInput(cleaned_text="Artículo 1º ..."))
        assert output.doc_type_hint == "ordenanza"
        assert output.number == "6801"
        assert output.year == 1999
        assert output.issuing_body == "Concejo Municipal"
        assert output.signatories == ["Hermes Binner"]
        assert output.article_count == 3

    def test_raises_value_error_on_malformed_response(self) -> None:
        chain = build_entity_extraction_chain(MockLlm(response=_MALFORMED_RESPONSE))
        with pytest.raises(ValueError, match="No valid JSON object"):
            chain.invoke(EntityExtractionInput(cleaned_text="Artículo 1º ..."))

    def test_all_fields_optional_on_empty_object(self) -> None:
        chain = build_entity_extraction_chain(MockLlm(response="{}"))
        output = chain.invoke(EntityExtractionInput(cleaned_text="..."))
        assert output.doc_type_hint is None
        assert output.signatories == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/enrichment/test_entity_extraction_chain.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.enrichment.prompts'`

- [ ] **Step 3: Implement the chain**

```python
# src/classiflow/enrichment/prompts/entity_extraction.py
import contextlib
import json
import re

from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnableLambda

from classiflow.domain.base import BaseEntity


class EntityExtractionInput(BaseEntity):
    cleaned_text: str


_TEMPLATE = """\
Task: extract structured metadata from this excerpt of an official municipal \
act (ordenanza, decreto, resolución) of the Municipalidad de Rosario. Return \
only what is explicitly present in the text — use null for anything not \
found, do not guess or infer.

Text: {cleaned_text}

Answer with a single JSON object and nothing else.

JSON:
{{"doc_type_hint": "ordenanza, decreto, resolucion, or null", \
"number": "act number as it appears, or null", \
"year": "year as an integer, or null", \
"issuing_body": "issuing body name, or null", \
"signatories": ["list of signatory names, empty array if none found"], \
"article_count": "number of ARTÍCULO entries detected, or null"}}"""

# Matches a single non-nested JSON object -- same approach as
# ingesta/prompts/content_validation.py's _JSON_RE (the "signatories" array's own
# brackets don't confuse this, since [] aren't excluded from the character class).
_JSON_RE = re.compile(r"\{[^{}]+\}", re.DOTALL)


class EntityExtractionOutput(BaseEntity):
    doc_type_hint: str | None = None
    number: str | None = None
    year: int | None = None
    issuing_body: str | None = None
    signatories: list[str] = []
    article_count: int | None = None


def _extract(text: str) -> EntityExtractionOutput:
    for m in _JSON_RE.finditer(text):
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            return EntityExtractionOutput.model_validate(json.loads(m.group()))
    msg = f"No valid JSON object found in LLM output: {text!r}"
    raise ValueError(msg)


def _format_prompt(chain_input: EntityExtractionInput) -> str:
    return _TEMPLATE.format(cleaned_text=chain_input.cleaned_text)


def build_entity_extraction_chain(
    llm: BaseLLM,
) -> Runnable[EntityExtractionInput, EntityExtractionOutput]:
    return RunnableLambda(_format_prompt) | llm | StrOutputParser() | RunnableLambda(_extract)
```

```python
# src/classiflow/enrichment/prompts/__init__.py
from classiflow.enrichment.prompts.entity_extraction import (
    EntityExtractionInput,
    EntityExtractionOutput,
    build_entity_extraction_chain,
)

__all__ = ["EntityExtractionInput", "EntityExtractionOutput", "build_entity_extraction_chain"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/enrichment/test_entity_extraction_chain.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/classiflow/enrichment/prompts/ tests/enrichment/test_entity_extraction_chain.py
git commit -m "feat: add entity-extraction LLM chain"
```

---

## Task 8: Entity Extractor node

Wraps the chain from Task 7 in a `BaseNode`, following node2/node3's override-seam pattern, but **raises** `EntityExtractionFailedError` on failure instead of degrading into a "needs review" result — Stage 3's retry-then-review logic lives one level up (Task 12, `PipelineService`), since (unlike node3's coordinator) the enrichment coordinator has no built-in review branch to route to.

**Files:**
- Modify: `src/classiflow/enrichment/nodes/__init__.py`
- Create: `src/classiflow/enrichment/nodes/entity_extractor.py`
- Create: `tests/enrichment/test_entity_extractor.py`

**Interfaces:**
- Consumes: `classiflow.pipeline.base.BaseNode`, `classiflow.pipeline.context.JobContext` (Task 1), `classiflow.enrichment.prompts.entity_extraction.{EntityExtractionInput, EntityExtractionOutput, build_entity_extraction_chain}` (Task 7), `classiflow.enrichment.domain.results.EntityExtractionResult` (Task 4), `classiflow.enrichment.exceptions.EntityExtractionFailedError` (Task 4), `classiflow.ingesta.exceptions.LlmProviderError`, `classiflow.ingesta.llm_provider.get_llm_langchain`, `Settings.enrichment_model_path` (Task 3).
- Produces: `EntityExtractorNode(BaseNode)` — `__init__(audit, broadcaster, *, entity_chain=None)`, `async run(ctx, cleaned_text) -> EntityExtractionResult` (raises `EntityExtractionFailedError` on chain failure), `extract(cleaned_text) -> EntityExtractionResult` (sync, directly testable).

- [ ] **Step 1: Write the failing test**

```python
# tests/enrichment/test_entity_extractor.py
import pytest

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.enrichment.exceptions import EntityExtractionFailedError
from classiflow.enrichment.nodes.entity_extractor import EntityExtractorNode
from classiflow.enrichment.prompts.entity_extraction import build_entity_extraction_chain
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-enrich-001"
_VALID_RESPONSE = (
    '{"doc_type_hint": "decreto", "number": "42", "year": 2020, '
    '"issuing_body": "Intendencia", "signatories": [], "article_count": 1}'
)


def _node(response: str) -> EntityExtractorNode:
    return EntityExtractorNode(
        audit=AuditService(InMemoryAuditRepository()),
        broadcaster=EventBroadcaster(),
        entity_chain=build_entity_extraction_chain(MockLlm(response=response)),
    )


class TestEntityExtractorExtract:
    def test_extract_returns_result_on_valid_response(self) -> None:
        result = _node(_VALID_RESPONSE).extract("Artículo 1º ...")
        assert result.doc_type_hint == "decreto"
        assert result.number == "42"
        assert result.year == 2020

    def test_extract_raises_domain_error_on_malformed_response(self) -> None:
        with pytest.raises(EntityExtractionFailedError, match="No valid JSON object"):
            _node("not json").extract("Artículo 1º ...")


class TestEntityExtractorRun:
    async def test_run_emits_started_then_passed(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = EntityExtractorNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            entity_chain=build_entity_extraction_chain(MockLlm(response=_VALID_RESPONSE)),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, "Artículo 1º ...")
        assert result.doc_type_hint == "decreto"
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"

    async def test_run_emits_failed_and_reraises_on_error(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = EntityExtractorNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            entity_chain=build_entity_extraction_chain(MockLlm(response="not json")),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        with pytest.raises(EntityExtractionFailedError):
            await node.run(ctx, "Artículo 1º ...")
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/enrichment/test_entity_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.enrichment.nodes.entity_extractor'`

- [ ] **Step 3: Implement the node**

```python
# src/classiflow/enrichment/nodes/entity_extractor.py
import asyncio
from typing import Protocol, cast, runtime_checkable

from classiflow.database.repositories.audit import AuditDetail
from classiflow.enrichment.domain.results import EntityExtractionResult
from classiflow.enrichment.exceptions import EntityExtractionFailedError
from classiflow.enrichment.prompts.entity_extraction import (
    EntityExtractionInput,
    EntityExtractionOutput,
    build_entity_extraction_chain,
)
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.exceptions import LlmProviderError
from classiflow.ingesta.llm_provider import get_llm_langchain
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService
from classiflow.settings import Settings


@runtime_checkable
class _EntityChain(Protocol):
    def invoke(self, inp: EntityExtractionInput, **kwargs: object) -> EntityExtractionOutput: ...


class EntityExtractorNode(BaseNode):
    @property
    def name(self) -> str:
        return "enrichment_entity_extractor"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        entity_chain: "_EntityChain | None" = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.entity_chain: _EntityChain | None = entity_chain

    async def run(self, ctx: JobContext, cleaned_text: str) -> EntityExtractionResult:
        start = await self._emit_started(ctx)
        try:
            result = await asyncio.to_thread(self.extract, cleaned_text)
        except EntityExtractionFailedError as exc:
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
                "doc_type_hint": result.doc_type_hint,
                "article_count": result.article_count,
            }),
        )
        return result

    def extract(self, cleaned_text: str) -> EntityExtractionResult:
        if self.entity_chain is not None:
            chain: _EntityChain = self.entity_chain
        else:
            chain = cast(
                "_EntityChain",
                build_entity_extraction_chain(get_llm_langchain(Settings.enrichment_model_path)),
            )
        try:
            output = chain.invoke(EntityExtractionInput(cleaned_text=cleaned_text))
        except (ValueError, LlmProviderError) as exc:
            raise EntityExtractionFailedError(reason=str(exc)) from exc
        return EntityExtractionResult(
            doc_type_hint=output.doc_type_hint,
            number=output.number,
            year=output.year,
            issuing_body=output.issuing_body,
            signatories=output.signatories,
            article_count=output.article_count,
        )
```

Update `src/classiflow/enrichment/nodes/__init__.py`:

```python
from classiflow.enrichment.nodes.entity_extractor import EntityExtractorNode
from classiflow.enrichment.nodes.text_cleaner import TextCleanerNode

__all__ = ["EntityExtractorNode", "TextCleanerNode"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/enrichment/test_entity_extractor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/classiflow/enrichment/nodes/ tests/enrichment/test_entity_extractor.py
git commit -m "feat: add Stage 3 entity extractor node"
```

---

## Task 9: Metadata Enricher node

Pure data plumbing, no LLM — attaches `source` (hardcoded), `filename`, `language`, `sha256`, `stage2_extractor_used`.

**Files:**
- Modify: `src/classiflow/enrichment/nodes/__init__.py`
- Create: `src/classiflow/enrichment/nodes/metadata_enricher.py`
- Create: `tests/enrichment/test_metadata_enricher.py`

**Interfaces:**
- Consumes: `classiflow.pipeline.base.BaseNode`, `classiflow.pipeline.context.JobContext` (Task 1), `classiflow.enrichment.domain.results.MetadataEnrichmentResult` (Task 4).
- Produces: `MetadataEnricherNode(BaseNode)` — no constructor override needed (uses `BaseNode.__init__` as-is), `async run(ctx, *, filename, language, sha256, stage2_extractor_used) -> MetadataEnrichmentResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/enrichment/test_metadata_enricher.py
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.enrichment.nodes.metadata_enricher import MetadataEnricherNode
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-enrich-002"


class TestMetadataEnricherRun:
    async def test_attaches_expected_fields(self) -> None:
        node = MetadataEnricherNode(
            audit=AuditService(InMemoryAuditRepository()), broadcaster=EventBroadcaster()
        )
        ctx = JobContext(job_id=_JOB_ID, filename="ordenanza.pdf")
        result = await node.run(
            ctx,
            filename="ordenanza.pdf",
            language="es",
            sha256="a" * 64,
            stage2_extractor_used="markitdown",
        )
        assert result.source == "manual_upload"
        assert result.filename == "ordenanza.pdf"
        assert result.language == "es"
        assert result.sha256 == "a" * 64
        assert result.stage2_extractor_used == "markitdown"

    async def test_emits_started_then_passed(self) -> None:
        audit_repo = InMemoryAuditRepository()
        node = MetadataEnricherNode(
            audit=AuditService(audit_repo), broadcaster=EventBroadcaster()
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        await node.run(
            ctx, filename="doc.pdf", language="es", sha256="b" * 64, stage2_extractor_used="ocr"
        )
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/enrichment/test_metadata_enricher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.enrichment.nodes.metadata_enricher'`

- [ ] **Step 3: Implement the node**

```python
# src/classiflow/enrichment/nodes/metadata_enricher.py
from classiflow.database.repositories.audit import AuditDetail
from classiflow.enrichment.domain.results import MetadataEnrichmentResult
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext

_SOURCE = "manual_upload"


class MetadataEnricherNode(BaseNode):
    @property
    def name(self) -> str:
        return "enrichment_metadata_enricher"

    async def run(
        self,
        ctx: JobContext,
        *,
        filename: str,
        language: str,
        sha256: str,
        stage2_extractor_used: str,
    ) -> MetadataEnrichmentResult:
        start = await self._emit_started(ctx)
        result = MetadataEnrichmentResult(
            source=_SOURCE,
            filename=filename,
            language=language,
            sha256=sha256,
            stage2_extractor_used=stage2_extractor_used,
        )
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({"filename": filename, "source": _SOURCE}),
        )
        return result
```

Update `src/classiflow/enrichment/nodes/__init__.py`:

```python
from classiflow.enrichment.nodes.entity_extractor import EntityExtractorNode
from classiflow.enrichment.nodes.metadata_enricher import MetadataEnricherNode
from classiflow.enrichment.nodes.text_cleaner import TextCleanerNode

__all__ = ["EntityExtractorNode", "MetadataEnricherNode", "TextCleanerNode"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/enrichment/test_metadata_enricher.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/classiflow/enrichment/nodes/ tests/enrichment/test_metadata_enricher.py
git commit -m "feat: add Stage 3 metadata enricher node"
```

---

## Task 10: Enrichment coordinator (LangGraph)

3-node linear chain: `clean → extract → enrich`. Mirrors `ingesta/coordinator.py`'s `_dump()`/`NodeUpdate` pattern, but with no conditional routing — Stage 3 has no reject/review branch of its own (failure handling is Task 12's job, one level up, since a mid-graph exception here simply propagates out of `.ainvoke()`).

**Files:**
- Create: `src/classiflow/enrichment/coordinator.py`
- Create: `tests/enrichment/test_coordinator.py`

**Interfaces:**
- Consumes: `TextCleanerNode`, `EntityExtractorNode`, `MetadataEnricherNode` (Tasks 6, 8, 9), `EnrichmentState`, `EnrichmentUpdate` (Task 4), `classiflow.pipeline.context.JobContext` (Task 1), `classiflow.enrichment.exceptions.EntityExtractionFailedError` (Task 4, re-raised through `.ainvoke()` by design).
- Produces: `build_enrichment_coordinator(text_cleaner, entity_extractor, metadata_enricher) -> CompiledStateGraph`. Compiled graph's `.ainvoke(EnrichmentState) -> EnrichmentState` with `cleaned_text`, `cleaning`, `entities`, `metadata` all populated on success, or raises `EntityExtractionFailedError` if the LLM step fails.

- [ ] **Step 1: Write the failing test**

```python
# tests/enrichment/test_coordinator.py
import pytest

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.enrichment.coordinator import build_enrichment_coordinator
from classiflow.enrichment.domain.state import EnrichmentState
from classiflow.enrichment.exceptions import EntityExtractionFailedError
from classiflow.enrichment.nodes import EntityExtractorNode, MetadataEnricherNode, TextCleanerNode
from classiflow.enrichment.prompts.entity_extraction import build_entity_extraction_chain
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.services.audit.service import AuditService

_VALID_RESPONSE = (
    '{"doc_type_hint": "ordenanza", "number": "1", "year": 2024, '
    '"issuing_body": "Concejo Municipal", "signatories": [], "article_count": 1}'
)


def _build_graph(entity_response: str):
    audit = AuditService(InMemoryAuditRepository())
    broadcaster = EventBroadcaster()
    text_cleaner = TextCleanerNode(audit=audit, broadcaster=broadcaster)
    entity_extractor = EntityExtractorNode(
        audit=audit,
        broadcaster=broadcaster,
        entity_chain=build_entity_extraction_chain(MockLlm(response=entity_response)),
    )
    metadata_enricher = MetadataEnricherNode(audit=audit, broadcaster=broadcaster)
    return build_enrichment_coordinator(text_cleaner, entity_extractor, metadata_enricher)


class TestEnrichmentCoordinatorHappyPath:
    async def test_full_chain_produces_all_results(self) -> None:
        graph = _build_graph(_VALID_RESPONSE)
        initial: EnrichmentState = {
            "job_id": "enrich-coord-001",
            "filename": "ordenanza.pdf",
            "text": "Municipalidad de Rosario\nArtículo 1º — texto.\nMunicipalidad de Rosario\nMunicipalidad de Rosario",
            "language": "es",
            "sha256": "a" * 64,
            "stage2_extractor_used": "markitdown",
        }
        result = await graph.ainvoke(initial)

        assert "Artículo 1" in result["cleaned_text"]
        assert result["entities"].doc_type_hint == "ordenanza"
        assert result["metadata"].source == "manual_upload"
        assert result["metadata"].language == "es"
        assert result["metadata"].sha256 == "a" * 64


class TestEnrichmentCoordinatorFailure:
    async def test_entity_extraction_failure_propagates(self) -> None:
        graph = _build_graph("not json")
        initial: EnrichmentState = {
            "job_id": "enrich-coord-002",
            "filename": "doc.pdf",
            "text": "Artículo 1º — texto.",
            "language": "es",
            "sha256": "b" * 64,
            "stage2_extractor_used": "ocr",
        }
        with pytest.raises(EntityExtractionFailedError):
            await graph.ainvoke(initial)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/enrichment/test_coordinator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.enrichment.coordinator'`

- [ ] **Step 3: Implement the coordinator**

```python
# src/classiflow/enrichment/coordinator.py
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from classiflow.enrichment.domain.results import (
    EntityExtractionResult,
    MetadataEnrichmentResult,
    TextCleaningResult,
)
from classiflow.enrichment.domain.state import EnrichmentState, EnrichmentUpdate
from classiflow.enrichment.nodes import EntityExtractorNode, MetadataEnricherNode, TextCleanerNode
from classiflow.pipeline.context import JobContext

EnrichmentUpdateValue = str | TextCleaningResult | EntityExtractionResult | MetadataEnrichmentResult


def _dump(update: EnrichmentUpdate) -> dict[str, EnrichmentUpdateValue]:
    return {k: v for k, v in update if v is not None}


def build_enrichment_coordinator(
    text_cleaner: TextCleanerNode,
    entity_extractor: EntityExtractorNode,
    metadata_enricher: MetadataEnricherNode,
) -> CompiledStateGraph:  # type: ignore[type-arg]
    async def _clean(state: EnrichmentState) -> dict[str, EnrichmentUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await text_cleaner.run(ctx, state["text"])
        return _dump(EnrichmentUpdate(cleaning=result, cleaned_text=result.cleaned_text))

    async def _extract(state: EnrichmentState) -> dict[str, EnrichmentUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await entity_extractor.run(ctx, state["cleaned_text"])
        return _dump(EnrichmentUpdate(entities=result))

    async def _enrich(state: EnrichmentState) -> dict[str, EnrichmentUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await metadata_enricher.run(
            ctx,
            filename=state["filename"],
            language=state["language"],
            sha256=state["sha256"],
            stage2_extractor_used=state["stage2_extractor_used"],
        )
        return _dump(EnrichmentUpdate(metadata=result))

    graph: StateGraph = StateGraph(EnrichmentState)  # type: ignore[type-arg]
    graph.add_node("clean", _clean)
    graph.add_node("extract", _extract)
    graph.add_node("enrich", _enrich)
    graph.set_entry_point("clean")
    graph.add_edge("clean", "extract")
    graph.add_edge("extract", "enrich")
    graph.add_edge("enrich", END)

    return graph.compile()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/enrichment/test_coordinator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/classiflow/enrichment/coordinator.py tests/enrichment/test_coordinator.py
git commit -m "feat: add Stage 3 enrichment coordinator"
```

---

## Task 11: DI wiring — production Container, TestContainer, `api/dependencies.py`

**Files:**
- Modify: `src/classiflow/injections/production.py`
- Modify: `src/classiflow/injections/test.py`
- Modify: `src/classiflow/api/dependencies.py`

**Interfaces:**
- Consumes: everything from Tasks 3–10, plus `classiflow.ingesta.llm_provider.{get_llm_langchain, MockLlm}`, `classiflow.database.repositories.enriched_record.{SqlEnrichedRecordRepository, InMemoryEnrichedRecordRepository}` (Task 5).
- Produces: `Container.enrichment_llm`, `Container.entity_extraction_chain` providers; `get_text_cleaner`, `get_entity_extractor`, `get_metadata_enricher`, `get_enrichment_coordinator`, `get_enriched_record_repo` dependency functions in `api/dependencies.py`; `TestContainer.enrichment_coordinator`, `TestContainer.enriched_record_repo`.

- [ ] **Step 1: Add `entity_extraction_chain` to `Container` (production.py)**

In `src/classiflow/injections/production.py`, add imports:

```python
from classiflow.enrichment.prompts.entity_extraction import build_entity_extraction_chain
```

Add inside `Container`, after `node3_content_chain`:

```python
    # Same Callable-wrapping-a-cache reasoning as node2_llm/node3_llm above -- a fresh
    # get_llm_langchain(path) call per resolution, sharing the same @lru_cache(maxsize=4)
    # slot, so unload_slm()'s cache_clear() still releases this model's VRAM too.
    enrichment_llm = providers.Callable(get_llm_langchain, Settings.enrichment_model_path)
    entity_extraction_chain = providers.Callable(build_entity_extraction_chain, enrichment_llm)
```

- [ ] **Step 2: Add enrichment dependency functions to `api/dependencies.py`**

Add imports:

```python
from classiflow.database.repositories.enriched_record import SqlEnrichedRecordRepository
from classiflow.domain.repositories.enriched_record import IEnrichedRecordRepository
from classiflow.enrichment.coordinator import build_enrichment_coordinator
from classiflow.enrichment.nodes import EntityExtractorNode, MetadataEnricherNode, TextCleanerNode
from classiflow.enrichment.prompts.entity_extraction import (
    EntityExtractionInput,
    EntityExtractionOutput,
)
```

Add `_EntityChain` to the existing `TYPE_CHECKING` block (same precedent as `_FormatChain`/`_ContentChain`):

```python
if TYPE_CHECKING:
    from classiflow.enrichment.nodes.entity_extractor import _EntityChain
    from classiflow.ingesta.nodes.node2_format_validation import _FormatChain
    from classiflow.ingesta.nodes.node3_content_validation import _ContentChain
```

Add the dependency functions (after `get_node4`, before `get_extraction_step` or anywhere in the node-builder group):

```python
def get_enriched_record_repo(session: DbSession) -> IEnrichedRecordRepository:
    return SqlEnrichedRecordRepository(session)


def get_text_cleaner(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> TextCleanerNode:
    return TextCleanerNode(audit=audit_service, broadcaster=broadcaster)


@inject
def get_entity_extractor(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    entity_chain: Annotated[
        Runnable[EntityExtractionInput, EntityExtractionOutput],
        Depends(Provide[Container.entity_extraction_chain]),
    ],
) -> EntityExtractorNode:
    return EntityExtractorNode(
        audit=audit_service,
        broadcaster=broadcaster,
        entity_chain=cast("_EntityChain", entity_chain),
    )


def get_metadata_enricher(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> MetadataEnricherNode:
    return MetadataEnricherNode(audit=audit_service, broadcaster=broadcaster)


def get_enrichment_coordinator(
    text_cleaner: Annotated[TextCleanerNode, Depends(get_text_cleaner)],
    entity_extractor: Annotated[EntityExtractorNode, Depends(get_entity_extractor)],
    metadata_enricher: Annotated[MetadataEnricherNode, Depends(get_metadata_enricher)],
) -> CompiledStateGraph:  # type: ignore[type-arg]
    return build_enrichment_coordinator(text_cleaner, entity_extractor, metadata_enricher)
```

Update `get_pipeline_service` to also take the new repo and coordinator (final form shown here; Task 12 defines what `PipelineService` does with them):

```python
@inject
def get_pipeline_service(
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    document_steps_repo: Annotated[IDocumentStepsRepository, Depends(get_document_steps_repo)],
    enriched_record_repo: Annotated[IEnrichedRecordRepository, Depends(get_enriched_record_repo)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    coordinator: Annotated[CompiledStateGraph, Depends(get_coordinator)],  # type: ignore[type-arg]
    enrichment_coordinator: Annotated[
        CompiledStateGraph, Depends(get_enrichment_coordinator)  # type: ignore[type-arg]
    ],
) -> PipelineService:
    return PipelineService(
        job_repo=job_repo,
        document_steps_repo=document_steps_repo,
        enriched_record_repo=enriched_record_repo,
        broadcaster=broadcaster,
        coordinator=coordinator,
        enrichment_coordinator=enrichment_coordinator,
    )
```

- [ ] **Step 3: Wire `TestContainer` (injections/test.py)**

Add imports:

```python
from classiflow.database.repositories.enriched_record import InMemoryEnrichedRecordRepository
from classiflow.enrichment.coordinator import build_enrichment_coordinator
from classiflow.enrichment.nodes import EntityExtractorNode, MetadataEnricherNode, TextCleanerNode
from classiflow.enrichment.prompts.entity_extraction import build_entity_extraction_chain
```

Add a deterministic entity-extraction chain stub (mirrors `_test_embed`'s role — every FastAPI-level test that reaches an accepted job now also runs the enrichment coordinator, so it needs a chain that doesn't try to load a real GGUF model):

```python
_TEST_ENTITY_RESPONSE = (
    '{"doc_type_hint": "ordenanza", "number": "1", "year": 2024, '
    '"issuing_body": "Concejo Municipal", "signatories": [], "article_count": 1}'
)


def _test_entity_chain() -> Runnable[EntityExtractionInput, EntityExtractionOutput]:
    return build_entity_extraction_chain(MockLlm(response=_TEST_ENTITY_RESPONSE))
```

(Add `from classiflow.enrichment.prompts.entity_extraction import EntityExtractionInput, EntityExtractionOutput`, `from classiflow.ingesta.llm_provider import MockLlm`, and `from langchain_core.runnables import Runnable` to the imports.)

Add providers inside `TestContainer`, after `job_repo` and before `audit_service`:

```python
    enriched_record_repo = providers.Singleton(InMemoryEnrichedRecordRepository)
    entity_extraction_chain = providers.Singleton(_test_entity_chain)
```

Add after `node4`, before `coordinator`:

```python
    enrichment_text_cleaner = providers.Factory(
        TextCleanerNode, audit=audit_service, broadcaster=broadcaster
    )
    enrichment_entity_extractor = providers.Factory(
        EntityExtractorNode,
        audit=audit_service,
        broadcaster=broadcaster,
        entity_chain=entity_extraction_chain,
    )
    enrichment_metadata_enricher = providers.Factory(
        MetadataEnricherNode, audit=audit_service, broadcaster=broadcaster
    )
    enrichment_coordinator = providers.Factory(
        build_enrichment_coordinator,
        text_cleaner=enrichment_text_cleaner,
        entity_extractor=enrichment_entity_extractor,
        metadata_enricher=enrichment_metadata_enricher,
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
    )
```

- [ ] **Step 4: Verify wiring compiles**

Run: `pytest tests/api -v -k pipeline`
Expected: currently FAILS (or errors on collection) — `PipelineService.__init__` doesn't accept `enriched_record_repo`/`enrichment_coordinator` yet. That's expected; Task 12 completes `PipelineService` itself. Confirm the failure is specifically a `TypeError: __init__() got an unexpected keyword argument`, not an import/wiring error — that confirms this task's DI plumbing itself is correct and only `PipelineService` is outstanding.

- [ ] **Step 5: Commit**

```bash
git add src/classiflow/injections/production.py src/classiflow/injections/test.py src/classiflow/api/dependencies.py
git commit -m "feat: wire Stage 3 enrichment coordinator into DI containers"
```

(This commit intentionally leaves the test suite red until Task 12 lands — both are one logical unit split for reviewability; keep them on the same branch before merging.)

---

## Task 12: `PipelineService` integration — automatic trigger + retry-then-review

**Files:**
- Modify: `src/classiflow/services/pipeline/service.py`
- Create: `tests/shared/test_pipeline_service_enrichment.py`

**Interfaces:**
- Consumes: everything from Tasks 4, 5, 10 (`EnrichmentState`, `EnrichedRecord`, `IEnrichedRecordRepository`, the compiled enrichment coordinator, `EnrichmentError`).
- Produces: `PipelineService.__init__(job_repo, document_steps_repo, enriched_record_repo, broadcaster, coordinator, enrichment_coordinator)`. New private method `_run_enrichment(job_id, filename, final_state) -> None`, called from `_run()` only when `final_state["final_status"] == "accepted"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/shared/test_pipeline_service_enrichment.py
import asyncio
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from fastapi import BackgroundTasks

from classiflow.database.repositories.audit import InMemoryAuditRepository
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


def _build_service(entity_response: str) -> PipelineService:
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

    return PipelineService(
        job_repo=InMemoryJobRepository(),
        document_steps_repo=InMemoryDocumentStepsRepository(),
        enriched_record_repo=InMemoryEnrichedRecordRepository(),
        broadcaster=broadcaster,
        coordinator=coordinator,
        enrichment_coordinator=enrichment_coordinator,
    )


class TestPipelineServiceEnrichmentHappyPath:
    async def test_accepted_job_gets_enriched_record(self) -> None:
        service = _build_service(_VALID_ENTITY_RESPONSE)
        background_tasks = BackgroundTasks()
        job_id = await service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        job = await service._job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status == "accepted"

        record = await service._enriched_record_repo.find_by_job_id(job_id)
        assert record is not None
        assert "Artículo 1" in record.cleaned_text
        assert record.entities["doc_type_hint"] == "ordenanza"
        assert record.metadata_["source"] == "manual_upload"


class TestPipelineServiceEnrichmentFailurePath:
    async def test_enrichment_failure_marks_job_for_review(self) -> None:
        service = _build_service("not json at all")
        background_tasks = BackgroundTasks()
        job_id = await service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        job = await service._job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status == "review"
        assert job.review_action_needed == "enrichment_failed"
        assert job.failed_at_node == "enrichment"
        assert "Enrichment failed after retries" in (job.rejection_reason or "")

        record = await service._enriched_record_repo.find_by_job_id(job_id)
        assert record is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/shared/test_pipeline_service_enrichment.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'enriched_record_repo'`

- [ ] **Step 3: Update `PipelineService`**

In `src/classiflow/services/pipeline/service.py`, update imports:

```python
from classiflow.database.models import DocumentStep, EnrichedRecord, Job
from classiflow.domain.repositories.enriched_record import IEnrichedRecordRepository
from classiflow.enrichment.config_enrichment import get_enrichment_config
from classiflow.enrichment.domain.state import EnrichmentState
from classiflow.enrichment.exceptions import EnrichmentError
```

Update `__init__` and `_run`:

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
    ) -> None:
        self._job_repo = job_repo
        self._document_steps_repo = document_steps_repo
        self._enriched_record_repo = enriched_record_repo
        self._broadcaster = broadcaster
        self._coordinator = coordinator
        self._enrichment_coordinator = enrichment_coordinator

    async def start(
        self, background_tasks: BackgroundTasks, filename: str, file_bytes: bytes
    ) -> str:
        job_id = str(uuid4())
        now = datetime.now(timezone.utc)
        await self._job_repo.create(
            Job(job_id=job_id, filename=filename, status="started", created_at=now, updated_at=now)
        )
        background_tasks.add_task(self._run, job_id, filename, file_bytes)
        return job_id

    async def _run(self, job_id: str, filename: str, file_bytes: bytes) -> None:
        initial: JobState = {"job_id": job_id, "filename": filename, "file_bytes": file_bytes}
        final_state = cast("JobState", await self._coordinator.ainvoke(initial))

        failed_at_node = await self._persist_steps(job_id, final_state)
        await self._finalize_job(job_id, final_state, failed_at_node)
        unload_slm()

        if final_state.get("final_status") == "accepted":
            await self._run_enrichment(job_id, filename, final_state)

        await self._broadcaster.emit(
            NodeEvent(job_id=job_id, node=_PIPELINE_NODE, status=JobStatus.DONE)
        )
```

Add the new method, after `_finalize_job`:

```python
    async def _run_enrichment(self, job_id: str, filename: str, final_state: JobState) -> None:
        reception = cast("FileReceptionResult", final_state["reception"])
        content_validation = cast("ContentValidationResult", final_state["content_validation"])
        extraction = cast("ExtractionResult", final_state["extraction"])
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
                result = cast(
                    "EnrichmentState", await self._enrichment_coordinator.ainvoke(initial)
                )
            except EnrichmentError as exc:
                last_error = exc
                continue
            await self._enriched_record_repo.save(
                EnrichedRecord(
                    job_id=job_id,
                    cleaned_text=result["cleaned_text"],
                    entities=result["entities"].model_dump(),
                    metadata_=result["metadata"].model_dump(),
                )
            )
            return
        await self._job_repo.update_status(
            job_id,
            "review",
            rejection_reason=f"Enrichment failed after retries: {last_error}",
            review_action_needed="enrichment_failed",
            failed_at_node="enrichment",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/shared/test_pipeline_service_enrichment.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite (regression check on Task 11's intentionally-red state)**

Run: `pytest tests -v`
Expected: PASS across the board, including `tests/api` (Task 11's DI wiring now resolves correctly since `PipelineService` accepts the new params) and `tests/ingesta` (untouched).

- [ ] **Step 6: Commit**

```bash
git add src/classiflow/services/pipeline/service.py tests/shared/test_pipeline_service_enrichment.py
git commit -m "feat: trigger Stage 3 enrichment automatically after job acceptance"
```

---

## Task 13: Final verification and `todo_stage3.md` cleanup

**Files:**
- Modify: `tasks/todo_stage3.md`

**Interfaces:** none — documentation and verification only.

- [ ] **Step 1: Update `todo_stage3.md` to reflect this plan**

Replace its contents with a pointer to this plan (mirroring how `plan_stage3.md` now points to the design spec), since the thin `S3-T01..T05` cards are superseded by Tasks 1–12 above:

```markdown
# Classiflow — Stage 3 Task List

> Superseded by the detailed implementation plan:
> `docs/superpowers/plans/2026-08-17-refinement-enrichment.md` (Tasks 1-12).
> Design: `docs/superpowers/specs/2026-08-17-refinement-enrichment-design.md`.
> Full field/model details: [plan_stage3.md](plan_stage3.md).
```

- [ ] **Step 2: Hand the full verification gate to the user**

Hand over (do not run yourself, per this project's standing convention):

```bash
uv run poe check
```

Expected: `lint`, `typecheck`, `test`/`coverage` all pass.

- [ ] **Step 3: Hand over the pre-commit gate**

```bash
uv run --all-groups pre-commit run --all-files
```

Expected: all hooks pass.

- [ ] **Step 4: Commit**

```bash
git add tasks/todo_stage3.md
git commit -m "docs: point todo_stage3.md at the Stage 3 implementation plan"
```
