# Design: Stage 3 — Refinement & Enrichment

## Context

`tasks/plan_stage3.md` already defines Stage 3's shape: three sequential steps (clean →
extract entities → enrich metadata) over Stage 2's extracted text, landing in a new
`EnrichedRecord` table. That plan and `tasks/todo_stage3.md`'s task cards predate this
design — they name *what* gets built but not *how*, and are missing the parts that only
became visible once Stage 5 (RAG embeddings) was scoped: `EnrichedRecord.cleaned_text`
isn't just "the enriched record's text" — it is specifically the text Stage 5 will
embed, which makes Stage 3's failure behavior a first-class decision (a document with no
`EnrichedRecord` is a document invisible to RAG), not an afterthought.

This spec resolves three previously-open gaps — package layout, the entity-extraction
LLM chain design, and the text-cleaning heuristic — plus the newly surfaced
persistence/failure-handling question, and supersedes `plan_stage3.md`'s Steps section
with concrete decisions. The field lists and `EnrichedRecord` shape `plan_stage3.md`
already defined are treated as settled and are not re-litigated here.

## Decisions

### 1. Package location: new top-level `enrichment/`, not inside `ingesta/`

Mirrors the precedent already set for Stage 4 (`docs/superpowers/specs/2026-08-17-bert-tunning-classification-integration-design.md`,
Decision 3): Stage 3 is conceptually independent of Stage 1/2's ingestion pipeline —
nesting it under `ingesta/` would misrepresent that, and `ingesta/` is already a large
package covering five nodes plus extraction. `src/classiflow/enrichment/` mirrors
`ingesta/`'s internal shape (`domain/`, `nodes/`, `prompts/`, `coordinator.py`,
per-concern `config_*.py` files).

### 2. Prerequisite: relocate `BaseNode` and `config_loader.py` to neutral ground

Both `classiflow.ingesta.nodes.base.BaseNode` and
`classiflow.ingesta.config_loader.load_yaml_config` are generic (audit/broadcast
wrapping; YAML→pydantic loading) — nothing about either is ingestion-specific. The
bert_tunning spec already called for this exact relocation (`classification/` needs the
same shared base) but it was never implemented, since `classification/` doesn't exist
yet either. Stage 3 is now the first stage to actually need it, so this design executes
the move:

- `ingesta/nodes/base.py` → `classiflow/pipeline/base.py`. `ingesta/nodes/base.py` is
  deleted; its 5 current importers (`node1_file_reception`, `node2_format_validation`,
  `node3_content_validation`, `node4_duplicate_control`, `extraction_step`) switch their
  import. `enrichment/nodes/*` imports from the same place.
- `ingesta/config_loader.py` → `classiflow/config_loader.py`. `ingesta`'s 4 config
  modules (`config.py`, `config_content.py`, `config_duplicate.py`,
  `config_extraction.py`) switch their import; `enrichment/config_enrichment.py` uses
  the same relocated helper instead of a near-duplicate.

Mechanical, no behavior change — covered by the existing Stage 1/2 test suite.

### 3. Trigger: automatic, in-memory, inside `PipelineService._run()`

Stage 3 runs immediately after a job's `final_status` resolves to `"accepted"`, using
`final_state["text"]` directly — no DB re-fetch on the happy path:

```python
if final_state.get("final_status") == "accepted":
    await self._enrichment_coordinator.ainvoke({
        "job_id": job_id,
        "filename": filename,
        "text": final_state["text"],
    })
```

`DocumentStep.detail["text"]` (Stage 2, `node="extraction"`, written for every job per
`plan_stage2.md` S2-T04) remains as a durable fallback source of the raw text — not used
by this trigger, but available if a future backfill/reprocess path needs to re-run
enrichment for a job independently of the original coordinator run.

### 4. Step 1 — Text Cleaning: frequency-based repeated-line detection

Rejected the plan's original heuristic ("detect lines repeated across pages") as
unimplementable as stated: `OCRExtractor._read_pages()` joins all pages with
`"\n".join(lines)` and `MarkItDownExtractor.extract()` returns a single flat
`text_content` — neither preserves page boundaries, so there is no "across pages" to
compare.

