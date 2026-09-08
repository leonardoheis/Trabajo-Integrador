# CI, SonarQube and release automation — implementation plan

Design: `docs/superpowers/specs/2026-09-07-ci-release-sonarqube-design.md`

Branch: `ci/github-actions-and-release`, cut from `main` after PR #33 merged.

Reference implementation: `/c/Users/leona/source/repos/CFO_Copilot` — same author, same
`uv` + `poe` + semantic-release toolchain. Read its `.github/workflows/` before writing
each file, but do not copy `deploy.yml` or the self-committing pattern (see the spec).

## Global constraints

- **No deploy job, no container publishing.** Classiflow needs a GPU; nothing free
  provides one. A GitHub release publishes `dist/*` against a tag and costs nothing.
- **No self-committing CI.** No `PUSH_TOKEN`, no job that rewrites the author's branch.
  CI reports; the developer fixes locally.
- Every workflow must be runnable via `workflow_dispatch` so it can be tested without
  pushing junk commits.
- `uv run poe check` must stay the single local gate — CI runs the same tasks, never a
  divergent set of commands.
- Do not stage, commit, push, or open a PR without explicit authorization.

## Task 1: The coverage gate

**Files:** modify `pyproject.toml`

- [x] Add a `check-coverage` poe task: `coverage report --fail-under=90`. Follows
  CFO_Copilot's task of the same name, at 90 rather than 80 — current coverage is 95%, so
  80 would be a ceiling rather than a floor.
- [x] Do **not** add it to the `check` sequence. `poe check` already runs `coverage`, and
  a local build should not fail on a threshold CI is better placed to enforce.
- [x] Confirm `[tool.coverage.report]` has the omissions the gate needs — `__main__.py`,
  `settings.py`, and anything else that cannot be meaningfully unit-tested. Add the
  section if it does not exist.

```bash
uv run poe coverage && uv run poe check-coverage
```

Must print the current figure and exit 0. If it fails, the omit list is wrong — fix that,
not the threshold.

**Done 2026-09-08.** Coverage went **up**, 94% -> 96%, because the omissions removed
what the suite cannot reach rather than what it fails to test -- alembic's `downgrade()`
was the main drag, and each migration already has its own end-to-end test.

Followed CFO_Copilot's shape: `source = ["src", "tests"]` rather than the previous bare
`--cov=.`, plus `show_missing`/`skip_covered`. Did **not** copy its `parallel = true` --
that is for multi-process runs this suite does not do and would need a `coverage combine`
step.

`dependency_injector` is a Cython package whose compiled module reports its origin as a
`.pyx` path resolving under this repo's `src/`, which coverage cannot read. It is absent
from `coverage.xml`, so CI and Sonar are unaffected; only the terminal report needs `-i`.

Verified the gate is not a no-op: exit 2 at `--fail-under=97`, exit 0 at 90.

**Suggested commit boundary:** coverage floor at 90%.

## Task 2: The CI workflow

**Files:** add `.github/workflows/lint_and_test.yml`

Three jobs, split so a ruff error does not wait behind a torch download.

- [x] `lint`: checkout, `astral-sh/setup-uv@v6` pinned to the `uv` version in
  `[dependency-groups] dev` (0.8.9), `uv sync --group dev`, then `uv run poe lint` and
  `uv run poe typecheck`. No ML dependencies needed.
- [x] `frontend`: `actions/setup-node@v4`, `npm ci` in `src/classiflow/frontend`, then
  `npx vitest run` and `npm run build`. Independent of the Python jobs.
- [x] `test`: `uv sync`, `uv run poe coverage`, then `uv run poe check-coverage`. This is
  the expensive job — checkout with `fetch-depth: 0`, which SonarQube needs for blame
  data.
- [x] Triggers: `push` and `pull_request` on `main`, plus `workflow_dispatch`.
- [x] Publish the test report with `dorny/test-reporter@v2` reading
  `tests/reports/pytest-report.xml`. **Note the path differs from CFO_Copilot's**, which
  writes to the repository root — check `poe coverage`'s `--junitxml` argument rather than
  assuming.

