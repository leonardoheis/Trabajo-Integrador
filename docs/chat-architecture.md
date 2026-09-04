# How the chat works

From a PDF on disk to a streamed, cited answer — and how conversation memory, model
lifecycle and concurrency fit around it.

---

## The two halves

Chat is a **RAG** (retrieval-augmented generation) pipeline. It runs in two phases that
happen at completely different times:

```
INDEXING (once per document, manually triggered)
  document → chunks → embeddings → ChromaDB

RETRIEVAL + GENERATION (every question)
  question → embedding → similarity search → prompt → LLM → streamed answer
```

The model never sees the corpus. It only ever sees the handful of passages retrieval
selected for one specific question — which is why answers can cite sources, and why the
assistant genuinely cannot answer "how many documents are there".

---

## Phase 1 — Indexing

Runs only when a human triggers it: the **Index into Knowledge Base** button on a document,
or **Sync Knowledge Base** on the Classification page. Only `accept`-routed documents are
eligible. Classification alone never indexes anything.

### 1. Chunking — `knowledge/chunking/chunker.py`

The cleaned text is split into overlapping, paragraph-aware windows
(`CHUNK_SIZE=1000`, `CHUNK_OVERLAP=250`).

Two details that matter:

- **Paragraph-aware, not fixed-stride.** Windows break on paragraph boundaries where
  possible, so a passage rarely starts mid-sentence. A paragraph longer than the window
  is hard-split on a fixed stride as a fallback — common in scanned norms with no blank
  lines at all.
- **Every chunk is prefixed with a citation header.** Retrieval returns single chunks, and
  a bare fragment of legal prose is often unattributable. The header carries
  `doc_type`/`number`/`year`, derived from the entities the enrichment stage already
  extracted.

### 2. Embedding — `knowledge/embeddings/embedder.py`

Each chunk's text becomes a vector via `paraphrase-multilingual-MiniLM-L12-v2`.

**Multilingual on purpose** — the corpus is Spanish. Note this is a *different* model from
node 4's `all-MiniLM-L6-v2` duplicate control; swapping that one would invalidate the
cosine threshold calibrated in `config/duplicate_control.yaml`.

### 3. Storage — `knowledge/vectordb/vector_store.py`

Vectors go into **ChromaDB** with metadata: `filename`, `doc_type`, `number`, `year`,
`job_id`, `sha256`. That metadata is what makes filtered retrieval possible later.

Both the embedding and the Chroma write run in `asyncio.to_thread` — they're blocking and
CPU-bound, and indexing happens inside a pipeline job while other jobs and SSE streams are
live.

---

## Phase 2 — Answering a question

### Step 1: Load conversation memory

`MemoryService.load()` returns two things:

| | Content |
|---|---|
| `summary` | A running LLM-written summary of older exchanges |
| `recent_turns` | The last **6** turns, verbatim (`RAW_WINDOW_SIZE`) |

### Step 2: Retrieve passages — `knowledge/retrieval/retriever.py`

The question is embedded with the same model used at index time, then Chroma returns the
`top_k` nearest chunks (`RETRIEVAL_TOP_K=10`).

**One important escape hatch:** dense vector search is weak at exact identifier lookup — a
bare filename embeds poorly against its own content. So if the question names a `.pdf`
explicitly, retrieval adds a hard metadata filter on `filename`:

```python
filename = detect_filename(query.question)
if filename and "filename" not in filters:
    filters["filename"] = filename
```

Asking *"¿de qué trata ordenanza_9964_2019.pdf?"* filters directly to that document rather
than hoping cosine similarity favours it. Deliberately filename-only — `doc_type` is
LLM-extracted and inconsistent in real data (observed: `"Ordenanza, decreto, resolucion"`,
mojibake like `"Resoluci�n"`), so filtering on it would fail silently rather than degrade.

### Step 3: Build the prompt — `knowledge/prompts/chat.py`

Three blocks assembled into one user prompt:

```
[conversation history: summary + last 6 turns]

[1] Ordenanza 9964/2019 (ordenanza_9964_2019.pdf)
    <chunk text>
[2] Decreto 810/2026 (decreto_810_2026.pdf)
    <chunk text>
...

[the question]
```

The system prompt constrains behaviour hard:

- Answer **only** from the provided passages — no external knowledge
- Cite by `doc_type`, number and year
- Multiple numbered passages may belong to one document; don't count them as separate
- If asked for a *complete inventory* of the knowledge base, say you only see the fragments
  for this question
- If the passages don't contain the answer, say so rather than improvise

That last rule is what keeps the assistant from hallucinating municipal law.

### Step 4: Generate and stream — `knowledge/llm/llama.py`

`Meta-Llama-3.1-8B-Instruct` (Q4_K_M GGUF) via llama.cpp, `n_ctx=3072`.

Streaming is real token-by-token generation, not one buffered response. The mechanism:

```
llama.cpp (blocking, in a daemon thread)
        │  puts tokens on a queue
        ▼
astream() coroutine drains the queue on the event loop
        │  yields each token
        ▼
SSE: event: token / event: sources / event: done
```

