# Design: Integrating `bert_tunning`'s trained classifier into Stage 4

## Context

`tasks/plan_stage4.md` already plans a "Second Opinion Agent" explicitly described as
*"equivalent to bert_tunning's SVM reviewer"* — but as a second LLM call with a different
persona, not the real trained model. `bert_tunning` (sibling project,
`../bert_tunning`) is a mature, already-shipped Spanish municipal document classifier:
a fine-tuned BETO (Spanish BERT) model with a calibrated 4-signal OOD detector
(Mahalanobis / cosine / k-NN / TF-IDF) and an independent SVM reviewer, all wrapped in
one `BertTunningClassifier.predict_text(text) -> PredictResult` call. Its own
`schemas.py` comments this integration was anticipated from that side already ("for the
downstream Classiflow agent").

This spec replaces that placeholder with the real model.

## Decisions

### 1. BERT's role: Second Opinion Agent in Stage 4, not a new Stage 3 step

Stage 3's own stated responsibility is producing an `EnrichedRecord` "ready for
classification" — it doesn't classify. Classification is Stage 4's job, both per its
name and per the architecture diagram (`Classification agent — document type ·
confidence score` is its own box). Stage 4 already plans a Primary Classification
Agent (LLM, `label`/`confidence`/`all_scores`) and a Second Opinion Agent whose
current placeholder (second LLM call) this design replaces with `bert_tunning`'s real
model — the Confidence Gate and `classifier_disagreement` logic in `plan_stage4.md`
stay conceptually the same, just fed by a real independent model instead of a second
LLM persona.

### 2. Integration shape: port the scoring code, don't depend on the package, don't call it as a service

Three options considered:

| Option | Verdict |
|---|---|
| `uv add --editable ../bert_tunning`, call `BertTunningClassifier` directly | Rejected — pulls `bert_tunning`'s entire dependency tree (`fastapi`, `uvicorn`, `wandb`, `plotly`, `click`, `pandas`, `pyarrow`, `accelerate`, `sentencepiece`, plus duplicate `markitdown`/`easyocr`/`PyMuPDF` Classiflow already has) for code that only needs a handful of those packages. Real cost on a resource-limited dev machine. |
| Call `bert_tunning`'s `/predict` HTTP endpoint as a sidecar service | Rejected — that endpoint is job-polling (built for batch/UI use), not a low-latency synchronous call inside an already-async pipeline node; adds a second service to run/deploy/monitor (Docker included) for no benefit here. |
| **Port (copy + adapt) just the scoring modules** | **Chosen.** Checked their actual imports directly: `ood.py`, `embeddings.py`, `svm_reviewer.py`, `inference/classify.py`, `inference/ood_scorer.py` need only `numpy` (already present), `torch` (already present), plus **`scipy`, `scikit-learn` (brings `joblib`), `transformers`** — 3 new packages, none of the serving/training/logging bloat. `clean_text`/`detect_foreign_municipality` (`ingestion/_text.py`) are pure-regex, stdlib only. |

**Accepted cost of porting, stated explicitly:** this is a copy, not a live link. If
`bert_tunning`'s OOD/SVM math gets bug-fixed or recalibrated later, Classiflow's copy
doesn't inherit that automatically — someone re-ports it by hand. User confirmed this
tradeoff is acceptable ("I can live with a manual calibration between projects").

### 3. Package location: new top-level `classification/`, not inside `ingesta/`

`src/classiflow/classification/` — sibling to `ingesta/`, not nested under it. Stage 4
is conceptually independent of Stage 1/2's ingestion pipeline; nesting it under
`ingesta` would misrepresent that.

### 4. Shared infrastructure relocates to neutral ground

Two pieces of existing `ingesta`-owned code are genuinely generic, not
extraction-specific, and both `ingesta` and `classification` need them:

- **`BaseNode`** (currently `classiflow.ingesta.nodes.base`) → moves to
  **`classiflow.pipeline.base`**. It only wraps `AuditService` + `EventBroadcaster`
  into `_emit_started`/`_emit_and_audit` — nothing about it is ingestion-specific.
  `ingesta/nodes/base.py` is deleted; its 5 current importers (`node1_file_reception`,
  `node2_format_validation`, `node3_content_validation`, `node4_duplicate_control`,
  `extraction_step`) switch their import to `classiflow.pipeline.base`.
  `classification/nodes/*` imports from the same place.
- **`config_loader.py`'s `load_yaml_config()`** (currently
  `classiflow.ingesta.config_loader`) → moves to **`classiflow.config_loader`**
  (top-level, sibling to `settings.py`) for the identical reason — it's generic YAML
  config loading, not pipeline- or ingestion-specific. `ingesta`'s 4 config modules
  (`config.py`, `config_content.py`, `config_duplicate.py`, `config_extraction.py`)
  switch their import; `classification/config_classification.py` uses the same
  relocated helper instead of a 5th near-duplicate.

