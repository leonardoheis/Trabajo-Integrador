# Classiflow — Stage 3 Task List

> Prerequisite: Stage 2 complete (the `"extraction"` `DocumentStep` carries `text`,
> `extractor_used`, `char_count` in its `detail` for every job — see `plan_stage2.md` S2-T04).
> Full details in [plan_stage3.md](plan_stage3.md).
> Status: `[ ]` pending · `[~]` in progress · `[x]` done · `[-]` skipped · `[!]` blocked

---

## Parallel Execution Map

```
BATCH 0  ──────────────────────────────────────────── parallel (no dependencies)
  S3-T01  EnrichedRecord DB model + Alembic migration
  S3-T02  Text cleaner
  S3-T03  Entity extractor (LLM chain)             (needs LLM provider T11)
  S3-T04  Metadata enricher

BATCH 1  ──────────────────────────────────────────── sequential
  S3-T05  Stage 3 coordinator: clean → extract → enrich  (needs S3-T01..T04)
```

---

## Task Details

- [ ] **S3-T01** — EnrichedRecord DB model + Alembic migration
      Branch: `feat/enriched-model`

- [ ] **S3-T02** — Text cleaner (header/footer stripping, OCR artifact removal, Unicode normalization)
      Branch: `feat/text-cleaner`

- [ ] **S3-T03** — Entity extractor: LLM chain → `doc_type_hint`, `number`, `year`, `issuing_body`, `signatories`, `article_count`
      Branch: `feat/entity-extractor`

- [ ] **S3-T04** — Metadata enricher: attach source, csv_category, language, sha256, extractor_used
      Branch: `feat/metadata-enricher`

- [ ] **S3-T05** — Stage 3 coordinator: sequential chain clean → extract → enrich → write EnrichedRecord
      Branch: `feat/stage3-coordinator`