The background thread exists because llama.cpp generation is blocking and GPU-bound —
running it inline would freeze every other request, including other jobs and open SSE
streams, for its entire duration.

### Step 5: Record the turn

After the stream closes, `record_turn` runs as a **background task** — so a slow memory
write never stalls token delivery.

---

## Conversation memory

The model has no memory of its own; every request is stateless. Continuity is manufactured
from two sources.

### The verbatim window

The last `RAW_WINDOW_SIZE = 6` turns go into the prompt word for word. This is a **context
budget**, not a preference: 6 exchanges + retrieved passages + the question is roughly what
fits in `n_ctx=3072`. Raising it overflows the context and the generation fails mid-answer.

### The rolling summary

Turns older than the window are folded into an LLM-written summary — in **batches of 10**
(`SUMMARY_BATCH_SIZE`), not one at a time.

```
turns 1-6     all verbatim, no summary yet
turns 7-15    6 verbatim + a gap of 1-9 turns not yet folded
turn 16       first fold: turns 1-10 → summary
turns 17-25   summary(1-10) + 6 verbatim + gap
turn 26       second fold: turns 11-20 → summary
```

**Why batch:** each fold is a full 8B generation. Folding on every turn meant one extra LLM
call per question forever — over a 31-turn conversation, 25 generations instead of 2.

**The cost:** between folds, up to 9 turns are *invisible* — too old for the verbatim
window, not yet in the summary. Lower `SUMMARY_BATCH_SIZE` to 5 if the assistant starts
forgetting mid-conversation; the tradeoff is 2× the folds.

Both values are in `Settings` and env-overridable.

---

## Model lifecycle and concurrency

Three constraints shape this, and all three were learned the hard way.

### One generation at a time

llama.cpp's C bindings are **not safe** for concurrent use of one model handle. Two
generations interleaved on the same `Llama` object corrupt each other's KV cache and
surface as `IndexError: index N is out of bounds` deep inside `llama_cpp`.

Every generation serializes on `_generation_lock`, held for the whole stream — not just its
creation, since llama.cpp advances the cache on every token.

The realistic collision is background summarization overlapping a chat: the summarizer runs
as a background task on the same handle the user's next question needs.

### The model must not be evicted mid-generation

`unload_chat_llm()` frees ~4 GB of VRAM by dropping the `lru_cache` reference. Doing that
during an active generation hangs the process — observed as a pipeline job stuck forever at
`processing` with zero steps recorded.

An in-flight counter guards it. Unload requests during a generation **no-op and log**
rather than proceeding.

### An abandoned stream must release its resources

Close a browser tab mid-answer and three things have to happen, or the counter leaks and
every later unload silently no-ops:

1. **The SSE endpoint closes its generator** — Starlette does *not* `aclose()` a body
   iterator on client disconnect, so `contextlib.aclosing` is explicit at every layer.
2. **Each nested generator closes the one below it** — the endpoint wraps
   `ChatService.astream`, which wraps `ChatLlm.astream`. Missing any layer breaks the chain.
3. **The producer thread stops** — a `threading.Event`, checked between tokens, because
   llama.cpp's loop cannot be interrupted from outside. Without it an abandoned stream
   generates to completion into a queue nobody is reading.

### VRAM budgeting

On an 8 GB card the chat model (~4 GB) cannot coexist with the pipeline's SLM + BETO. So
navigation triggers eviction:

| Action | Effect |
|---|---|
| Open Processing or Classification | `POST /pipeline/warmup` → unload chat model |
| Open Chat | `POST /knowledge/chat/warmup` → unload pipeline models, load chat |
| Sign out | Unload chat model always; the four pipeline models if no job is running |

Every unload is a *request*, never an assertion — each is refused if the model is in use.

---

## Code map

| Concern | File |
|---|---|
| Chunking | `knowledge/chunking/chunker.py` |
| Embeddings | `knowledge/embeddings/embedder.py` |
| Vector store | `knowledge/vectordb/vector_store.py` |
| Indexing | `knowledge/indexing/indexer.py` |
| Retrieval + filename filter | `knowledge/retrieval/retriever.py` |
| Prompts | `knowledge/prompts/chat.py`, `knowledge/prompts/memory.py` |
| Orchestration | `knowledge/chat/service.py` |
| Memory / summarization | `knowledge/memory/service.py` |
| llama.cpp, streaming, locking | `knowledge/llm/llama.py` |
| SSE endpoint | `api/routes/knowledge/endpoints.py` |
| Frontend | `frontend/src/pages/ChatPage.tsx` |

## Settings

| Setting | Default | Controls |
|---|---|---|
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 1000 / 250 | Chunk window |
| `EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | Vectorization |
| `RETRIEVAL_TOP_K` | 10 | Passages per question |
| `CHAT_MODEL_N_CTX` | 3072 | Context window — the hard budget |
| `CHAT_MAX_TOKENS` | 2048 | Answer length cap |
| `RAW_WINDOW_SIZE` | 6 | Verbatim turns (bounded by `CHAT_MODEL_N_CTX`) |
| `SUMMARY_BATCH_SIZE` | 10 | Turns folded per summarization call |
