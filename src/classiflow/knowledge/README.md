# `knowledge/` — the RAG knowledge base

One folder per stage of the pipeline, in the order data flows through them.

| Folder | Does | Key names |
|---|---|---|
| `domain/` | Shared value objects. The one non-capability folder. | `Chunk`, `Embedding`, `StoreMetadata`, `DocumentMetadata`, `ChatQuery`, `RetrievedChunk`, `SourceRef`, `ChatAnswer` |
| `indexing/` | Entry point: one accepted document → persisted chunks. Resolves doc_type/number/year from the document's own extracted entities. | `IndexerService`, `IndexResult` |
| `chunking/` | Splits text into overlapping, paragraph-aware windows, each prefixed with a citation header. | `ChunkerService` |
| `embeddings/` | Text → vectors, via a cached multilingual SentenceTransformer. | `SentenceTransformerEmbedder`, `get_sentence_model` |
| `vectordb/` | Stores and similarity-searches chunk vectors. | `VectorStore` (abstract), `ChromaVectorStore`, `InMemoryVectorStore` |
| `retrieval/` | Query → the `top_k` most similar chunks. | `RetrieverService` |
| `prompts/` | The RAG system prompt and passage formatting. | `SYSTEM_PROMPT`, `build_user_prompt` |
| `llm/` | Streaming chat completion. | `ChatLlm` (abstract), `LlamaCppChatLlm` |
| `chat/` | Retrieval + prompt + streamed answer with sources. | `ChatService` |
| `utils/` | Stage-agnostic helpers. | `normalize_whitespace`, `split_paragraphs`, `dot`, Chroma response adapters |

Document ingestion itself — MIME detection, PDF/DOCX text extraction, OCR, and the
LangGraph pipeline — is **not** here. It lives in `src/classiflow/ingesta/`, which calls
into `indexing/` from its node 5.

## Import from the concrete module, not the package

Every `__init__.py` in this package is deliberately **empty** (only `domain/`, `prompts/`
and `chunking/` carry re-exports, and those are dependency-free).

Python executes a package's `__init__.py` before any of its submodules, so a convenience
barrel at `knowledge/__init__.py` would load `chromadb`, `sentence_transformers`
*and* `llama_cpp` the moment anything imported `knowledge.utils.text`. That cost lands
on the test suite, which needs none of them. So:

Do this:

```python
from classiflow.knowledge.vectordb.chroma_store import ChromaVectorStore
```

Not this:

```python
from classiflow.knowledge import ChromaVectorStore
```

## The two abstract classes

There is no separate ports layer — no `repositories/` package, no `I`-prefixed
`Protocol`s. Implementations are named and depended on directly.

The two exceptions are `vectordb/vector_store.py` and `llm/chat_llm.py`, which each
declare a thin `abc.ABC` **beside** their implementations. Both capabilities have more
than one live implementation that the DI container substitutes at runtime
(`ChromaVectorStore` ↔ `InMemoryVectorStore`; `LlamaCppChatLlm` ↔ the test-only stub in
`injections/test.py`), so consumers need a common type to name. Annotating against one
concrete class would be false.

Both ABC modules are kept free of heavy imports on purpose: they sit on the import path
of `retrieval/`, `indexing/` and `chat/`.

`embeddings/` has a single production implementation and therefore no abstraction —
consumers name `SentenceTransformerEmbedder` directly.

## Exceptions

`knowledge/exceptions.py` holds only the `KnowledgeError` base. Each capability defines
its own subclasses in its `exceptions.py`:

| Capability | Raises |
|---|---|
| `embeddings/` | `EmbeddingError` |
| `vectordb/` | `VectorStoreError` |
| `llm/` | `ChatLlmError` |
