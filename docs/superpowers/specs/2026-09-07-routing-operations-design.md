# Routing operations — design

## Problem

`RoutingNode.run` takes a 24-field `RoutingInput`. Three callers construct one:

| Caller | Owns | Restates | Absent |
|---|---|---|---|
| `coordinator.py:152` (machine pass) | 2 | 20 | 2 |
| `endpoints.py:149` (human decision) | 4 (+1 derived) | 19 | 0 |
| `endpoints.py:207` (reopen) | 1 | 23 | 0 |

The two human callers share `_reroute` (`endpoints.py:83-110`), a 27-line helper whose
only job is restating fields the endpoint has no opinion about.

**The finding that motivates this work:** `_save_record` already loads the record itself.
`routing.py:66` calls `self.classification_repo.find_by_job_id(routing_input.job_id)`,
through the *same* `IClassificationRecordRepository` the endpoints use at
`endpoints.py:125` and `:185`. So all 19 restated fields are values the node re-reads from
the same row, one call later.

`_reroute` exists to hand the node data it is about to fetch anyway.

**Why this is a bug class, not a style complaint.** Every field of `RoutingInput` has a
pydantic default, so omitting one from `_reroute` is silent — it writes `None` over live
data. Two instances have been found and fixed:

- `original_label` fabricated on a legacy reopen (caught by a failing test during the
  reopen feature's own implementation)
- `judge_final_label` and `judge_reasoning` nulled on every human decision — 14 records
  damaged before it was noticed, and unrecoverable, since a rejected verdict names a
  category stored nowhere else

Both are fixed. The shape that produced them is unchanged, and a 25th field added tomorrow
can be forgotten the same way.

### Two dead arguments, proven

`_reroute` passes both write-once fields back to the node, and neither can have any
effect:

- `machine_review_route` — the guard reads `record.machine_review_route`, not the input
  (`routing.py:106`). A non-`None` stored value skips the branch; a `None` one means
  `_reroute` passed `None` too, falling through to `routing_input.review_route`.
- `expected_label` — if the record has one, `_reroute` passes it back and the guard
  reassigns it to itself (`routing.py:102-103`).

## Scope

**In:** two named operations on `RoutingNode` for the human paths, and deleting
`_reroute`.

**Out:** any change to `ClassificationRecord`'s schema — no migration, no new or renamed
columns. This changes how the record is written, never what it holds. Also out:
`ClassificationUpdate` and `ClassificationState`, the two other parallel field lists — they
belong to the graph, not to routing.

## Design

### The machine pass keeps `RoutingInput`

The coordinator has no record to re-read: on the first pass the row does not exist yet, and
every field comes from graph state. All 24 are genuinely new information there, so the
struct is the right shape for that caller and stays exactly as it is.

```python
async def route(self, ctx: JobContext, routing_input: RoutingInput) -> RoutingResult
```

### The human paths get named operations

```python
async def apply_human_decision(
    self, ctx: JobContext, job_id: str, *, label: str, original_label: str | None
) -> RoutingResult

async def reopen_for_review(self, ctx: JobContext, job_id: str) -> RoutingResult
```

Each loads the record, mutates only what its path owns, and leaves everything else
untouched **by not naming it**. Pass-through stops being something a caller performs.

Ticket 01 established that the two paths differ in exactly four arguments — `label`,
`review_route`, `human_overridden`, `capture_prediction` — and that everything else about
them already differs *outside* `_reroute`: the precondition guard, the exception type, the
audit event, and `require_admin` on reopen only. Two operations, not one with flags.

### `original_label` stays caller-controlled

The three write-once fields are not enforced the same way, and deliberately so:

| Field | Enforcement |
|---|---|
| `expected_label` | Record-side guard (`routing.py:102`) |
| `machine_review_route` | Record-side guard (`routing.py:106`) |
| `original_label` | Caller supplies; the operation decides |

A record-side guard on `original_label` was considered and rejected: the machine pass
legitimately writes it when re-running over an existing record, and a NULL-only guard would
block that. Keeping it caller-controlled means `apply_human_decision` takes it explicitly
rather than inheriting the `capture_prediction` flag — the *decision* moves into the
operation's signature, where a reader can see it, instead of a boolean threaded through a
shared helper.

`reopen_for_review` never takes it, so the fabrication bug becomes unrepresentable on that
path.

## Consequences

**Locality.** Adding a 25th classification signal touches the model, `RoutingInput`, and
the machine pass. The human paths cannot be affected, because they no longer name fields.

**Leverage.** The endpoints learn two verbs instead of 24 field names. `_reroute`'s 27
lines disappear.

**Testability.** `tests/api/routes/test_classification.py:136-144` hand-mutates four fields
to fabricate a decided record, because no "decide" operation exists to call. With one, that
setup becomes a single call — and the decision→reopen sequence gains coverage nothing
currently provides.

**Cost.** `RoutingNode` grows from one public method to three, and two shapes coexist —
`RoutingInput` for the machine, plain arguments for humans. That is the honest cost of the
callers genuinely differing.

## Rejected alternatives

**One operation for all three callers.** The machine pass writes a record that does not
exist yet; the human paths update one that does. Collapsing them needs an explicit
create-vs-update split, which is more interface than the two-shape version, not less.

**Record-side guard on `original_label`.** Would make the fabrication bug impossible
everywhere, but breaks a legitimate machine-pass re-run. Rejected in favour of removing the
field from the reopen path entirely, which fixes the observed bug without the collateral.

**Fixing `capture_prediction` alone.** It dissolves under this design. Fixing it in place
would leave the 19 restated fields untouched — the actual defect.

**Deleting `RoutingInput` outright.** Its fields are all genuinely new for the machine
pass. Removing it would replace one struct with 24 parameters.

## Open question

**Does the audit record move into the operations?** The endpoints write their audit entry
before calling routing, deliberately — the reopen's entry must exist even if routing then
fails. Left as-is; revisit only if a caller forgets one.