**Chosen instead:** split `text` on `"\n"`, count occurrences of each stripped
non-empty line, and drop any line whose count exceeds a configurable threshold
(default: appears 3+ times) — a repeated line is a strong signal of a running
header/footer regardless of which page boundary produced it. Combined with:
- Page-number-shaped line removal (bare integers, `Página N`, `N/M` patterns).
- OCR artifact cleanup (long runs of non-alphanumeric noise, stray control
  characters).
- Unicode normalization (NFC, common ligature/accent fixes seen in scanned municipal
  PDFs).

Output: `cleaned_text: str`. Pure string processing, no LLM involved, no external
dependency beyond stdlib `unicodedata` and `re`.

### 5. Step 2 — Entity Extraction: same LLM chain pattern as node2/node3

Follows the established shape exactly (verified against
`ingesta/prompts/content_validation.py`): a `BaseEntity` chain-input model, a plain
`.format()`-based prompt template (no `PromptTemplate`), a `RunnableLambda | llm |
StrOutputParser() | RunnableLambda` chain, and a `BaseEntity` output model with
defaults that fail safe on a malformed/partial SLM response rather than raising.

```python
class EntityExtractionInput(BaseEntity):
    cleaned_text: str

class EntityExtractionOutput(BaseEntity):
    doc_type_hint: str | None = None
    number: str | None = None
    year: int | None = None
    issuing_body: str | None = None
    signatories: list[str] = []
    article_count: int | None = None

def build_entity_extraction_chain(llm: BaseLLM) -> Runnable[EntityExtractionInput, EntityExtractionOutput]:
    return RunnableLambda(_format_prompt) | llm | StrOutputParser() | RunnableLambda(_extract)
```

Same JSON-object regex parse with a field-by-field regex fallback for
quote-escaping failures, matching `content_validation.py`'s `_extract` precedent.
Imports `get_llm_langchain()` directly from `classiflow.ingesta.llm_provider` — no new
`enrichment/llm_provider.py` module — called with a new `Settings.enrichment_model_path`
so it gets its own `@lru_cache` slot, independent of node2/node3's models but reusing
the exact same cached-loader function (and the VRAM-release-on-job-end behavior that
comes with it) rather than inventing a second caching mechanism.

### 6. Step 3 — Metadata Enrichment

Attaches context already known from earlier in the pipeline — no new detection:

| Field | Source |
|---|---|
| `source` | Hardcoded `"manual_upload"` — the only live ingestion path since `scrapper/`'s deletion. `csv_category` is dropped entirely (no data source produces it anymore). |
| `filename` | Passed through from the job. |
| `language` | From Stage 1 Node 3's `ContentValidationResult.detected_language` (already detected, not re-run). |
| `sha256` | From Stage 1 Node 4's `DuplicateControlResult` (already computed). |
| `stage2_extractor_used` | From the `"extraction"` `DocumentStep.detail["extractor_used"]`. |

Pure data plumbing, no LLM call — a plain function, not a chain.

### 7. Persistence — `EnrichedRecord.cleaned_text` is the Stage 5 RAG input

`plan_stage3.md`'s `EnrichedRecord` model (`id`, `job_id`, `cleaned_text`, `entities`
JSON, `metadata` JSON, `created_at`) already has the right shape — this design adds the
explicit rationale that was previously undocumented: `cleaned_text` is not just "the
document's text after Stage 3" — it is the exact text Stage 5 will chunk and embed for
RAG. This is why it must be *cleaned* (not raw Stage 2 output) and why it must exist
durably per accepted document, not just transiently in `final_state`. No new DB field is
needed beyond what `plan_stage3.md` already specifies.

### 8. Failure handling: retry twice, then fall back to the existing review mechanism

By the time enrichment runs, the job is already `"accepted"` — a hard failure can't
un-accept it, and Stage 3 shouldn't block or reverse Stage 1/2's decision. Chosen
behavior:

1. Retry the enrichment coordinator up to 2 times on any failure (LLM error, chain
   parse failure, etc.).
2. If still failing after retries, reuse the existing `JobRepository.update_status()`
   mechanism (`services/pipeline/service.py:116`, already used by Stage 1/2's own
   review path) to transition the job:

```python
await self._job_repo.update_status(
    job_id,
    "review",
    rejection_reason=f"Enrichment failed after retries: {error}",
    review_action_needed="enrichment_failed",
    failed_at_node="enrichment",
)
```

