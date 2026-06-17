# Ingesta Pipeline — Task List

Branch: `feat/ingesta-pipeline`
Spec: `ingesta_pipeline.md` (uploaded)
Full plan: `tasks/plan.md`

## Phase 1: Foundation

- [ ] **Task 1** — Package skeleton + dependencies (`pyproject.toml`, `uv sync`, empty `__init__.py` files, stub YAMLs)

**Checkpoint A:** `uv run poe check` passes on empty modules

## Phase 2: Deterministic Agents

- [ ] **Task 2** — Agent 1: File Reception (`agent1_file_reception.py` + `test_agent1.py`)
- [ ] **Task 3** — Config YAMLs + Agent 2 rule-based path (no SLM, `NotImplementedError` stub)

**Checkpoint B:** `uv run poe test` passes for agents 1 and 2

## Phase 3: LLM Integration

- [ ] **Task 4** — LLM Provider singleton (`llm_provider.py`, `MockLlm`, cache test)
- [ ] **Task 5** — Agent 2 SLM path + `prompts/format_validation.py` (LangChain chain)
- [ ] **Task 6** — Agent 3 Content Validation (`agent3_content_validation.py` + `prompts/content_validation.py`)

**Checkpoint C:** Agents 1–3 pass end-to-end with `MockLlm`

## Phase 4: Duplicate Control

- [ ] **Task 7** — Agent 4: Duplicate Control (SHA-256 + FAISS semantic near-duplicate)

**Checkpoint D:** All agent tests green

## Phase 5: Orchestration

- [ ] **Task 8** — Coordinator: LangGraph state machine (`coordinator.py` + integration tests)
- [ ] **Task 9** — Watcher daemon (`watcher.py`, `--dry-run` flag)

**Checkpoint E:** End-to-end dry-run with a sample PDF fixture