```bash
gh workflow run "Lint and Test" --ref ci/github-actions-and-release
gh run watch
```

**Done 2026-09-08.** All three jobs' commands verified locally before pushing.

`dorny/test-reporter` reads `tests/reports/pytest-report.xml` -- **not** the repo root
CFO_Copilot uses -- with `reporter: java-junit`, which is what pytest's `--junitxml`
emits.

**Install size, measured rather than guessed:** the venv is **5.9GB, of which torch is
4.2GB**, plus 15 `nvidia-*` CUDA runtime packages. `uv.lock` pins `torch 2.11.0+cu128`
via an explicit `[[tool.uv.index]]` for every non-darwin platform, and `--frozen` means
CI installs exactly that -- for a suite that never opens a GPU.

`UV_TORCH_BACKEND=cpu` was tested and proved inconclusive locally: the existing venv
already satisfies the lock, so a dry run shows no change, and whether the variable
overrides an explicit index pin cannot be settled without a clean environment.

Shipping as-is deliberately. It fits the runner's ~14GB and the uv cache makes repeat runs
cheap, so the first real run turns this from speculation into a number. If the cold run is
painful, the fix is to make the CUDA index conditional in `pyproject.toml` -- which
changes `uv.lock` and needs the local GPU setup re-verified, so it is not worth doing
blind.

**Suggested commit boundary:** CI workflow with lint, frontend and test jobs.

## Task 3: SonarCloud analysis

**Files:** modify `.github/workflows/lint_and_test.yml`

- [x] Add a `SonarSource/sonarqube-scan-action@v5` step to the `test` job, after the tests
  and before the coverage gate, guarded with
  `if: ${{ !cancelled() && env.SONAR_TOKEN != '' }}` so a fork without the secret still
  passes.
