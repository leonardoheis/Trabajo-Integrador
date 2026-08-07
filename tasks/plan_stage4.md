# Stage 4: Classification

## Responsibility

Takes an `EnrichedRecord` (Stage 3 output) and produces a classification decision with
a routing outcome and a full audit trail. All checks below are in scope — mandatory vs
optional decided at implementation time.

## Components

### 1. Primary Classification Agent

- LLM-based document type classifier
- Input: `cleaned_text` truncated to `max_input_tokens` (same configurable truncation
  strategy as bert_tunning — first N tokens)
- Output: `label: str`, `confidence: float`, `all_scores: dict[str, float]`

### 2. Second Opinion Agent (optional at impl time)

Second LLM call with a different prompt/persona — equivalent to bert_tunning's SVM
reviewer. Gives an independent label.

- `classifier_disagreement: bool` — primary label ≠ second opinion label
- When disagreement → route to `human_review` regardless of confidence

### 3. Foreign Municipality Detection

Detects when the document names a municipality other than Rosario. Adds
`foreign_municipality` smell and a context string (the sentence where the name appears).

Adapted from bert_tunning `src/ingestion/_text.py:detect_foreign_municipality`.

### 4. Smells + Risk Score

Named conditions adapted from bert_tunning `pipeline.py:_SMELL_WEIGHTS`:

| Smell | Weight | Source |
|---|---|---|
| `unreadable_document` | 3 | Stage 2 returned `text=None` |
| `classifier_disagreement` | 3 | primary ≠ second opinion |
| `foreign_municipality` | 2 | document names another municipality |
| `low_svm_margin` | 2 | second opinion margin below threshold (if enabled) |
| `low_confidence` | 1 | confidence < `confidence_threshold` |

`risk_score = sum(weight for smell in fired_smells)`

`smell_review_suggested: bool` — `risk_score > smell_review_risk_threshold`, computed
independently of `review_route`. A safety net: flags docs for human attention even when
the gate said `accept`.

### 5. Confidence Gate

Adapted from bert_tunning `classify.py:decide_review_route`:

```
if foreign_municipality or classifier_disagreement:
    review_route = "human_review"
elif confidence >= confidence_threshold:
    review_route = "accept"
else:
    review_route = "llm_judge"
```

`ReviewRoute = "accept" | "llm_judge" | "human_review"`

### 6. LLM Judge (the `llm_judge` tier)

Focused second LLM pass for uncertain predictions. Uses the full `cleaned_text` (not
truncated). Outputs updated `label` + `confidence`, then the gate re-evaluates:
`accept` or `human_review`.

### 7. Routing Agent

Given the final `review_route`:

- `accept` → write to classified documents directory
- `llm_judge` → run judge → re-route to `accept` or `human_review`
- `human_review` → write to review queue

Writes to **audit log** for every document: label, confidence, review_route, all smells,
risk_score, smell_review_suggested, extractor_used, timestamp.

## Config (`config/classification.yaml`)

```yaml
confidence_threshold: 0.75
smell_review_risk_threshold: 4
max_input_tokens: 512               # truncation — same bert_tunning strategy, configurable
second_opinion_enabled: true        # ponytail: set false to skip second LLM call
foreign_municipality_enabled: true
```

## DB Model — ClassificationRecord

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `file_id` | UUID | FK → ingested file |
| `enriched_id` | UUID | FK → EnrichedRecord |
| `label` | str\|None | |
| `confidence` | float | |
| `all_scores` | JSON | per-class scores |
| `review_route` | str | `accept\|llm_judge\|human_review` |
| `smells` | JSON | list of fired smell names |
| `risk_score` | int | |
| `smell_review_suggested` | bool | |
| `foreign_municipality` | str\|None | municipality name if detected |
| `second_opinion_label` | str\|None | None when second opinion disabled |
| `classifier_disagreement` | bool | |
| `created_at` | datetime | |

## Tasks

See `todo_stage4.md` for the full task list and parallel execution map.
