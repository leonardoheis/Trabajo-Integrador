# CI, SonarQube and release automation — design

## Problem

Classiflow has a single verification gate (`uv run poe check`) that only ever runs on a
developer's machine. Nothing verifies a pull request, no coverage floor is enforced, and
there is no way to cut a release: no `.github/`, no `CHANGELOG.md`, no tags.

The configuration for half of this already exists and is simply never executed:

| Present | Missing |
|---|---|
| `versioning` group with `python-semantic-release==10.3.1` | any workflow that runs it |
| `[tool.semantic_release]` config, `allow_zero_version = true` | `version-bump` poe task |
| `__version__` in `src/classiflow/__init__.py` | `CHANGELOG.md` |
| `poe coverage` emits `coverage.xml` + `pytest-report.xml` | a coverage floor, and anything reading those files |

The reference implementation is `CFO_Copilot`, the same author's project, which has
`lint_and_test.yml`, `publish.yml`, SonarQube and a coverage gate. This spec adapts that
shape rather than inventing one.

## Scope

**In:** a CI workflow, SonarCloud analysis, a release workflow that tags and publishes a
GitHub release, a `version-bump` task, a seeded changelog, and a coverage floor.

**Out — deliberately, and this is the main departure from CFO_Copilot:**

**No deploy job.** Classiflow needs a GPU: llama.cpp for classification and chat, BETO for
the second opinion, and the sentence-transformers embedder. Vercel, Netlify and the free
container tiers provide none, and a GPU instance is a real recurring cost the project has
decided not to carry. A GitHub release publishes `dist/*` against a tag — no
infrastructure, no bill — and anyone with their own GPU can install it. CFO_Copilot's
`deploy.yml` has no counterpart here.

**No self-committing CI.** CFO's `lint` and `versioning` jobs commit their own fixes back
to the branch and then fail deliberately to force a re-run. That needs a `PUSH_TOKEN` with
write access, and a job that rewrites the branch under the author is surprising enough to
be worth avoiding. CI reports; the developer fixes locally. `uv run poe check` already
runs before every commit here, so this path would almost never fire.

**No container publishing.** Follows from having nothing to deploy to.

## Design

### Three jobs, split by install cost

The expensive part of this repo is its dependency tree: torch, easyocr, transformers,
chromadb and llama-cpp-python are multi-gigabyte. Splitting keeps the common failures
fast:

| Job | Installs | Expected |
|---|---|---|
| `lint` | ruff only | ~30 s |
| `frontend` | Node + npm | ~1 min |
| `test` | the full ML stack | 8-15 min cold, 3-5 min warm |

`astral-sh/setup-uv` caches on the `uv.lock` hash, so the third job only re-downloads when
dependencies actually change. The repository is public, so GitHub Actions minutes are
unmetered and SonarCloud is free — the cost concern that motivated the split is about
feedback latency, not billing.

If `test` still proves too slow, two levers exist and are deliberately not used yet:
overriding torch to CPU wheels in CI (the `cu128` index pin is for local GPU work; tests
never touch the GPU), and restricting `test` to pull requests and `main` rather than every
push. Neither is worth doing before measuring.

### SonarCloud

Organization `leonardoheis`, project key `leonardoheis_Classiflow`. Both report files
`poe coverage` already writes are fed in:

- `coverage.xml` → `sonar.python.coverage.reportPaths`
- `tests/reports/pytest-report.xml` → `sonar.python.xunit.reportPath`

Note the path differs from CFO_Copilot's, which writes to the repository root.

Coverage exclusions mirror the things that cannot be meaningfully unit-tested: the
frontend's TypeScript (covered by vitest instead, which Sonar is not reading),
`__main__.py`, and `settings.py`.

### Coverage floor at 90

Current coverage is 95%. CFO_Copilot uses 80, which here would be a ceiling rather than a
floor — it would permit a 15-point regression without complaint. 90 leaves working room
while still failing on a real drop, and the intent is to raise it as the number stabilises.

`poe coverage` already produces the data; the gate is one new task reading it.

### Versioning starts at 0.1.0

No tags exist. `__version__` is `0.1.0` and `allow_zero_version = true`, so semantic
release begins there and every `feat:` is a minor bump while below 1.0.

The history is already conventional — 171 `feat:`, 22 `fix:`, 24 `docs:`, 16 `chore:`,
13 `refactor:` across 366 commits on `main`. Retroactively tagging some earlier commit to
"account for" that history was considered and rejected: it invents a release that never
happened, and the version number only needs to be meaningful going forward. The first
release after this lands is `0.2.0`, driven by the `feat:` commits merged since.

Worth knowing: `allowed_tags = ["chore", "feat", "fix"]` in the existing config means the
`docs:` and `refactor:` commits do not affect the version at all. That is the existing
choice and this spec does not change it.

### Release flow

`publish.yml` triggers on a successful CI run against `main`, plus manual dispatch:

```
uv build  ->  semantic-release computes version  ->  git tag  ->
extract that version's changelog section  ->  GitHub release with dist/*
```

Frontend build output is verified in CI but not published — the release is the Python
package.

## Consequences

**A pull request is verified before it is merged**, rather than relying on the author
having run `poe check`. PR #33 — 13 commits, 102 files, six features — is precisely the
case where that matters.

**Coverage cannot silently rot.** The 95% figure becomes a defended property.

**Releases become mechanical**, driven by commit messages that are already written in the
right format.

**Cost:** three workflow files, one poe task, one changelog, and a slower feedback loop on
the `test` job than running locally. Sonar adds a second opinion on code quality that may
disagree with ruff and mypy — the intent is to treat it as advisory, not to chase its
score.

## Rejected alternatives

**Copy `deploy.yml` from CFO_Copilot.** Rejected on hardware: no free tier offers the GPU
this project requires, and paying for one is out of scope.

**One monolithic CI job.** Simpler to write, but a ruff error would take 10 minutes to
surface behind a torch download. The split is the whole point.

**Coverage gate at 95 to lock in today's number.** Rejected as brittle: a single
legitimately-untestable branch would break the build, and the gate would be tuned down
under pressure rather than treated as a floor.

**`pytest-cov --cov-fail-under` instead of a separate task.** Rejected because
`poe coverage` is inside `poe check`, so a failing gate would block local development on a
number CI is better placed to enforce.

## Open questions

**Should `test` run on every push, or only on pull requests and `main`?** Left running
everywhere initially; revisit once real timings exist rather than guessing.

**Does the frontend deserve its own coverage gate?** 38 vitest tests exist with no
threshold. Out of scope here; the Python floor is the one that guards the pipeline.
