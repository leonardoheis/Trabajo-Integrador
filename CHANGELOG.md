# CHANGELOG

<!-- version list -->

## v0.5.0 (2026-09-08)

### Bug Fixes

- **ci**: Pin Python 3.10 so torch and torchvision resolve compatibly
  ([`a17eb15`](https://github.com/leonardoheis/Trabajo-Integrador/commit/a17eb15fad3890f273aee2bf482584dcf34b22ce))

- **ci**: Write the version before building the release
  ([`8576acf`](https://github.com/leonardoheis/Trabajo-Integrador/commit/8576acf35b87ae0800771542f415cac6612edf8d))

### Features

- Add implementation plans for CI, SonarQube, and routing operations
  ([`ecf7589`](https://github.com/leonardoheis/Trabajo-Integrador/commit/ecf7589e7a3a5a8b0d2a7d58a8df79c17c35008c))


<!--
Sections below v0.5.0 were written by hand: the tags were backfilled onto the merge
commits of PRs #30-#34 after the fact, so no release ever ran to generate them.
Everything from v0.5.0 onward is appended by python-semantic-release.
-->

## v0.4.0 (2026-09-07)

PR #34 - routing operations.

### Features

- `RoutingNode` exposes `apply_human_decision` and `reopen_for_review` instead of taking a
  24-field struct on the human paths. The endpoints stopped restating 19 fields the node
  reloads for itself; `_reroute` and its `capture_prediction` flag are gone.
- Classification list defaults to newest first.

## v0.3.0 (2026-09-07)

PR #33 - accuracy measurement, GPU residency, reopen review.

### Features

- Classification accuracy measured from the live database rather than a notebook:
  migrations 0014-0016, `MetricsService`, `GET /classification/metrics`, `MetricsPage`,
  and the `poe accuracy` CLI.
- Ground truth derived from the corpus filing convention (`classification/ground_truth.py`).
- Admin-only reopen of a decided classification, plus first/last page controls in the PDF
  viewer.
- `GpuResidency` replaces five directly-imported unloaders, with `InFlightCounter` backing
  the chat and pipeline guards.
- Database dialect tuning: adding an engine adds a file under `database/dialects/`.
- Judge verdicts survive a human decision, and the judge's `final_label` is written to the
  audit log so a lost verdict stays recoverable.
- Conversation memory takes a configurable window and batch size.

### Bug Fixes

- Sign-out releases every resident model and resets in-flight generation counters.
- SQLite concurrency: WAL journal mode and a busy timeout, fixing `database is locked`
  under bulk ingest.
- Entity extraction survives malformed LLM JSON - unescaped quotes are repaired, a numeric
  act number is coerced, and an unparsable response degrades instead of failing the job.

## v0.2.0 (2026-09-01)

PR #32 - classification search and sort.

### Features

- Search matches label or filename; `indexed` became a sortable column.
- Pipeline warmup on page mount, and job discard.
- Review queue surfaced in the sidebar, and user profiles carry a picture.

## v0.1.0 (2026-08-31)

PR #30 - chat, retrieval, and the pipeline UI.

### Features

- Chat conversation memory: recent turns verbatim, older ones folded into a summary.
- Token streaming with a cold-start indicator, and markdown rendering in chat.
- Every pipeline step's detail is inspectable, and completed phases expand.
- Archive Daylight theme.
- Retrieval tuning: filename detection, chunk overlap, and top-k.
