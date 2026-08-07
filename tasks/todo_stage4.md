# Classiflow — Stage 4 Task List

> Prerequisite: Stage 3 complete (EnrichedRecord exists in DB) + LLM provider (T11).
> Full details in [plan_stage4.md](plan_stage4.md).
> Status: `[ ]` pending · `[~]` in progress · `[x]` done · `[-]` skipped · `[!]` blocked

---

## Parallel Execution Map

```
BATCH 0  ──────────────────────────────────────────── parallel (no dependencies)
  S4-T01  ClassificationRecord DB model + Alembic migration
  S4-T02  Primary classification agent (LLM chain)  (needs T11)
  S4-T04  Foreign municipality detector

BATCH 1  ──────────────────────────────────────────── parallel
  S4-T03  Second opinion agent                       (needs S4-T02)
  S4-T07  LLM judge                                  (needs T11)

BATCH 2  ──────────────────────────────────────────── sequential
  S4-T05  Smells + risk score                        (needs S4-T02 + S4-T03 + S4-T04)

BATCH 3  ──────────────────────────────────────────── sequential
  S4-T06  Confidence gate + ReviewRoute decision     (needs S4-T05)

BATCH 4  ──────────────────────────────────────────── sequential
  S4-T08  Routing agent + audit log writer           (needs S4-T06 + S4-T07)

BATCH 5  ──────────────────────────────────────────── sequential
  S4-T09  Stage 4 coordinator (LangGraph)            (needs S4-T08)
```

---

## Task Details

- [ ] **S4-T01** — ClassificationRecord DB model + Alembic migration
      Branch: `feat/classification-model`

- [ ] **S4-T02** — Primary classification agent: LLM chain → `label`, `confidence`, `all_scores`
      Branch: `feat/classification-agent`

- [ ] **S4-T03** — Second opinion agent: second LLM call → `classifier_disagreement`
      Branch: `feat/second-opinion`

- [ ] **S4-T04** — Foreign municipality detector
      Branch: `feat/foreign-municipality`

- [ ] **S4-T05** — Smells collector + risk score computation (adapted from bert_tunning `_SMELL_WEIGHTS`)
      Branch: `feat/smells`

- [ ] **S4-T06** — Confidence gate: `decide_review_route` → `ReviewRoute` + `smell_review_suggested`
      Branch: `feat/confidence-gate`

- [ ] **S4-T07** — LLM judge: focused full-text second pass for `llm_judge` tier
      Branch: `feat/llm-judge`

- [ ] **S4-T08** — Routing agent: directory assignment + audit log write for every decision
      Branch: `feat/routing-agent`

- [ ] **S4-T09** — Stage 4 LangGraph coordinator: classify → gate → (judge?) → route
      Branch: `feat/stage4-coordinator`