- [x] Arguments: `sonar.organization=leonardoheis`,
  `sonar.projectKey=leonardoheis_Classiflow`, `sonar.sources=src`, `sonar.tests=tests`,
  `sonar.python.version=3.10` (matching `requires-python`, **not** CFO_Copilot's 3.12),
  `sonar.python.coverage.reportPaths=coverage.xml`, and
  `sonar.python.xunit.reportPath=tests/reports/pytest-report.xml`.
- [x] Coverage exclusions: `**/__main__.py`, `src/classiflow/settings.py`,
  `src/classiflow/frontend/**` (TypeScript is covered by vitest, which Sonar is not
  reading), `src/classiflow/playground/**`.
- [x] **For the user:** create the project in SonarCloud and add `SONAR_TOKEN` to the
  repository secrets. The scan step no-ops without it, so this task can land before the
  secret exists.

**Done 2026-09-08.** Two corrections to what the plan specified:

`SONAR_TOKEN` is set at **job** level, not on the step. An `if:` expression reads env
from the job, never from the step it guards -- placed on the step, the guard would have
evaluated empty and skipped the scan permanently. CFO_Copilot does this correctly and it
is easy to miss.

Added `sonar.exclusions` for the frontend and playground, which the plan did not call
for. `sonar.coverage.exclusions` alone only stops Sonar reporting them as uncovered; it
still analyses them. The frontend has its own vitest suite Sonar cannot see, so leaving it
in scope would report a large body of untested TypeScript. With the real exclusion in
place, those two paths were dropped from the coverage list as redundant.

`sonar.python.version=3.10` matches `requires-python`, not CFO_Copilot's 3.12.

The scan is guarded, so this lands green before the SonarCloud project exists.

**Suggested commit boundary:** SonarCloud analysis on the test job.

## Task 4: Version bump task and changelog seed

**Files:** modify `pyproject.toml`, add `CHANGELOG.md`

- [ ] Add the `version-bump` poe task, copied from CFO_Copilot:
  `uv run semantic-release -v version --no-tag --no-commit --skip-build --changelog`.
- [ ] Seed `CHANGELOG.md` with a heading and nothing else. semantic-release appends;
  `changelog-parser` in Task 5 needs the file to exist.
- [ ] Verify the existing `[tool.semantic_release]` block resolves correctly against this
  repo — `version_variables` must point at `src/classiflow/__init__.py:__version__` and
  `version_toml` at `pyproject.toml:project.version`. CFO_Copilot's paths refer to
  `src/app/`; if they were copied verbatim they are wrong here.

```bash
uv run --group versioning poe version-bump
git diff
```

Expect a bump from `0.1.0` to `0.2.0` (the merged work is `feat:`-dominated) and a
populated changelog. **Then `git checkout .` — this task verifies the machinery, it does
not perform the release.**

**Suggested commit boundary:** version-bump task and changelog seed.

## Task 5: The release workflow

**Files:** add `.github/workflows/publish.yml`

- [x] Trigger on `workflow_run` completion of "Lint and Test" against `main`, plus
  `workflow_dispatch`. Guard the job with
  `if: ${{ github.event.workflow_run.conclusion == 'success' }}`.
- [x] Permissions: `contents: write` for the tag and release; `id-token: write`.
- [x] Steps, following CFO_Copilot's `publish.yml`: `uv build` → read the version with
  `semantic-release -v version --print` → create and push the tag → extract that version's
  section with `changelog-parser` → `ncipollo/release-action@v1` with `artifacts: dist/*`.
- [x] **Omit the deploy job entirely.** There is nowhere to deploy to.
- [x] The frontend build is verified in CI but not published — the release artefact is the
  Python package.

Test with `workflow_dispatch` before trusting the automatic trigger.

**Done 2026-09-08.** Two additions the plan did not specify, both found by testing rather
than reasoning:

**An already-released guard.** `semantic-release version --print` returns the *current*
version when no release is due -- verified: it prints `0.4.0` and says "already been
released". Without a guard the tag step would fail on a duplicate. The workflow now checks
`git rev-parse` and skips the build, tag and release steps cleanly. Tested both branches:
`v0.4.0` -> already=true, `v0.5.0` -> already=false.

**`workflow_dispatch` in the job guard.** A manual run has no `workflow_run` context, so
`github.event.workflow_run.conclusion == 'success'` alone would never fire -- making the
workflow untestable by the very mechanism the plan asks to test it with.

`uv build` verified locally: produces `classiflow-0.4.0-py3-none-any.whl` and the sdist,
version matching the tag. `changelog-parser` verified against the hand-written CHANGELOG:
all four versions parse, `versions[0]` is the newest.

Node 22, not the default -- `changelog-parser@4` requires `>=22.12.0`.

**Suggested commit boundary:** release workflow producing a tagged GitHub release.

## Task 6: Document it

**Files:** modify `README.md`, `CLAUDE.md`

- [ ] README: a short CI/release section — what runs on a PR, where the coverage floor
  lives, how a release is cut, and **why there is no deployment** (GPU requirement), so the
  absence reads as a decision rather than an oversight.
- [ ] CLAUDE.md: note that commit messages drive the version, and that only `feat`, `fix`
  and `chore` are in `allowed_tags` — `docs:` and `refactor:` commits do not bump anything.
- [ ] Add the SonarCloud badge to the README once the first scan has run.

**Suggested commit boundary:** document the CI and release process.

## Final verification

```bash
uv run poe check
uv run poe check-coverage
```

- [ ] All three CI jobs pass on this branch.
- [ ] The Sonar scan appears in SonarCloud (or is cleanly skipped when the secret is
  absent).
- [ ] `publish.yml` runs green under `workflow_dispatch` and produces a tag plus a release
  with `dist/*` attached.
- [ ] `git status` is clean — no changelog or version bump committed by accident from
  Task 4's verification.

## Not in this plan

**Deployment of any kind.** The GPU requirement makes free hosting impossible and paid
hosting out of scope. If that changes, a deploy workflow is its own spec.

**A frontend coverage threshold.** 38 vitest tests run with no floor. Worth revisiting,
but the Python gate is the one guarding the classification pipeline.

**Dependabot, CodeQL, release-please.** Each is defensible and none is needed to close the
gap this plan addresses.
