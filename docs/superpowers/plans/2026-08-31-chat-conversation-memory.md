# Chat Conversation Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist per-user chat history (raw turns + a running summary of older turns) so the
chat model can answer multi-turn follow-up questions, and the Chat page shows a user's prior
conversation across sessions.

**Architecture:** Two new tables (`conversation_turns`, `conversation_summaries`), a repository
pair following the existing `IDocumentKbRepository`/`SqlDocumentKbRepository`/
`InMemoryDocumentKbRepository` shape, a new `MemoryService` that loads history for prompting and
folds aging-out turns into a summary via one extra LLM call, two new `/knowledge/conversation`
endpoints, and a `ChatPage` change to load history on mount and add a clear button.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic (backend); React 19, TypeScript,
TanStack Query is NOT used on this page (matches existing `ChatPage` convention of plain
`useState`/`useEffect`, no react-query) (frontend); pytest, Vitest + Testing Library (tests).

**Spec:** `docs/superpowers/specs/2026-08-31-chat-conversation-memory-design.md`

## Global Constraints

- `RAW_WINDOW_SIZE = 6` — the last 6 turns are sent verbatim in every prompt; the 7th-oldest turn
  folds into the running summary the moment a 7th turn is saved.
- One continuous conversation per user (keyed by `AllowedUser.email`) — no multi-conversation
  support, no conversation-selection UI.
- Raw turns are never deleted except via the explicit `DELETE /knowledge/conversation` action —
  no auto-pruning when a turn ages out of the raw window.
- The summarization LLM call runs **after** the SSE stream has been fully sent to the client, not
  before — it must never add latency to a user-visible response.
- No new LLM provider — summarization reuses the existing `ChatLlm.astream` interface via the same
  `chat_llm` singleton already wired for answering.
- Follow `CLAUDE.md` exactly: full type annotations, no `Any`, no
  `from __future__ import annotations`, no `TYPE_CHECKING` unless a real circular import forces
  it, `BaseSchema`/`BaseEntity` for schemas/domain models, `@dataclass` exception subclasses,
  Protocol-based repository interfaces matching `IDocumentKbRepository`'s shape.

---

### Task 1: `ConversationTurn`/`ConversationSummary` models + alembic migration

**Files:**
- Modify: `src/classiflow/database/models.py`
- Create: `alembic/versions/0013_add_conversation_memory.py`

**Interfaces:**
- Produces: `ConversationTurn`, `ConversationSummary` SQLAlchemy models. Consumed by Task 2's
  repository.

- [ ] **Step 1: Add the two models**

In `src/classiflow/database/models.py`, add after `ClassificationRecord` (end of file):

