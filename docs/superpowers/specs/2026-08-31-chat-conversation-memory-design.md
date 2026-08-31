# Chat Conversation Memory — Design Spec

## Status

Approved — ready for planning.

## Context

The Chat page (`ChatPage.tsx`, `POST /knowledge/chat/stream`) is fully stateless today: every
question is answered from scratch, using only the retrieved document passages
(`build_user_prompt`) and the fixed `SYSTEM_PROMPT`. There is no concept of "this user's prior
questions" anywhere in the system — refreshing the page loses the visible history, and even
within one page load, the backend never sees earlier turns when answering a new question. A
follow-up like "what about the second one?" cannot be answered correctly, because the model has
no way to know what "the second one" refers to.

This spec adds persisted, per-user conversation memory: prior turns are stored in the database,
included in the prompt for every new question (a recent-turns window plus a running summary of
older turns), and the Chat page loads a user's history on mount instead of always starting blank.

This is a new subsystem (two new tables, a new service, new endpoints, and a frontend history
load/clear flow) — architectural, not a bounded edit.

## Decisions

### 1. Conversation scope: one continuous conversation per user

There is no "conversation list" or "new chat" concept. Each signed-in user (identified by
`AllowedUser.email`, matching how every other per-user concept in this codebase is keyed) has
exactly one ongoing conversation that grows indefinitely. No conversation-selection UI, no
create/switch/rename endpoints.

**Rationale:** the rest of this app has no multi-session concept for any other feature (documents,
jobs); introducing one here would be a bigger UI/UX surface than this feature needs. If multiple
named conversations are wanted later, that's a separate, additive feature on top of this one.

### 2. Data model: two tables

```python
class ConversationTurn(Base):
    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    user_email: Mapped[str] = mapped_column(String(255), primary_key=True)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

`conversation_turns` is append-only — one row per Q&A pair, one turn, never mutated or deleted
except by the explicit "clear conversation" action (Decision 7). `conversation_summaries` has at
most one row per user, overwritten in place as the summary evolves.

**Rationale for two tables over one:** mirrors this codebase's existing pattern of splitting
distinct concerns into their own tables (e.g. `DocumentKb` vs. `EnrichedRecord`) rather than
conflating a per-turn fact (the Q&A) with a per-user rolling value (the summary) in one row, which
would complicate "which row holds the current summary" logic.

**Retention:** raw turns are kept forever once written (never auto-pruned when they age out of the
6-turn window) — matches this codebase's audit-everything philosophy (`audit_records`,
`document_steps` are never pruned either). The summary is a derived cache for prompting, not the
source of truth; the raw turns remain that source of truth and could back a future "full history"
view.

### 3. Repository layer

Following the existing `IDocumentKbRepository` / `SqlDocumentKbRepository` /
`InMemoryDocumentKbRepository` pattern exactly:

```python
class IConversationRepository(Protocol):
    async def save_turn(self, user_email: str, question: str, answer: str) -> None: ...
    # Both methods return oldest-first (ascending created_at): recent_turns so
    # _history_block prints them in natural reading order, all_turns so
    # MemoryService.record_turn can index the turn that just aged out of the window.
    async def recent_turns(self, user_email: str, limit: int) -> list[ConversationTurn]: ...
    async def all_turns(self, user_email: str) -> list[ConversationTurn]: ...
    async def turn_count(self, user_email: str) -> int: ...
    async def get_summary(self, user_email: str) -> str | None: ...
    async def save_summary(self, user_email: str, summary_text: str) -> None: ...
    async def clear(self, user_email: str) -> None: ...  # deletes turns + summary for the user
```

`SqlConversationRepository` implements this over the two tables above.
`InMemoryConversationRepository` implements it over two `dict`s (`dict[str, list[...]]` and
`dict[str, str]`), matching the in-memory pattern used for every other repository in
`injections/test.py`.

### 4. `MemoryService`: window + summarization orchestration

New file: `src/classiflow/knowledge/memory/service.py` (new `memory/` subpackage under
`knowledge/`, alongside `chat/`, `retrieval/`, `chunking/` — same one-concern-per-subpackage
layout already used there).

```python
RAW_WINDOW_SIZE = 6  # last N turns sent verbatim; the 7th-oldest folds into the summary


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
        # The turn that just fell out of the raw window is the oldest one beyond
        # RAW_WINDOW_SIZE -- fold exactly that one into the running summary.
        turns = await self._repo.all_turns(user_email)
        aging_out = turns[-(RAW_WINDOW_SIZE + 1)]
        old_summary = await self._repo.get_summary(user_email) or ""
        new_summary = await self._summarize(old_summary, aging_out)
        await self._repo.save_summary(user_email, new_summary)

    async def _summarize(self, old_summary: str, turn: ConversationTurn) -> str:
        prompt = build_summary_prompt(old_summary, turn.question, turn.answer)
        parts = [tok async for tok in self._chat_llm.astream(SUMMARY_SYSTEM_PROMPT, prompt)]
        return "".join(parts).strip()

    async def clear(self, user_email: str) -> None:
        await self._repo.clear(user_email)