### 5. Label space mismatch between BETO v2 and Classiflow's 10 categories

Checked BETO v2's actual trained labels (`config.json`'s `id2label`):

```
boletines, declaracion_concejo_municipal, decreto, decreto_ordenanza,
decretos_concejo_municipal, ordenanza, otro, resolucion, resolucion_concejo_municipal
```

vs. Classiflow's 10 categories (`README.md`): same concepts, mostly just singular
Spanish (BETO) vs. plural snake_case (Classiflow, matching the CSV filenames) — needs
a normalization map. Two real gaps, not cosmetic:

- **`convenios`** and **`compendios_de_boletines`** — Classiflow categories BETO was
  **never trained on**. It cannot predict these under any circumstances.
- **`otro`** — BETO's catch-all class; Classiflow's taxonomy has no equivalent.

**Handling:** a label-normalization map translates BETO's singular labels to
Classiflow's plural ones. When the primary (LLM) label is `convenios` or
`compendios_de_boletines` (outside BETO's trained set), or BERT's own label is `otro`
(outside Classiflow's set), `classifier_disagreement` is `False` — BERT is treated as
having **no opinion**, not as forcibly disagreeing. This mirrors `bert_tunning`'s own
`svm_agrees_with_prediction` default-`True`-on-missing-signal pattern (documented in
its `schemas.py`) rather than inventing a new convention.

```python
_LABEL_NORMALIZE = {
    "boletines": "boletines",
    "declaracion_concejo_municipal": "declaraciones_concejo_municipal",
    "decreto": "decretos",
    "decreto_ordenanza": "decreto_ordenanzas",
    "decretos_concejo_municipal": "decretos_concejo_municipal",
    "ordenanza": "ordenanzas",
    "resolucion": "resoluciones",
    "resolucion_concejo_municipal": "resoluciones_concejo_municipal",
    "otro": None,  # BETO's catch-all -- no Classiflow category equivalent
}
```

## File layout

```
src/classiflow/pipeline/
└── base.py                        BaseNode (moved from ingesta/nodes/base.py, unchanged)

src/classiflow/config_loader.py    load_yaml_config() (moved from ingesta/config_loader.py, unchanged)

src/classiflow/classification/
├── config_classification.py       ClassificationConfig + get_classification_config()
│                                   — loads config/classification.yaml via the relocated
│                                   config_loader.load_yaml_config()
├── domain/
│   └── results.py                 ClassificationResult(BaseEntity)
├── bert/                          ported from bert_tunning, adapted to BaseEntity
│   ├── ood.py                     Mahalanobis/cosine/k-NN/TF-IDF math + PCA projection
│   ├── ood_scorer.py              OodScorer.load() / .score()
│   ├── embeddings.py              BETO forward pass -> [CLS] embeddings
│   ├── svm_reviewer.py            SVM load + per-class scoring
│   ├── smell_thresholds.py        smell_thresholds.json loader
│   ├── text_cleaning.py           clean_text / detect_foreign_municipality (pure regex)
│   ├── label_mapping.py           _LABEL_NORMALIZE + classifier_disagreement helper
│   └── classifier.py              BertClassifier.predict_text() — combined entry point
├── nodes/
│   ├── primary_classifier.py      LLM-based, same Phi-4-mini pattern as node2/node3
│   ├── second_opinion.py          wraps BertClassifier; computes classifier_disagreement
│   ├── smells_risk.py             foreign_municipality + smells + risk_score
│   ├── confidence_gate.py         review_route decision
│   ├── llm_judge.py
│   └── routing.py
└── coordinator.py                 build_classification_coordinator(...)

models/bert_tunning_beto_v2/       copied from ../bert_tunning/models/bert_tunning_model_beto_v2/final/
                                    (config.json, model.safetensors, tokenizer files,
                                    ood_stats.npz, smell_thresholds.json, svm_classifiers.joblib)

config/classification.yaml         new
```

## Config — `config/classification.yaml`

```yaml
confidence_threshold: 0.75
smell_review_risk_threshold: 4
max_input_tokens: 512
second_opinion_enabled: true
foreign_municipality_enabled: true

bert_model_path: models/bert_tunning_beto_v2   # relative to project root

# Fallback OOD thresholds, only used if a model's own ood_stats.npz isn't calibrated
# (mirrors bert_tunning's own uncalibrated-fallback design). BETO v2 ships pre-calibrated,
# so these are a safety net for future retrained models, not what BETO v2 itself uses.
ood_mahalanobis_p_threshold: 0.001
ood_cosine_threshold: 13.7366
ood_knn_distance_threshold: 26.125
ood_tfidf_cosine_threshold: 2.5
ood_pca_components: 64
ood_trained_municipality: rosario
```

## DB model — `ClassificationRecord`

Revised from `plan_stage4.md`'s original sketch: `file_id: UUID` didn't match this
project's actual schema, which keys everything off `job_id: str` (`Job`,
`DocumentStep`, `AuditRecord` all use it) — corrected here.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `job_id` | str | FK → `Job`, matching every other table's key |
| `enriched_id` | UUID | FK → `EnrichedRecord` (Stage 3) |
| `label` | str \| None | primary LLM classifier |
| `confidence` | float | primary classifier |
| `all_scores` | JSON | primary classifier per-class scores |
| `second_opinion_label` | str \| None | BERT's raw label (its own taxonomy, pre-normalization) |
| `second_opinion_confidence` | float | BERT's own softmax confidence |
| `classifier_disagreement` | bool | via `_LABEL_NORMALIZE`; `False` (not forced) when either label falls outside the mappable set |
| `ood_metrics` | JSON \| None | full `OodMetrics` blob; `None` only if no `ood_stats.npz` loaded |
| `svm_scores` | JSON | per-class SVM margins; `{}` if no SVM loaded |
| `svm_agrees_with_prediction` | bool | BERT-vs-its-own-SVM (distinct signal from `classifier_disagreement`) |
| `review_route` | str | `accept` \| `llm_judge` \| `human_review` |
| `smells` | JSON | fired smell names |
| `risk_score` | int | |
| `smell_review_suggested` | bool | |
| `foreign_municipality` | str \| None | |
| `created_at` | datetime | |

## Open items / risks

| Risk | Mitigation |
|---|---|
| Ported OOD/SVM code drifts from `bert_tunning`'s own as either project evolves | Accepted tradeoff (see Decision 2) — manual re-port when needed, not automatic |
| `transformers`/`scipy`/`scikit-learn` add real install weight even trimmed down | Smaller than the alternatives; no path avoids loading the actual BETO weights + SVM |
| `models/bert_tunning_beto_v2` (verified on disk: 425MB total — `model.safetensors` 420MB, `svm_classifiers.joblib` 2.5MB, `tokenizer.json` 744KB, `ood_stats.npz` 1.9MB, `smell_thresholds.json` 1KB; `training_args.bin` not copied — HF `Trainer` hyperparameters, unused at inference) committed nowhere, same as the existing SLM/embedding models | Follows the same `models/**` + `.gitkeep` gitignore pattern Stage 2 already established; document fetch/copy steps in README's Models section |
| Relocating `BaseNode`/`config_loader.py` touches already-shipped Stage 1/2 code | Small, mechanical import-path changes only — no behavior change; covered by existing test suite |
| Primary Classification Agent / Confidence Gate / LLM Judge / Routing Agent components not detailed in this spec | Out of scope here — `plan_stage4.md`'s existing description of these (LLM-based primary classifier, Confidence Gate logic, `llm_judge` tier, Routing Agent's accept/review/directory behavior) is unchanged by this design; this spec only concerns the Second Opinion Agent's new BERT backing and the shared-infrastructure relocation it required |