`review_action_needed="enrichment_failed"` is a new, distinct value from Stage 1/2's
generic `"pending"` — makes an enrichment-caused review visibly different from a
content/duplicate-caused one in the review queue. No `EnrichedRecord` row is created for
that job; it remains invisible to Stage 5 until manually reprocessed. No new retry
infrastructure beyond a bounded loop — if review-queue volume from this path grows,
revisit with real data instead of building more upfront.

## File layout

```
src/classiflow/pipeline/
└── base.py                          BaseNode (moved from ingesta/nodes/base.py, unchanged)

src/classiflow/config_loader.py      load_yaml_config() (moved from ingesta/config_loader.py, unchanged)

src/classiflow/enrichment/
├── config_enrichment.py             EnrichmentConfig + get_enrichment_config()
│                                     — loads config/enrichment.yaml via the relocated
│                                     config_loader.load_yaml_config()
├── domain/
│   ├── results.py                   TextCleaningResult, EntityExtractionResult,
│   │                                 MetadataEnrichmentResult (all BaseEntity)
│   └── state.py                     EnrichmentState TypedDict
├── prompts/
│   └── entity_extraction.py         EntityExtractionInput/Output + build_entity_extraction_chain()
├── nodes/
│   ├── text_cleaner.py               TextCleanerNode (pure string processing, no LLM)
│   ├── entity_extractor.py           EntityExtractorNode (LLM chain, node2/node3 pattern;
│   │                                 imports get_llm_langchain() from ingesta.llm_provider)
│   └── metadata_enricher.py          MetadataEnricherNode (plumbing, no LLM)
└── coordinator.py                    build_enrichment_coordinator(...) — LangGraph
                                      3-node linear chain: clean -> extract -> enrich

config/enrichment.yaml               new — repeated-line threshold, retry count, etc.
```

## Config — `config/enrichment.yaml`

```yaml
repeated_line_min_count: 3         # lines appearing this many times or more are stripped
max_enrichment_retries: 2
```

`EnrichmentConfig` (pydantic `BaseModel`, same pattern as `ExtractionConfig` in
`ingesta/config_extraction.py`), loaded once via `@lru_cache(maxsize=1)`.

## Testing

- Unit tests per node, mirroring `tests/ingesta/test_node3.py`'s structure:
  `TestTextCleaner` (repeated-line stripping, page-number removal, Unicode
  normalization — pure input/output, no mocks needed), `TestEntityExtractor` (using
  `MockLlm` from `ingesta/llm_provider.py`, same as `test_node3.py`'s
  `content_chain=build_content_chain(MockLlm(...))` pattern), `TestMetadataEnricher`
  (plain data-plumbing assertions).
- Coordinator-level test: happy path (clean → extract → enrich → `EnrichedRecord`
  persisted with the right `cleaned_text`), and the retry-then-review path (force 3
  consecutive failures, assert `JobRepository.update_status` was called with
  `review_action_needed="enrichment_failed"` and no `EnrichedRecord` was created).

## Open items / risks

| Risk | Mitigation |
|---|---|
| Relocating `BaseNode`/`config_loader.py` touches already-shipped Stage 1/2 code | Small, mechanical import-path changes only — no behavior change; covered by existing test suite (same accepted risk as the bert_tunning spec's identical relocation) |
| `enrichment/` depends on `ingesta.llm_provider.get_llm_langchain()`, a cross-package import in the direction Stage 3 → Stage 1/2 | Accepted — `llm_provider.py` is a generic SLM-loading utility, not ingestion-specific logic; a future cleanup could relocate it alongside `BaseNode`/`config_loader.py`, but that's out of scope here since nothing about it needs to change to be reused |
| Repeated-line threshold (`3+`) is a heuristic default, not tuned against real municipal PDF samples | Configurable via `config/enrichment.yaml`; revisit once Stage 3 runs against real accepted documents and false-positive/negative stripping can be observed |
| `review_action_needed="enrichment_failed"` volume could grow if the entity-extraction LLM is unreliable on this document set | Accepted for now per explicit user decision — revisit (e.g. add backoff, alerting, or a dedicated retry queue) only if the review queue shows it's a real problem |