```

`_summarize` reuses the existing `ChatLlm.astream` interface (no new LLM-facing abstraction) —
one full generation, collected into a string exactly like `ChatService.answer()` already does at
`chat/service.py:19`.

New prompt module addition, in `src/classiflow/knowledge/prompts/memory.py`:

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

### 5. Prompt construction: splice history before the existing passages block

`build_user_prompt` (`knowledge/prompts/chat.py`) gains an optional `history` parameter:

```python
def build_user_prompt(
    question: str, chunks: list[RetrievedChunk], history: ConversationHistory | None = None
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

`SYSTEM_PROMPT` itself is unchanged — the history block travels in the user prompt, consistent
with how retrieved passages already do.

`ChatService.astream` and `.answer` (`chat/service.py`) gain a `history: ConversationHistory |
None = None` parameter, forwarded to `build_user_prompt`. Existing callers/tests that don't pass
`history` keep working unchanged (default `None` -> today's exact behavior, no history block).

### 6. Wiring into the chat flow

`POST /knowledge/chat/stream` (`api/routes/knowledge/endpoints.py`) is the only endpoint that
changes:

1. Before streaming: `history = await memory_service.load(current_user.email)`, passed into
   `chat_service.astream(query, history=history)`.
2. The full answer is already being assembled token-by-token for the SSE stream; accumulate it
   into one string as it streams (`"".join` of yielded tokens — the route already has every
   token in hand to forward as SSE events, so this is a formatting change, not a new call).
3. After the stream's `done` event is yielded (i.e. after the response has been fully sent):
   `await memory_service.record_turn(current_user.email, question, full_answer)`. Since this
   happens inside the same async generator body after the last `yield`, it runs as part of
   closing out that generator — the HTTP response has already been flushed to the client by the
   time this executes, so it does not add latency to the perceived response. If `record_turn`
   raises (e.g. the summarization LLM call fails), the exception is caught and logged, not
   propagated — the user already has their answer; a failed summary fold-in is not fatal and will
   retry naturally the next time a turn ages out (Decision 2's retention guarantee: the raw turn
   itself is saved before the summarization step runs, so no data is lost either way).

`POST /knowledge/chat` (the non-streaming endpoint) gets the same `history`/`record_turn` wiring
for parity, even though the Chat page only uses the streaming endpoint — keeping both endpoints
behaviorally consistent avoids a silent capability gap if the non-streaming endpoint is ever used
directly (it already exists and is tested).

### 7. New endpoints

Two new routes on the existing `/knowledge` router (same `Depends(get_current_user)` convention):

```python
@router.get("/conversation")
async def get_conversation(
    current_user: CurrentUser,
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> ConversationResponse:
    history = await memory_service.load(current_user.email)
    return ConversationResponse.from_domain(history)


@router.delete("/conversation", status_code=HTTPStatus.NO_CONTENT)
async def clear_conversation(
    current_user: CurrentUser,
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> None:
    await memory_service.clear(current_user.email)
```

New schemas in `api/routes/knowledge/schemas.py`:

```python
class ConversationTurnSchema(BaseSchema):
    question: str
    answer: str
    created_at: datetime


class ConversationResponse(BaseSchema):
    summary: str | None
    turns: list[ConversationTurnSchema]

    @classmethod
    def from_domain(cls, history: ConversationHistory) -> "ConversationResponse": ...
```

`GET /knowledge/conversation` returns **all** raw turns kept (not just the 6-turn LLM window) —
the frontend history view should show everything the user has asked, even if only the last 6 feed
the model's prompt. This is a deliberate difference from what `MemoryService.load()` uses
internally for prompting (`recent_turns`, capped at `RAW_WINDOW_SIZE`) versus what this endpoint
returns for display (`all_turns`) — the route calls `repo.all_turns()` directly rather than going
through `MemoryService.load()`.

### 8. DI wiring

`SqlConversationRepository` needs a per-request database session, so — like `document_kb_repo` —
it is **not** wired into `injections/production.py`'s `Container`. Instead, add a new
`get_conversation_repo` dependency function in `api/dependencies.py`, session-scoped, next to the
existing `get_document_kb_repo`. `memory_service` similarly gets a `get_memory_service` dependency
function (not a container provider), constructed per-request from `get_conversation_repo` and the
existing `chat_llm` singleton (via the same `Depends(Provide[Container.chat_llm])` pattern
`get_chat_service` already uses) — mirrors how `get_chat_service` is already built today.

`injections/test.py`: add `_InMemoryConversationRepository` wiring alongside the existing
`_StubEmbedder`/`_StubChatLlm` stubs, and a `TestContainer`-side `conversation_repo` provider so
route tests can seed/inspect it directly (matching `document_kb_repo`'s existing test-side setup).

### 9. Alembic migration

One new migration, `alembic/versions/0013_add_conversation_memory.py`, creating both tables. Next
number after the KB migrations already on `main` (`0009`-`0012`).

### 10. Frontend: history load + clear button

`ChatPage.tsx`:
- New `api/knowledge.ts` functions: `fetchConversation(): Promise<ConversationResponse>` and
  `clearConversation(): Promise<void>`, following the existing `fetchDocumentKb`/`synchronizeKb`
  throw-on-`!ok` convention.
- On mount (alongside the existing `warmupChat()` effect), fetch conversation history and seed
  `messages` state from it: each `ConversationTurnSchema` becomes one user message + one assistant
  message, in `created_at` order.
- A "Clear conversation" button, placed near the input row (matching the existing inline-button
  style used by "Sync Knowledge Base" on the Classification page): calls `clearConversation()`,
  then resets local `messages` state to `[]` on success.
- No change to the streaming logic itself (`handleSend`) — history is loaded once on mount and
  grows locally exactly as it does today; the backend is the one appending to persisted storage
  after each answer, invisibly to the frontend.

## Non-Goals

- No multi-conversation support (one continuous conversation per user — Decision 1).
- No UI for viewing, editing, or deleting individual turns — only whole-conversation clear, via
  the `DELETE /knowledge/conversation` endpoint (Decision 7).
- No cross-user visibility or conversation sharing.
- No change to retrieval, chunking, embedding, or the `/knowledge/synchronize-kb` /
  `/knowledge/documents/*` endpoints — this spec only touches the chat/memory path.
- No summarization model change — reuses the existing single chat `ChatLlm` provider
  (`LlamaCppChatLlm`), no second/smaller model introduced for summarization specifically.

## Testing

- **Repository:** `tests/shared/test_repositories.py` — `SqlConversationRepository` and
  `InMemoryConversationRepository`, covering `save_turn`/`recent_turns`/`all_turns`/`turn_count`/
  `get_summary`/`save_summary`/`clear`, mirroring the existing `DocumentKb` repository test shape.
- **`MemoryService`:** new `tests/knowledge/test_memory_service.py` — `load()` returns the right
  window size and summary; `record_turn()` does not summarize before the window fills; `record_turn()`
  triggers exactly one summarization call once the window overflows, and it targets the correct
  aging-out turn; a summarization failure doesn't lose the just-saved raw turn.
- **Prompt construction:** extend `tests/knowledge/test_prompts.py` (or create it if it doesn't
  exist) — `build_user_prompt` with/without `history`, confirming the history block only appears
  when `history` has content, and existing no-history callers are byte-for-byte unaffected.
- **Routes:** extend `tests/api/routes/test_knowledge.py` — `GET`/`DELETE /knowledge/conversation`
  require auth; `GET` returns the full turn list plus summary; `DELETE` empties both, confirmed via
  a subsequent `GET`; `POST /knowledge/chat/stream` persists a turn after streaming completes and
  passes prior history into the next call's prompt (integration-style, using the in-memory
  repository).
- **Frontend:** extend `ChatPage.test.tsx` — history loads and renders on mount; "Clear
  conversation" empties the message list and calls the delete endpoint.
- Standard gate: `uv run poe check` (lint, typecheck, full pytest suite, pre-commit) plus the
  frontend's own `tsc -b && lint && test`, handed to the user per this repo's execution-workflow
  rule.
