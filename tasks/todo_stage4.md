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

BATCH 6  ──────────────────────────────────────────── parallel (ops/infra — no
                                                        dependency on classification
                                                        logic; moved from Stage 1)
  S4-T10  GitHub Actions CI pipeline
  S4-T11  GitHub Actions Docker build + push          (needs S4-T09, containerizes
                                                        the finished app)
  S4-T12  wandb integration — LLM tracing + metrics   (needs T11 LLM provider, already
                                                        done in Stage 1)
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

- [ ] **S4-T10** — GitHub Actions CI pipeline *(moved from Stage 1 T18)*
      Branch: `feat/ci`
      - [ ] `.github/workflows/ci.yml` triggers on every push and PR
      - [ ] Jobs: `lint` (ruff), `typecheck` (mypy), `test` (pytest + coverage),
            `coverage-gate` (≥ 80%)
      - [ ] `lint` and `typecheck` run in parallel
      - [ ] `test` uploads coverage artifact
      - [ ] All jobs green on first push
      ```bash
      # Verify
      gh run list --limit 5
      gh run view <run-id>
      ```

- [ ] **S4-T11** — GitHub Actions Docker build + push *(moved from Stage 1 T19)*
      Branch: `feat/docker`
      - [ ] `Dockerfile`: `python:3.12-slim`, `apt-get install libmagic1`,
            `uv sync --no-dev`, port 8000
      - [ ] Entrypoint: `uvicorn classiflow.api.app:create_app --factory --host
            0.0.0.0 --port 8000`
      - [ ] `python-magic` detects MIME correctly inside the container
      - [ ] Container accepts `DATABASE_URL`, `JWT_SECRET_KEY`,
            `GOOGLE_CLIENT_ID/SECRET` as env vars
      - [ ] `.github/workflows/docker.yml`: build + push on `main`, build only on PRs
      - [ ] `INSTALL.md` documents `libmagic1` for Linux and the Windows dev workaround
      ```bash
      # Verify
      docker build -t classiflow .
      docker run --env-file .env -p 8000:8000 classiflow
      curl http://localhost:8000/health
      ```

- [ ] **S4-T12** — wandb integration — LLM tracing + per-node metrics
      *(moved from Stage 1 T20)*
      Branch: `feat/wandb`

      **Strategy A — LangChain callback (zero node changes):**
      - [ ] `wandb>=0.17` added to `pyproject.toml`; `uv sync --dev` succeeds
      - [ ] `ingesta/llm_provider.py`: `get_llm_langchain()` accepts optional
            `callbacks` list; production default is
            `[WandbCallbackHandler(project="classiflow")]` when `WANDB_API_KEY` is set
      - [ ] `settings.py` has `WANDB_API_KEY: str = ""` and
            `WANDB_PROJECT: str = "classiflow"`
      - [ ] Every LLM call (node2, node3, and Stage 4's classification agents) logs:
            prompt text, raw output, latency, token count
      - [ ] `WANDB_API_KEY` unset → callbacks list is empty, no wandb import
            side-effects

      **Strategy B — per-node `wandb.log()` (richer metrics):**
      - [ ] Each node's `run()` calls `wandb.log({"node": self.name, "duration_ms":
            duration_ms, "passed": result.passed})` after audit
      - [ ] Node 3 logs additionally: `confidence`, `detected_language`
      - [ ] Node 4 logs additionally: `is_duplicate`, `duplicate_type`,
            `similarity_score`
      - [ ] Guarded by `if settings.WANDB_API_KEY` — no wandb traffic in tests

      **Tests:**
      - [ ] Strategy A: test that `WandbCallbackHandler` is in the callbacks list when
            `WANDB_API_KEY` is set
      - [ ] Strategy B: test that `wandb.log` is called with expected keys (mock
            `wandb.log`)
      - [ ] All existing tests unchanged (wandb disabled when `WANDB_API_KEY` is empty)
      - [ ] `uv run poe check` passes
