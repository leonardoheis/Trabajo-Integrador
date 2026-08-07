# Stage 5: Knowledge Base + Chat Agent (stub)

> Detailed planning deferred — run a dedicated /grill-me session when Stage 4 is near complete.

## Responsibility

Build a searchable knowledge base from classified documents and expose a chat agent that
retrieves relevant passages and responds with sources.

## Known Shape

### KB Pipeline

1. **Chunking** — overlapping fixed-size windows over `cleaned_text` (size + overlap TBD)
2. **Embeddings** — sentence-transformers (reuse `all-MiniLM-L6-v2` from Node 4 duplicate
   control to avoid a second model load)
3. **Vector store** — TBD: pgvector, ChromaDB, or Qdrant (decide when Stage 4 is done)
4. Each chunk stored with: `file_id`, `label`, `source`, `chunk_index`, `text`, `embedding`

### Chat Agent

- RAG pattern: query → embed → retrieve top-k chunks → LLM generates answer with sources
- Sources surfaced to the user: filename, doc_type, excerpt
- Interface: `GET /chat` endpoint → SSE stream (same `EventBroadcaster` pattern)

## Open Questions (resolve before planning)

- Vector store choice (pgvector keeps everything in one DB; ChromaDB/Qdrant are specialized)
- Chunk size and overlap strategy
- Reranking step (optional — cross-encoder on top-k before LLM)
- Auth scope: whitelist-only or publicly accessible chat?
- Incremental indexing: re-index when a document is reclassified?
