# Classiflow — Stage 2 Task List

> Prerequisite: Stage 1 complete + EventBroadcaster (Stage 1 T07) exists.
> Full details in [plan_stage2.md](plan_stage2.md).
> Status: `[ ]` pending · `[~]` in progress · `[x]` done · `[-]` skipped · `[!]` blocked

---

## Parallel Execution Map

```
BATCH 0  ──────────────────────────────────────────── parallel (no dependencies)
  S2-T01  ExtractionRecord DB model + Alembic migration
  S2-T03  MarkItDown extractor
  S2-T04  PaddleOCR extractor
  S2-T07  extraction.yaml + ExtractionConfig model

BATCH 1  ──────────────────────────────────────────── parallel
  S2-T02  ExtractionRepository                    (needs S2-T01)
  S2-T05  Extraction chain (MarkItDown → OCR)     (needs S2-T03 + S2-T04)

BATCH 2  ──────────────────────────────────────────── sequential
  S2-T06  Async worker pool + asyncio.Queue       (needs S2-T02 + S2-T05 + S2-T07)

BATCH 3  ──────────────────────────────────────────── sequential
  S2-T08  SSE events wired to EventBroadcaster    (needs S2-T06)

BATCH 4  ──────────────────────────────────────────── sequential
  S2-T09  Integration test: full extraction pipeline  (needs S2-T08)
```

---

## Task Details

- [ ] **S2-T01** — ExtractionRecord DB model + Alembic migration
      Branch: `feat/extraction-model`

- [ ] **S2-T02** — ExtractionRepository (CRUD over ExtractionRecord)
      Branch: `feat/extraction-repo`

- [ ] **S2-T03** — MarkItDown extractor
      Branch: `feat/extractor-markitdown`

- [ ] **S2-T04** — PaddleOCR extractor
      Branch: `feat/extractor-paddleocr`

- [ ] **S2-T05** — Extraction chain: MarkItDown → PaddleOCR fallback, `ExtractionMetadata`
      Branch: `feat/extraction-chain`

- [ ] **S2-T06** — Async worker pool + `asyncio.Queue`, semaphore from config
      Branch: `feat/extraction-worker`

- [ ] **S2-T07** — `config/extraction.yaml` + `ExtractionConfig` Pydantic model
      Branch: `feat/extraction-config`

- [ ] **S2-T08** — SSE event emission at each state transition via `EventBroadcaster`
      Branch: `feat/extraction-sse`

- [ ] **S2-T09** — Integration test: enqueue file → worker runs → ExtractionRecord written → events emitted
      Branch: `feat/extraction-integration`