```python
class ConversationTurn(Base):
    """One question/answer pair in a user's chat history.

    Append-only: rows are never updated, and are only deleted by the explicit
    "clear conversation" action. The last RAW_WINDOW_SIZE rows for a user are sent
    verbatim in every chat prompt; older rows are folded into ConversationSummary
    instead but remain here as the source of truth.
    """

    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ConversationSummary(Base):
    """Running summary of a user's turns older than the raw prompting window.

    At most one row per user, overwritten in place each time a turn ages out of
    MemoryService.RAW_WINDOW_SIZE.
    """

    __tablename__ = "conversation_summaries"

    user_email: Mapped[str] = mapped_column(String(255), primary_key=True)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 2: Create the migration**

Create `alembic/versions/0013_add_conversation_memory.py`:

```python
"""Add conversation_turns and conversation_summaries tables

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-31

"""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_email", sa.String(length=255), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_conversation_turns_user_email", "conversation_turns", ["user_email"])
    op.create_table(
        "conversation_summaries",
        sa.Column("user_email", sa.String(length=255), primary_key=True),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("conversation_summaries")
    op.drop_index("ix_conversation_turns_user_email", table_name="conversation_turns")
    op.drop_table("conversation_turns")
```

- [ ] **Step 3: Apply and verify the migration**

Run: `uv run alembic upgrade head`
Expected: applies `0013` cleanly on top of `0012`, no errors.

Run: `uv run alembic downgrade 0012 && uv run alembic upgrade head`
Expected: both directions succeed cleanly (confirms `downgrade()` is correct).

- [ ] **Step 4: Commit** — only when the user explicitly authorizes it (this repo's git-workflow
  rule); do not run `git commit` as part of this step.

---

### Task 2: `IConversationRepository` + Sql/InMemory implementations

**Files:**
- Create: `src/classiflow/domain/repositories/conversation.py`
- Create: `src/classiflow/database/repositories/conversation.py`
- Modify: `src/classiflow/domain/repositories/__init__.py`
- Modify: `tests/shared/test_repositories.py`

**Interfaces:**
- Consumes: `ConversationTurn`, `ConversationSummary` (Task 1).
- Produces: `IConversationRepository` Protocol, `SqlConversationRepository`,
  `InMemoryConversationRepository`. Consumed by Task 3's `MemoryService` and Task 6's DI wiring.

- [ ] **Step 1: Write the failing tests**

In `tests/shared/test_repositories.py`, add near the existing `TestSqlDocumentKbRepository`/
`TestInMemoryDocumentKbRepository` classes (same file already imports `AsyncSession`, `_JOB`
constant style — add new module-level constants for this section):

```python
_CONVO_USER = "convo-user@classiflow.dev"
_CONVO_OTHER_USER = "other-user@classiflow.dev"


class TestSqlConversationRepository:
    async def test_save_turn_then_recent_turns_returns_it(self, session: AsyncSession) -> None:
        repo = SqlConversationRepository(session)
        await repo.save_turn(_CONVO_USER, "q1", "a1")
        turns = await repo.recent_turns(_CONVO_USER, limit=6)
        assert len(turns) == 1
        assert turns[0].question == "q1"
        assert turns[0].answer == "a1"

    async def test_recent_turns_returns_oldest_first_within_the_limit(
        self, session: AsyncSession
    ) -> None:
        repo = SqlConversationRepository(session)
        for i in range(8):
            await repo.save_turn(_CONVO_USER, f"q{i}", f"a{i}")
        turns = await repo.recent_turns(_CONVO_USER, limit=6)
        assert [t.question for t in turns] == ["q2", "q3", "q4", "q5", "q6", "q7"]

    async def test_recent_turns_scoped_to_user(self, session: AsyncSession) -> None:
        repo = SqlConversationRepository(session)
        await repo.save_turn(_CONVO_USER, "mine", "a")
        await repo.save_turn(_CONVO_OTHER_USER, "not-mine", "a")
        turns = await repo.recent_turns(_CONVO_USER, limit=6)
        assert [t.question for t in turns] == ["mine"]

    async def test_all_turns_returns_oldest_first(self, session: AsyncSession) -> None:
        repo = SqlConversationRepository(session)
        await repo.save_turn(_CONVO_USER, "q1", "a1")
        await repo.save_turn(_CONVO_USER, "q2", "a2")
        turns = await repo.all_turns(_CONVO_USER)
        assert [t.question for t in turns] == ["q1", "q2"]

    async def test_turn_count(self, session: AsyncSession) -> None:
        repo = SqlConversationRepository(session)
        assert await repo.turn_count(_CONVO_USER) == 0
        await repo.save_turn(_CONVO_USER, "q1", "a1")
        await repo.save_turn(_CONVO_USER, "q2", "a2")
        assert await repo.turn_count(_CONVO_USER) == 2

    async def test_get_summary_missing_returns_none(self, session: AsyncSession) -> None:
        repo = SqlConversationRepository(session)
        assert await repo.get_summary(_CONVO_USER) is None

    async def test_save_summary_then_get_returns_it(self, session: AsyncSession) -> None:
        repo = SqlConversationRepository(session)
        await repo.save_summary(_CONVO_USER, "the summary")
        assert await repo.get_summary(_CONVO_USER) == "the summary"

    async def test_save_summary_overwrites_existing(self, session: AsyncSession) -> None:
        repo = SqlConversationRepository(session)
        await repo.save_summary(_CONVO_USER, "first")
        await repo.save_summary(_CONVO_USER, "second")
        assert await repo.get_summary(_CONVO_USER) == "second"

    async def test_clear_removes_turns_and_summary(self, session: AsyncSession) -> None:
        repo = SqlConversationRepository(session)
        await repo.save_turn(_CONVO_USER, "q1", "a1")
        await repo.save_summary(_CONVO_USER, "summary")
        await repo.clear(_CONVO_USER)
        assert await repo.all_turns(_CONVO_USER) == []
        assert await repo.get_summary(_CONVO_USER) is None

    async def test_clear_does_not_affect_other_users(self, session: AsyncSession) -> None:
        repo = SqlConversationRepository(session)
        await repo.save_turn(_CONVO_USER, "mine", "a")
        await repo.save_turn(_CONVO_OTHER_USER, "not-mine", "a")
        await repo.clear(_CONVO_USER)
        remaining = await repo.all_turns(_CONVO_OTHER_USER)
        assert [t.question for t in remaining] == ["not-mine"]


class TestInMemoryConversationRepository:
    async def test_save_turn_then_recent_turns_returns_it(self) -> None:
        repo = InMemoryConversationRepository()
        await repo.save_turn(_CONVO_USER, "q1", "a1")
        turns = await repo.recent_turns(_CONVO_USER, limit=6)
        assert len(turns) == 1
        assert turns[0].question == "q1"

    async def test_recent_turns_returns_oldest_first_within_the_limit(self) -> None:
        repo = InMemoryConversationRepository()
        for i in range(8):
            await repo.save_turn(_CONVO_USER, f"q{i}", f"a{i}")
        turns = await repo.recent_turns(_CONVO_USER, limit=6)
        assert [t.question for t in turns] == ["q2", "q3", "q4", "q5", "q6", "q7"]

    async def test_turn_count(self) -> None:
        repo = InMemoryConversationRepository()
        assert await repo.turn_count(_CONVO_USER) == 0
        await repo.save_turn(_CONVO_USER, "q1", "a1")
        assert await repo.turn_count(_CONVO_USER) == 1

    async def test_save_summary_then_get_returns_it(self) -> None:
        repo = InMemoryConversationRepository()
        await repo.save_summary(_CONVO_USER, "the summary")
        assert await repo.get_summary(_CONVO_USER) == "the summary"

    async def test_clear_removes_turns_and_summary(self) -> None:
        repo = InMemoryConversationRepository()
        await repo.save_turn(_CONVO_USER, "q1", "a1")
        await repo.save_summary(_CONVO_USER, "summary")
        await repo.clear(_CONVO_USER)
        assert await repo.all_turns(_CONVO_USER) == []
        assert await repo.get_summary(_CONVO_USER) is None
```

Add the imports at the top of `tests/shared/test_repositories.py`:

```python
from classiflow.database.repositories.conversation import (
    InMemoryConversationRepository,
    SqlConversationRepository,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/shared/test_repositories.py -k Conversation -v`
Expected: collection error (`ModuleNotFoundError`) since neither module exists yet.

- [ ] **Step 3: Implement the Protocol**

Create `src/classiflow/domain/repositories/conversation.py`:

```python
from typing import Protocol

from classiflow.database.models import ConversationTurn


class IConversationRepository(Protocol):
    async def save_turn(self, user_email: str, question: str, answer: str) -> None: ...

    # Both methods return oldest-first (ascending created_at): recent_turns so the
    # history block prints in natural reading order, all_turns so MemoryService can
    # index the turn that just aged out of the raw window.
    async def recent_turns(self, user_email: str, limit: int) -> list[ConversationTurn]: ...

    async def all_turns(self, user_email: str) -> list[ConversationTurn]: ...

    async def turn_count(self, user_email: str) -> int: ...

    async def get_summary(self, user_email: str) -> str | None: ...

    async def save_summary(self, user_email: str, summary_text: str) -> None: ...

    async def clear(self, user_email: str) -> None: ...
```

- [ ] **Step 4: Implement `SqlConversationRepository`**

Create `src/classiflow/database/repositories/conversation.py`:

```python
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.database.models import ConversationSummary, ConversationTurn


class SqlConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_turn(self, user_email: str, question: str, answer: str) -> None:
        self._session.add(ConversationTurn(user_email=user_email, question=question, answer=answer))
        await self._session.flush()

    async def recent_turns(self, user_email: str, limit: int) -> list[ConversationTurn]:
        result = await self._session.execute(
            select(ConversationTurn)
            .where(ConversationTurn.user_email == user_email)
            .order_by(ConversationTurn.created_at.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def all_turns(self, user_email: str) -> list[ConversationTurn]:
        result = await self._session.execute(
            select(ConversationTurn)
            .where(ConversationTurn.user_email == user_email)
            .order_by(ConversationTurn.created_at.asc())
        )
        return list(result.scalars().all())

    async def turn_count(self, user_email: str) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(ConversationTurn)
            .where(ConversationTurn.user_email == user_email)
        )
        return result.scalar_one()

    async def get_summary(self, user_email: str) -> str | None:
        result = await self._session.execute(
            select(ConversationSummary).where(ConversationSummary.user_email == user_email)
        )
        row = result.scalar_one_or_none()
        return row.summary_text if row is not None else None

    async def save_summary(self, user_email: str, summary_text: str) -> None:
        existing = await self._session.execute(
            select(ConversationSummary).where(ConversationSummary.user_email == user_email)
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            row.summary_text = summary_text
        else:
            self._session.add(ConversationSummary(user_email=user_email, summary_text=summary_text))
        await self._session.flush()

    async def clear(self, user_email: str) -> None:
        await self._session.execute(
            delete(ConversationTurn).where(ConversationTurn.user_email == user_email)
        )
        await self._session.execute(
            delete(ConversationSummary).where(ConversationSummary.user_email == user_email)
        )
        await self._session.flush()


class InMemoryConversationRepository:
    def __init__(self) -> None:
        self._turns: dict[str, list[ConversationTurn]] = {}
        self._summaries: dict[str, str] = {}

    async def save_turn(self, user_email: str, question: str, answer: str) -> None:
        self._turns.setdefault(user_email, []).append(
            ConversationTurn(user_email=user_email, question=question, answer=answer)
        )

    async def recent_turns(self, user_email: str, limit: int) -> list[ConversationTurn]:
        return self._turns.get(user_email, [])[-limit:]

    async def all_turns(self, user_email: str) -> list[ConversationTurn]:
        return list(self._turns.get(user_email, []))

    async def turn_count(self, user_email: str) -> int:
        return len(self._turns.get(user_email, []))

    async def get_summary(self, user_email: str) -> str | None:
        return self._summaries.get(user_email)

    async def save_summary(self, user_email: str, summary_text: str) -> None:
        self._summaries[user_email] = summary_text

    async def clear(self, user_email: str) -> None:
        self._turns.pop(user_email, None)
        self._summaries.pop(user_email, None)
```

Note on `recent_turns`'s SQL implementation: it orders descending + `LIMIT`, then reverses in
Python to get "last N, oldest-first" — mirrors the common pattern for this exact query shape and
avoids a slower `ORDER BY ... DESC LIMIT n` subquery re-sorted ascending.

- [ ] **Step 5: Register the re-export**

In `src/classiflow/domain/repositories/__init__.py`, add `IConversationRepository` to the imports
and `__all__` list (follow the exact existing pattern for `IDocumentKbRepository` in that file).

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/shared/test_repositories.py -k Conversation -v`
Expected: all new tests PASS.

- [ ] **Step 7: Run lint and typecheck**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: clean.

- [ ] **Step 8: Commit** — only when the user explicitly authorizes it.

---

### Task 3: `MemoryService` + summary prompt module

**Files:**
- Create: `src/classiflow/knowledge/memory/__init__.py`
- Create: `src/classiflow/knowledge/memory/service.py`
- Create: `src/classiflow/knowledge/prompts/memory.py`
- Create: `tests/knowledge/test_memory_service.py`

**Interfaces:**
- Consumes: `IConversationRepository` (Task 2), `ChatLlm` (existing,
  `src/classiflow/knowledge/llm/chat_llm.py`).
- Produces: `ConversationHistory` dataclass, `MemoryService` with `load`/`record_turn`/`clear`.
  Consumed by Task 4 (`build_user_prompt`), Task 5 (`ChatService`), Task 6 (routes/DI).

- [ ] **Step 1: Write the failing tests**

Create `tests/knowledge/test_memory_service.py`:

```python
from classiflow.database.models import ConversationTurn
from classiflow.database.repositories.conversation import InMemoryConversationRepository
from classiflow.knowledge.memory.service import MemoryService, RAW_WINDOW_SIZE

_USER = "memory-user@classiflow.dev"


class _StubChatLlm:
    def __init__(self, response: str = "stubbed summary") -> None:
        self._response = response
        self.calls: list[tuple[str, str]] = []

    async def astream(self, system: str, user: str):
        self.calls.append((system, user))
        yield self._response


class TestMemoryServiceLoad:
    async def test_returns_empty_history_for_a_new_user(self) -> None:
        service = MemoryService(repo=InMemoryConversationRepository(), chat_llm=_StubChatLlm())
        history = await service.load(_USER)
        assert history.summary is None
        assert history.recent_turns == []

    async def test_returns_summary_and_recent_turns(self) -> None:
        repo = InMemoryConversationRepository()
        await repo.save_turn(_USER, "q1", "a1")
        await repo.save_summary(_USER, "prior summary")
        service = MemoryService(repo=repo, chat_llm=_StubChatLlm())
        history = await service.load(_USER)
        assert history.summary == "prior summary"
        assert len(history.recent_turns) == 1

    async def test_caps_recent_turns_at_the_raw_window_size(self) -> None:
        repo = InMemoryConversationRepository()
        for i in range(RAW_WINDOW_SIZE + 3):
            await repo.save_turn(_USER, f"q{i}", f"a{i}")
        service = MemoryService(repo=repo, chat_llm=_StubChatLlm())
        history = await service.load(_USER)
        assert len(history.recent_turns) == RAW_WINDOW_SIZE


class TestMemoryServiceRecordTurn:
    async def test_saves_the_turn(self) -> None:
        repo = InMemoryConversationRepository()
        service = MemoryService(repo=repo, chat_llm=_StubChatLlm())
        await service.record_turn(_USER, "q1", "a1")
        turns = await repo.all_turns(_USER)
        assert len(turns) == 1
        assert turns[0].question == "q1"

    async def test_does_not_summarize_while_under_the_window(self) -> None:
        repo = InMemoryConversationRepository()
        llm = _StubChatLlm()
        service = MemoryService(repo=repo, chat_llm=llm)
        for i in range(RAW_WINDOW_SIZE):
            await service.record_turn(_USER, f"q{i}", f"a{i}")
        assert llm.calls == []
        assert await repo.get_summary(_USER) is None

    async def test_summarizes_the_aging_out_turn_once_the_window_overflows(self) -> None:
        repo = InMemoryConversationRepository()
        llm = _StubChatLlm(response="new summary")
        service = MemoryService(repo=repo, chat_llm=llm)
        for i in range(RAW_WINDOW_SIZE):
            await service.record_turn(_USER, f"q{i}", f"a{i}")
        await service.record_turn(_USER, "q-overflow", "a-overflow")

        assert len(llm.calls) == 1
        _system, user_prompt = llm.calls[0]
        assert "q0" in user_prompt  # the oldest turn is the one that ages out
        assert await repo.get_summary(_USER) == "new summary"

    async def test_a_summarization_failure_does_not_lose_the_saved_turn(self) -> None:
        class _FailingChatLlm:
            async def astream(self, system: str, user: str):
                raise RuntimeError("model unavailable")
                yield ""  # pragma: no cover - unreachable, satisfies async generator shape

        repo = InMemoryConversationRepository()
        service = MemoryService(repo=repo, chat_llm=_FailingChatLlm())
        for i in range(RAW_WINDOW_SIZE):
            await service.record_turn(_USER, f"q{i}", f"a{i}")
        await service.record_turn(_USER, "q-overflow", "a-overflow")

        turns = await repo.all_turns(_USER)
        assert len(turns) == RAW_WINDOW_SIZE + 1
        assert await repo.get_summary(_USER) is None


class TestMemoryServiceClear:
    async def test_clears_turns_and_summary(self) -> None:
        repo = InMemoryConversationRepository()
        service = MemoryService(repo=repo, chat_llm=_StubChatLlm())
        await service.record_turn(_USER, "q1", "a1")
        await service.clear(_USER)
        assert await repo.all_turns(_USER) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/knowledge/test_memory_service.py -v`
Expected: collection error (`ModuleNotFoundError`).

- [ ] **Step 3: Create the empty package `__init__.py`**

Create `src/classiflow/knowledge/memory/__init__.py` — empty except for a module docstring line,
matching the eager-import-avoidance convention already documented in `knowledge/__init__.py` (no
executable statements, per this repo's `__init__.py` rule).

- [ ] **Step 4: Create the summary prompt module**

Create `src/classiflow/knowledge/prompts/memory.py`:

```python
SUMMARY_SYSTEM_PROMPT = (
    "Resumís conversaciones para dar contexto a un asistente. Sé breve y concreto: "
    "conservá nombres propios, números de decreto/ordenanza, fechas y temas puntuales "
    "mencionados. No inventes información que no esté en el resumen anterior ni en el "
    "nuevo intercambio."
)


def build_summary_prompt(old_summary: str, question: str, answer: str) -> str:
    summary_block = old_summary or "(sin resumen previo)"
    return (
        f"Resumen anterior:\n{summary_block}\n\n"
        f"Nuevo intercambio:\nP: {question}\nR: {answer}\n\n"
        "Resumen actualizado (incorporá el nuevo intercambio al resumen anterior):"
    )
```

- [ ] **Step 5: Implement `MemoryService`**

Create `src/classiflow/knowledge/memory/service.py`:

```python
import logging
from dataclasses import dataclass

from classiflow.database.models import ConversationTurn
from classiflow.domain.repositories.conversation import IConversationRepository
from classiflow.knowledge.llm.chat_llm import ChatLlm
from classiflow.knowledge.prompts.memory import SUMMARY_SYSTEM_PROMPT, build_summary_prompt

RAW_WINDOW_SIZE = 6

logger = logging.getLogger(__name__)


@dataclass
class ConversationHistory:
    summary: str | None
    recent_turns: list[ConversationTurn]


class MemoryService:
    def __init__(self, repo: IConversationRepository, chat_llm: ChatLlm) -> None:
        self._repo = repo
        self._chat_llm = chat_llm

    async def load(self, user_email: str) -> ConversationHistory:
        summary = await self._repo.get_summary(user_email)
        recent = await self._repo.recent_turns(user_email, RAW_WINDOW_SIZE)
        return ConversationHistory(summary=summary, recent_turns=recent)

    async def record_turn(self, user_email: str, question: str, answer: str) -> None:
        await self._repo.save_turn(user_email, question, answer)
        count = await self._repo.turn_count(user_email)
        if count <= RAW_WINDOW_SIZE:
            return
        turns = await self._repo.all_turns(user_email)
        aging_out = turns[-(RAW_WINDOW_SIZE + 1)]
        try:
            new_summary = await self._summarize(user_email, aging_out)
        except Exception:
            # The raw turn is already saved -- a failed fold-in only delays the
            # summary update; it will retry the next time a turn ages out.
            logger.exception("Failed to fold conversation turn into summary")
            return
        await self._repo.save_summary(user_email, new_summary)

    async def _summarize(self, user_email: str, turn: ConversationTurn) -> str:
        old_summary = await self._repo.get_summary(user_email) or ""
        prompt = build_summary_prompt(old_summary, turn.question, turn.answer)
        parts = [tok async for tok in self._chat_llm.astream(SUMMARY_SYSTEM_PROMPT, prompt)]
        return "".join(parts).strip()

    async def clear(self, user_email: str) -> None:
        await self._repo.clear(user_email)
```

Note on the broad `except Exception`: this matches the same pattern already used in
`services/pipeline/service.py`'s `index_enriched_record` (`except KnowledgeError` there is
narrower because indexing only raises that one type; here `ChatLlm.astream` can raise any
`ChatLlmError` subclass, but a defensive catch-all is intentional at this specific boundary
because a summarization failure must never propagate and turn a successful answer into a 500 —
the user's turn is already durably saved by the time this runs).

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/knowledge/test_memory_service.py -v`
Expected: all PASS.

- [ ] **Step 7: Run lint and typecheck**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: clean. If `BLE001` (blind except) flags the `except Exception` in `record_turn`, that is
expected and intentional per the note above — do not add a `noqa`; if ruff blocks it, narrow to
catching `Exception` is still required by design here, so confirm with the user before changing
approach (this repo's `no # noqa suppressions` rule applies. If a lint failure blocks progress,
stop and flag it rather than adding a suppression).

- [ ] **Step 8: Commit** — only when the user explicitly authorizes it.

---

### Task 4: Wire history into `build_user_prompt`

**Files:**
- Modify: `src/classiflow/knowledge/prompts/chat.py`
- Create: `tests/knowledge/test_prompts.py` (confirmed not to exist yet — `build_user_prompt`'s
  no-history behavior is currently only exercised indirectly through
  `tests/knowledge/test_retrieval_and_chat.py`'s `ChatService` tests)

**Interfaces:**
- Consumes: `ConversationHistory` (Task 3).
- Produces: `build_user_prompt(question, chunks, history=None)` — the `history` param is new and
  optional, defaulting to `None` so every existing caller/test is unaffected. Consumed by Task 5's
  `ChatService`.

- [ ] **Step 1: Write the failing tests**

Create `tests/knowledge/test_prompts.py`:

```python
from classiflow.knowledge.domain.chat import RetrievedChunk
from classiflow.knowledge.domain.chunk import StoreMetadata
from classiflow.knowledge.memory.service import ConversationHistory
from classiflow.database.models import ConversationTurn
from classiflow.knowledge.prompts.chat import build_user_prompt

_CHUNK = RetrievedChunk(
    chunk_id="c1",
    text="El decreto 810/2026 establece...",
    score=0.9,
    metadata=StoreMetadata(doc_type="Decreto", number="810", year="2026", filename="d.pdf"),
)


class TestBuildUserPromptWithoutHistory:
    def test_matches_existing_behavior_when_history_is_none(self) -> None:
        prompt = build_user_prompt("pregunta", [_CHUNK])
        assert "Contexto de la conversación" not in prompt
        assert "Pasajes:" in prompt
        assert "Pregunta: pregunta" in prompt

    def test_matches_existing_behavior_when_history_is_empty(self) -> None:
        empty_history = ConversationHistory(summary=None, recent_turns=[])
        with_none = build_user_prompt("pregunta", [_CHUNK])
        with_empty = build_user_prompt("pregunta", [_CHUNK], history=empty_history)
        assert with_none == with_empty


class TestBuildUserPromptWithHistory:
    def test_includes_the_summary(self) -> None:
        history = ConversationHistory(summary="resumen previo", recent_turns=[])
        prompt = build_user_prompt("pregunta", [_CHUNK], history=history)
        assert "resumen previo" in prompt

    def test_includes_recent_turns_in_order(self) -> None:
        turns = [
            ConversationTurn(user_email="u", question="q1", answer="a1"),
            ConversationTurn(user_email="u", question="q2", answer="a2"),
        ]
        history = ConversationHistory(summary=None, recent_turns=turns)
        prompt = build_user_prompt("pregunta", [_CHUNK], history=history)
        assert prompt.index("q1") < prompt.index("q2")
        assert "q1" in prompt and "a1" in prompt

    def test_history_block_appears_before_passages(self) -> None:
        history = ConversationHistory(summary="s", recent_turns=[])
        prompt = build_user_prompt("pregunta", [_CHUNK], history=history)
        assert prompt.index("Contexto de la conversación") < prompt.index("Pasajes:")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/knowledge/test_prompts.py -v`
Expected: `TypeError: build_user_prompt() got an unexpected keyword argument 'history'` (or similar)
on the history tests; the no-history tests should already PASS since they match current behavior.

- [ ] **Step 3: Implement the change**

In `src/classiflow/knowledge/prompts/chat.py`, add the import and modify `build_user_prompt`:

```python
from classiflow.knowledge.memory.service import ConversationHistory
```

Replace the existing `build_user_prompt` function with:

```python
def build_user_prompt(
    question: str,
    chunks: list[RetrievedChunk],
    history: ConversationHistory | None = None,
) -> str:
    parts = []
    if history is not None and (history.summary or history.recent_turns):
        parts.append(_history_block(history))
    if not chunks:
        context = _NO_CONTEXT
    else:
        context = "\n\n".join(starmap(_passage, enumerate(chunks, start=1)))
    parts.append(f"Pasajes:\n{context}\n\nPregunta: {question}\n\nRespuesta:")
    return "\n\n".join(parts)


def _history_block(history: ConversationHistory) -> str:
    lines = ["Contexto de la conversación:"]
    if history.summary:
        lines.append(f"Resumen de intercambios anteriores: {history.summary}")
    for turn in history.recent_turns:
        lines.append(f"P: {turn.question}\nR: {turn.answer}")
    return "\n".join(lines)
```

Note: importing `ConversationHistory` from `knowledge.memory.service` into `knowledge.prompts.chat`
does not create a circular import — `memory/service.py` does not import anything from
`prompts/chat.py` (it imports `prompts/memory.py` instead), so this is a normal one-directional
dependency; do not use `TYPE_CHECKING` here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/knowledge/test_prompts.py -v`
Expected: all PASS.

Run: `uv run pytest tests/knowledge -v` (full knowledge test dir)
Expected: all PASS — confirms no existing caller of `build_user_prompt` broke.

- [ ] **Step 5: Run lint and typecheck**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: clean.

- [ ] **Step 6: Commit** — only when the user explicitly authorizes it.

---

### Task 5: Wire `history`/`record_turn` into `ChatService` and the chat routes

**Files:**
- Modify: `src/classiflow/knowledge/chat/service.py`
- Modify: `src/classiflow/api/routes/knowledge/endpoints.py`
- Modify: `tests/knowledge/test_retrieval_and_chat.py` (or wherever `ChatService` is currently
  tested — locate with `grep -rl "class ChatService" tests/` first if the filename differs)
- Modify: `tests/api/routes/test_knowledge.py`

**Interfaces:**
- Consumes: `MemoryService`, `ConversationHistory` (Task 3), `build_user_prompt` with `history`
  (Task 4).
- Produces: `ChatService.astream`/`.answer` gain `history: ConversationHistory | None = None`.
  `POST /knowledge/chat` and `POST /knowledge/chat/stream` now call `memory_service.load()` before
  answering and `memory_service.record_turn()` after. Consumed by Task 6's DI wiring (which
  supplies the `MemoryService` instance these routes depend on).

- [ ] **Step 1: Read the current `ChatService` test file**

The existing tests live in `tests/knowledge/test_retrieval_and_chat.py`. It already has a
`FakeChatLlm` helper (`tests/knowledge/fakes.py`) that records `last_system`/`last_user` on every
`astream` call, a `_chat(store, llm, top_k)` constructor helper, and a `TestChatService` class with
`test_answer_returns_text_and_sources`, `test_prompt_carries_the_retrieved_passages`, etc. — this
task adds to `TestChatService`, following its exact existing style.

- [ ] **Step 2: Write the failing tests for `ChatService`**

Add to `tests/knowledge/test_retrieval_and_chat.py`'s `TestChatService` class:

```python
async def test_answer_passes_history_into_the_prompt(
    self, indexer: IndexerService, store: InMemoryVectorStore
) -> None:
    await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", TEXT, FAKE_ENTITIES)
    llm = FakeChatLlm()
    history = ConversationHistory(
        summary=None,
        recent_turns=[ConversationTurn(user_email="u", question="prior q", answer="prior a")],
    )

    await _chat(store, llm, top_k=2).answer(
        ChatQuery(question="¿Cuál es el presupuesto?"), history=history
    )

    assert "prior q" in llm.last_user
    assert "prior a" in llm.last_user


async def test_astream_passes_history_into_the_prompt(
    self, indexer: IndexerService, store: InMemoryVectorStore
) -> None:
    await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", TEXT, FAKE_ENTITIES)
    llm = FakeChatLlm()
    history = ConversationHistory(summary="resumen de contexto", recent_turns=[])

    async for _ in _chat(store, llm, top_k=2).astream(
        ChatQuery(question="¿Cuál es el presupuesto?"), history=history
    ):
        pass

    assert "resumen de contexto" in llm.last_user


async def test_history_defaults_to_none_and_matches_existing_behavior(
    self, indexer: IndexerService, store: InMemoryVectorStore
) -> None:
    await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", TEXT, FAKE_ENTITIES)
    llm = FakeChatLlm()

    await _chat(store, llm, top_k=2).answer(ChatQuery(question="¿Cuál es el presupuesto?"))

    assert "Contexto de la conversación" not in llm.last_user
```

Add the new imports at the top of the file:

```python
from classiflow.database.models import ConversationTurn
from classiflow.knowledge.memory.service import ConversationHistory
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/knowledge/test_retrieval_and_chat.py -k History -v`
Expected: `TypeError` on the `history=` kwarg (method doesn't accept it yet).

- [ ] **Step 4: Update `ChatService`**

In `src/classiflow/knowledge/chat/service.py`, add the import and update both methods:

```python
from classiflow.knowledge.memory.service import ConversationHistory
```

```python
async def answer(self, query: ChatQuery, history: ConversationHistory | None = None) -> ChatAnswer:
    chunks = await self._retriever.retrieve(query)
    user_prompt = build_user_prompt(query.question, chunks, history=history)
    parts = [token async for token in self._chat_llm.astream(SYSTEM_PROMPT, user_prompt)]
    return ChatAnswer(
        answer="".join(parts).strip(),
        sources=[chunk.to_source() for chunk in chunks],
    )


async def astream(
    self, query: ChatQuery, history: ConversationHistory | None = None
) -> AsyncIterator[tuple[str, list[SourceRef]]]:
    chunks = await self._retriever.retrieve(query)
    sources = [chunk.to_source() for chunk in chunks]
    user_prompt = build_user_prompt(query.question, chunks, history=history)
    async for token in self._chat_llm.astream(SYSTEM_PROMPT, user_prompt):
        yield token, sources
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/knowledge/test_retrieval_and_chat.py -v` (the whole file, to confirm no
regression on existing `.answer`/`.astream` tests that don't pass `history`).
Expected: all PASS.

- [ ] **Step 6: Write the failing route tests**

In `tests/api/routes/test_knowledge.py`, find this file's existing `TestChatEndpoint` /
`TestChatStreamEndpoint` classes (or equivalent) and add:

```python
class TestChatPersistsHistory:
    def test_chat_stream_persists_a_turn_after_completing(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/knowledge/chat/stream", json={"question": "hola"}, headers=auth_headers
        )
        assert response.status_code == HTTPStatus.OK
        # Drain the stream so the post-stream record_turn() call actually runs.
        _ = response.text

        history_response = client.get("/knowledge/conversation", headers=auth_headers)
        assert history_response.status_code == HTTPStatus.OK
        turns = history_response.json()["turns"]
        assert len(turns) == 1
        assert turns[0]["question"] == "hola"

    def test_chat_uses_prior_history_in_the_next_prompt(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # First turn establishes history.
        first = client.post(
            "/knowledge/chat/stream", json={"question": "primera pregunta"}, headers=auth_headers
        )
        _ = first.text

        # Capture the prompt the stub ChatLlm receives on the second call -- this
        # depends on TestContainer's stub chat_llm exposing captured calls; follow
        # whatever introspection hook injections/test.py's _StubChatLlm already
        # exposes (check that class before writing the exact assertion).
        second = client.post(
            "/knowledge/chat/stream", json={"question": "segunda pregunta"}, headers=auth_headers
        )
        assert second.status_code == HTTPStatus.OK
```

Note for the implementer: `_StubChatLlm` in `injections/test.py` must be checked for whether it
already records the prompts it was called with; if not, this task must add that capability to it
(a `self.received_prompts: list[str]` list appended to in its `astream`), since this is the only
way to assert history actually reached the LLM in a route-level (not unit-level) test. Keep this
addition minimal and consistent with the stub's existing style.

- [ ] **Step 7: Run tests to verify they fail**

Run: `uv run pytest tests/api/routes/test_knowledge.py -k Persist -v`
Expected: FAIL — `/knowledge/conversation` doesn't exist yet (404), and `ChatService` isn't yet
wired to a `MemoryService` in the route.

- [ ] **Step 8: Wire `MemoryService` into the chat routes**

This step depends on Task 6's `get_memory_service` dependency function existing. If Task 6 has not
been done yet, do Task 6's Steps 1-4 (DI wiring only, no route changes) first, then return here.

In `src/classiflow/api/routes/knowledge/endpoints.py`, add the import and update both chat routes:

```python
from classiflow.knowledge.memory.service import MemoryService
```

Add `get_memory_service` to the existing `from classiflow.api.dependencies import (...)` block.

Replace the `chat` and `chat_stream` functions:

```python
@router.post("/chat")
async def chat(
    body: ChatRequest,
    current_user: CurrentUser,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> ChatResponse:
    history = await memory_service.load(current_user.email)
    answer = await chat_service.answer(_to_query(body), history=history)
    await memory_service.record_turn(current_user.email, body.question, answer.answer)
    return ChatResponse.from_domain(answer)


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    current_user: CurrentUser,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> StreamingResponse:
    history = await memory_service.load(current_user.email)

    async def _stream() -> AsyncGenerator[str, None]:
        sources: list[SourceRef] = []
        answer_parts: list[str] = []
        async for token, current_sources in chat_service.astream(_to_query(body), history=history):
            sources = current_sources
            answer_parts.append(token)
            yield _sse("token", {"text": token})
        yield _sse("sources", _sources_payload(sources))
        yield _sse("done", {})
        await memory_service.record_turn(
            current_user.email, body.question, "".join(answer_parts).strip()
        )

    return StreamingResponse(_stream(), media_type="text/event-stream")
```

`CurrentUser` needs importing too — add it to the existing
`from classiflow.api.dependencies import (...)` block alongside `get_memory_service`.

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run pytest tests/api/routes/test_knowledge.py -v`
Expected: all PASS, including the new `TestChatPersistsHistory` tests (Task 6 must be complete for
`/knowledge/conversation` to exist — if not done yet, do Task 6 fully now, then return to this
step).

- [ ] **Step 10: Run lint and typecheck**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: clean.

- [ ] **Step 11: Commit** — only when the user explicitly authorizes it.

---

### Task 6: `/knowledge/conversation` endpoints + DI wiring

**Files:**
- Modify: `src/classiflow/api/routes/knowledge/schemas.py`
- Modify: `src/classiflow/api/routes/knowledge/endpoints.py`
- Modify: `src/classiflow/api/dependencies.py`
- Modify: `src/classiflow/injections/production.py`
- Modify: `src/classiflow/injections/test.py`
- Modify: `tests/api/conftest.py`
- Modify: `tests/api/routes/test_knowledge.py`

**Interfaces:**
- Consumes: `IConversationRepository` (Task 2), `MemoryService` (Task 3).
- Produces: `get_conversation_repo`, `get_memory_service` dependency functions;
  `GET /knowledge/conversation`, `DELETE /knowledge/conversation`. `get_memory_service` is
  consumed by Task 5's chat routes.

- [ ] **Step 1: Add DI wiring in `injections/production.py`**

`SqlConversationRepository` needs a per-request session, so it does **not** go into the
`Container` — only `chat_llm` (already a Container singleton) is needed from there. No change to
this file is needed beyond confirming `chat_llm` is already exposed (it is — see the existing
`chat_service` provider). Skip to Step 2.

- [ ] **Step 2: Add `_InMemoryConversationRepository`-based test wiring**

In `src/classiflow/injections/test.py`, add the import:

```python
from classiflow.database.repositories.conversation import InMemoryConversationRepository
```

Add a `conversation_repo` provider to `TestContainer`, alongside the existing
`document_kb_repo = providers.Singleton(InMemoryDocumentKbRepository)` line:

```python
    conversation_repo = providers.Singleton(InMemoryConversationRepository)
```

Also check `_StubChatLlm`'s current implementation (`grep -n "class _StubChatLlm" -A 15
src/classiflow/injections/test.py`) — per Task 5 Step 6's note, add a `received_prompts: list[str]`
list to it if not already present, appending each call's `user` argument in `astream`, so route
tests can assert what prompt the stub received.

- [ ] **Step 3: Add `get_conversation_repo` and `get_memory_service` to `api/dependencies.py`**

Add the imports:

```python
from classiflow.database.repositories.conversation import SqlConversationRepository
from classiflow.domain.repositories.conversation import IConversationRepository
from classiflow.knowledge.memory.service import MemoryService
```

Add, next to the existing `get_document_kb_repo`:

```python
def get_conversation_repo(session: DbSession) -> IConversationRepository:
    return SqlConversationRepository(session)
```

Add, next to the existing `get_chat_service`:

```python
@inject
def get_memory_service(
    conversation_repo: Annotated[IConversationRepository, Depends(get_conversation_repo)],
    chat_llm: Annotated[ChatLlm, Depends(Provide[Container.chat_llm])],
) -> MemoryService:
    return MemoryService(repo=conversation_repo, chat_llm=chat_llm)
```

(`ChatLlm` is already imported in this file for `get_chat_service` — confirm before adding a
duplicate import.)

- [ ] **Step 4: Register `get_conversation_repo` in `tests/api/conftest.py`**

Add, alongside the existing `app.dependency_overrides[get_document_kb_repo] = ...` line:

```python
    app.dependency_overrides[get_conversation_repo] = _override(test_container.conversation_repo)
```

Add `get_conversation_repo` to this file's existing
`from classiflow.api.dependencies import (...)` block.

- [ ] **Step 5: Add the schemas**

In `src/classiflow/api/routes/knowledge/schemas.py`, add the import and new schemas:

```python
from classiflow.database.models import ConversationTurn
```

```python
class ConversationTurnSchema(BaseSchema):
    question: str
    answer: str
    created_at: datetime

    @classmethod
    def from_model(cls, turn: ConversationTurn) -> "ConversationTurnSchema":
        return cls(question=turn.question, answer=turn.answer, created_at=turn.created_at)


class ConversationResponse(BaseSchema):
    summary: str | None
    turns: list[ConversationTurnSchema]
```

- [ ] **Step 6: Write the failing tests**

In `tests/api/routes/test_knowledge.py`, add:

```python
class TestConversationEndpoint:
    def test_get_requires_auth(self, client: TestClient) -> None:
        response = client.get("/knowledge/conversation")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_get_returns_empty_history_for_a_new_user(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/knowledge/conversation", headers=auth_headers)
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["summary"] is None
        assert body["turns"] == []

    def test_delete_requires_auth(self, client: TestClient) -> None:
        response = client.delete("/knowledge/conversation")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_delete_clears_history(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        client.post("/knowledge/chat/stream", json={"question": "hola"}, headers=auth_headers).text
        before = client.get("/knowledge/conversation", headers=auth_headers).json()
        assert len(before["turns"]) == 1

        delete_response = client.delete("/knowledge/conversation", headers=auth_headers)
        assert delete_response.status_code == HTTPStatus.NO_CONTENT

        after = client.get("/knowledge/conversation", headers=auth_headers).json()
        assert after["turns"] == []
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `uv run pytest tests/api/routes/test_knowledge.py -k Conversation -v`
Expected: 404 on both routes (not registered yet).

- [ ] **Step 8: Implement the routes**

In `src/classiflow/api/routes/knowledge/endpoints.py`, add the import
(`ConversationResponse`, `ConversationTurnSchema` to the existing schemas import block;
`get_conversation_repo` to the dependencies import block; `IConversationRepository` from
`classiflow.domain.repositories.conversation`) and the two routes:

```python
@router.get("/conversation")
async def get_conversation(
    current_user: CurrentUser,
    conversation_repo: Annotated[IConversationRepository, Depends(get_conversation_repo)],
) -> ConversationResponse:
    turns = await conversation_repo.all_turns(current_user.email)
    summary = await conversation_repo.get_summary(current_user.email)
    return ConversationResponse(
        summary=summary,
        turns=[ConversationTurnSchema.from_model(t) for t in turns],
    )


@router.delete("/conversation", status_code=HTTPStatus.NO_CONTENT)
async def clear_conversation(
    current_user: CurrentUser,
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> None:
    await memory_service.clear(current_user.email)
```

Note: `get_conversation` reads directly from the repository (not through `MemoryService.load()`,
which caps at `RAW_WINDOW_SIZE`) because this endpoint must return the user's **full** history for
display, not just the model's prompting window — see spec Decision 7.

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run pytest tests/api/routes/test_knowledge.py -v` (whole file)
Expected: all PASS, including Task 5's `TestChatPersistsHistory` tests (now that
`/knowledge/conversation` exists).

- [ ] **Step 10: Run the full backend gate**

Run: `uv run poe check`
Expected: all steps pass — lint, typecheck, full pytest suite (including every new test from
Tasks 1-6), full pre-commit suite.

- [ ] **Step 11: Commit** — only when the user explicitly authorizes it.

---

### Task 7: Frontend — load history on mount + "Clear conversation" button

**Files:**
- Modify: `src/classiflow/frontend/src/api/knowledge.ts`
- Modify: `src/classiflow/frontend/src/pages/ChatPage.tsx`
- Modify: `src/classiflow/frontend/src/pages/ChatPage.test.tsx`

**Interfaces:**
- Consumes: `GET`/`DELETE /knowledge/conversation` (Task 6).
- Produces: `fetchConversation()`, `clearConversation()` in `api/knowledge.ts`. No new exports
  from `ChatPage.tsx` — same default export.

- [ ] **Step 1: Add the API client functions**

In `src/classiflow/frontend/src/api/knowledge.ts`, add:

```ts
export interface ConversationTurnRecord {
  question: string;
  answer: string;
  createdAt: string;
}

export interface ConversationResponse {
  summary: string | null;
  turns: ConversationTurnRecord[];
}

export async function fetchConversation(): Promise<ConversationResponse> {
  const response = await apiFetch("/knowledge/conversation");
  if (!response.ok) {
    throw new Error(`GET /knowledge/conversation failed: ${response.status}`);
  }
  return response.json();
}

export async function clearConversation(): Promise<void> {
  const response = await apiFetch("/knowledge/conversation", { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`DELETE /knowledge/conversation failed: ${response.status}`);
  }
}
```

- [ ] **Step 2: Write the failing frontend tests**

In `src/classiflow/frontend/src/pages/ChatPage.test.tsx`, add:

```tsx
it("loads and renders prior conversation history on mount", async () => {
  vi.spyOn(knowledgeApi, "warmupChat").mockResolvedValue();
  vi.spyOn(knowledgeApi, "fetchConversation").mockResolvedValue({
    summary: null,
    turns: [{ question: "pregunta previa", answer: "respuesta previa", createdAt: "2026-01-01" }],
  });

  render(<ChatPage />);

  await waitFor(() => expect(screen.getByText("pregunta previa")).toBeInTheDocument());
  expect(screen.getByText("respuesta previa")).toBeInTheDocument();
});

it("clears the visible history when Clear conversation is clicked", async () => {
  vi.spyOn(knowledgeApi, "warmupChat").mockResolvedValue();
  vi.spyOn(knowledgeApi, "fetchConversation").mockResolvedValue({
    summary: null,
    turns: [{ question: "pregunta previa", answer: "respuesta previa", createdAt: "2026-01-01" }],
  });
  const clearSpy = vi.spyOn(knowledgeApi, "clearConversation").mockResolvedValue();

  render(<ChatPage />);
  await waitFor(() => expect(screen.getByText("pregunta previa")).toBeInTheDocument());

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /clear conversation/i }));
  });

  expect(clearSpy).toHaveBeenCalledTimes(1);
  expect(screen.queryByText("pregunta previa")).not.toBeInTheDocument();
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd src/classiflow/frontend && npm run test -- ChatPage`
Expected: FAIL — `fetchConversation` isn't called on mount yet, no "Clear conversation" button
exists yet.

- [ ] **Step 4: Implement the change**

In `src/classiflow/frontend/src/pages/ChatPage.tsx`:

Update the import line:

```tsx
import { warmupChat, fetchConversation, clearConversation } from "../api/knowledge";
```

Add a history-loading effect alongside the existing warmup effect:

```tsx
  useEffect(() => {
    warmupChat().catch(() => {});
    fetchConversation()
      .then((history) => {
        const loaded: Message[] = history.turns.flatMap((turn) => [
          { role: "user" as const, content: turn.question },
          { role: "assistant" as const, content: turn.answer },
        ]);
        setMessages(loaded);
      })
      .catch(() => {});
  }, []);
```

Add a clear handler and button. Add the handler function near `handleSend`:

```tsx
  async function handleClear(): Promise<void> {
    await clearConversation().catch(() => {});
    setMessages([]);
  }
```

Add the button in the input row, next to the Send button:

```tsx
        <button
          onClick={handleClear}
          disabled={isStreaming}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-2 text-base font-semibold text-[var(--color-text-muted)] disabled:opacity-50"
        >
          Clear conversation
        </button>
```

(Place it before or after the existing Send button in the same `<div className="mt-4 flex gap-2">`
row — matches the existing inline-button convention used elsewhere, e.g. "Sync Knowledge Base" on
the Classification page.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd src/classiflow/frontend && npm run test -- ChatPage`
Expected: all PASS, including the two new tests and the two pre-existing ones.

- [ ] **Step 6: Run the full frontend gate**

Run: `cd src/classiflow/frontend && npx tsc -b && npm run lint && npm run test`
Expected: all clean.

- [ ] **Step 7: Commit** — only when the user explicitly authorizes it.

---

### Task 8: Whole-feature verification pass

**Files:** none — verification only.

- [ ] **Step 1: Full backend gate**

Run: `uv run poe check`
Expected: all steps pass (lint, typecheck, full pytest suite including every test added in
Tasks 1-6, full pre-commit suite).

- [ ] **Step 2: Full frontend gate**

Run: `cd src/classiflow/frontend && npx tsc -b && npm run lint && npm run test`
Expected: all clean.

- [ ] **Step 3: Migration check**

Copy `data/classiflow.db` to a scratch file and run `uv run alembic upgrade head` against it via a
`DATABASE_URL` override (matching how the KB migrations were previously verified), confirming
`0013` applies cleanly on top of the current schema. Delete the scratch copy afterward — never
touch the real `data/classiflow.db` directly for this check.

- [ ] **Step 4: End-to-end manual walkthrough** — hand to the user (requires both servers live):
  ask a question, ask a follow-up that only makes sense with memory ("what about the second one?"
  after a multi-item answer), confirm the follow-up is answered correctly; refresh the page and
  confirm the full history reloads; click "Clear conversation" and confirm the page empties and a
  fresh question no longer references the cleared history; ask 7+ questions in one sitting and
  confirm the conversation still behaves sensibly once the raw window overflows (this is the one
  behavior that can't be verified by an automated test without a real or realistically-stubbed
  LLM, since it depends on genuine generation quality).

- [ ] **Step 5: Commit (only if Steps 1-4 surfaced fixes)** — only when the user explicitly
  authorizes it.
