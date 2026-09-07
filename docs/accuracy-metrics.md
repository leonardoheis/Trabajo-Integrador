# Classiflow — accuracy metrics

A snapshot of classification performance, and a guide to reading the numbers.

Measured from `data/classiflow.db` on 2026-09-04, after migration `0015`.

> This file is a point-in-time picture. The live figures are on the **Metrics** page in
> the app (`/metrics`), or from `uv run poe accuracy`. Expect the numbers below to drift
> as more documents are ingested; the explanations will not.

---

## The pipeline funnel

Accuracy is measured over scoreable documents only, so two reductions have to be accounted
for first:

| Stage | Count |
|---|---|
| Ingested | 77 |
| Rejected in Stage 1 (exact duplicates, node4) | −8 |
| Failed during processing | −1 |
| **Reached the classifier** | **68** |
| Corrected before the machine's prediction was preserved | −13 |
| **Scoreable** | **55** |

The 9 that never reached the classifier are **not** classification errors — a duplicate
correctly rejected is the pipeline working.

The 13 excluded corrections are a data-loss artefact, not a judgement: a reviewer changed
the label before `original_label` existed, so `label` now holds the reviewer's answer and
the machine's prediction is gone. Scoring them would compare a human against a filename.
Corrections made from now on preserve both and *are* scoreable.

---

## Headline

| Metric | Value |
|---|---|
| **Strict accuracy** | **45 / 55 = 81,8 %** |
| **Safeguarded accuracy** | **55 / 55 = 100 %** |
| Wrong, escalated to human review | 10 |
| **Wrong, filed without review** | **0** |

**Strict accuracy** — the model's label matched the truth. This is what "accuracy" normally
means, and it is the number to quote when asked how good the classifier is.

**Safeguarded accuracy** — correct, *or* wrong but escalated to a human before anything was
filed. This is a claim about the **safety net**, not the classifier. Every one of the 10
wrong predictions was escalated; none reached storage unreviewed.

Report both, labelled. Quoting only 100 % invites the reading that the classifier is
perfect, which it is not. Quoting only 81,8 % hides that no mistake was ever filed.

> **These figures supersede the 58,3 % / 91,7 % on the MVP slide, and an earlier 83,6 % /
> 98,5 % measured from this same database.** The earlier pair was computed before
> `machine_review_route` existed: it read the *current* workflow route, which a reviewer's
> resolution rewrites to `accept`, so escalated misses were miscounted as filed. It also
> included the 13 unscoreable corrections. Both defects are fixed; see
> [How ground truth is obtained](#how-ground-truth-is-obtained).

---

## What recall, precision and F1 mean

Take one category — say `boletines`. Every document either is or isn't a boletín, and the
model either says it is or doesn't:

|  | Model says `boletines` | Model says something else |
|---|---|---|
| **Actually a boletín** | true positive (9) | false negative (2) |
| **Actually something else** | false positive (0) | true negative |

**Recall = found ÷ actually there.** Of all real boletines, what share did the model catch?
`boletines` recall is 9/11 = **0.82** — it missed 2. Low recall means documents of this type
are being filed under the wrong category. *"Are we finding them?"*

**Precision = right ÷ claimed.** Of everything the model *called* a boletín, what share
really was? `boletines` precision is 9/9 = **1.00** — when it says boletín, it is always
right. Low precision means this category is a dumping ground catching documents that belong
elsewhere. *"When it says this, can we believe it?"*

**F1 = the harmonic mean of the two.** A single number that is only high when *both* are
high — it punishes lopsidedness. A model that labels everything `decretos` gets perfect
recall on decretos and terrible precision; F1 exposes that, a raw accuracy figure doesn't.

**Support = how many documents genuinely belong to the category.** The recall denominator,
and the honesty check on the other three: recall 0.00 over 1 document means one miss, not a
measured weakness.

### Which one matters here

They fail differently, and for a municipal archive the costs are not symmetric:

- **Low recall** on a category means documents of that type are scattered into other
  folders. Someone searching for all `convenios` will not find them all.
- **Low precision** means a folder is contaminated — you open `decretos` and find things
  that aren't decrees.

Classiflow escalates on classifier disagreement, so an error of either kind becomes a
review-queue item rather than a misfiling. That is what the gap between 81,8 % and 100 % is
measuring.

---

## Per category

| Category | Support | Recall | Precision | F1 |
|---|---|---|---|---|
| `decretos_concejo_municipal` | 15 | 0.73 | 1.00 | 0.85 |
| `decretos` | 14 | 1.00 | **0.64** | 0.78 |
| `boletines` | 11 | 0.82 | 1.00 | 0.90 |
| `ordenanzas` | 7 | 0.86 | 1.00 | 0.92 |
| `resoluciones_concejo_municipal` | 3 | 0.67 | 1.00 | 0.80 |
| `convenios` | 1 | 1.00 | 1.00 | 1.00 |
| `declaraciones_concejo_municipal` | 1 | 1.00 | 0.50 | 0.67 |
| `decreto_ordenanzas` | 1 | 0.00 | 0.00 | 0.00 |
| `otro` | 1 | 1.00 | 1.00 | 1.00 |
| `resoluciones` | 1 | 0.00 | 0.00 | 0.00 |
| `compendios_de_boletines` | 0 | — | — | — |

Read the **Support** column first. Only the top four rows (7+ documents) carry enough weight
to draw conclusions from. The five categories at 1–3 documents are indicative only — a
single miss takes `decreto_ordenanzas` and `resoluciones` to 0.00, which says nothing about
those categories in general.

Excluding the 13 corrections thinned the rare categories most: `convenios` dropped from 3
labelled examples to 1, `resoluciones` from 5 to 1.

---

## What the numbers say

### `decretos` is a sink — the one real finding

Recall **1.00**, precision **0.64**. It never misses a decree, but a third of its
predictions were something else. Of 10 misses, **8 land on `decretos`**:

| Truth | Predicted `decretos` |
|---|---|
| `decretos_concejo_municipal` | 3 |
| `boletines` | 2 |
| `resoluciones` | 1 |
| `ordenanzas` | 1 |
| `decreto_ordenanzas` | 1 |

The failure mode is not random confusion — the model defaults to the largest category when
uncertain. This also explains the other categories' recall gaps:
`decretos_concejo_municipal` at 0.73 and `boletines` at 0.82 are low *because* their misses
went to `decretos`, not because those categories are intrinsically hard.

The primary-classification prompt already warns about the `decretos` /
`decretos_concejo_municipal` / `decreto_ordenanzas` trio. The data confirms the warning is
warranted and not yet sufficient.

The two remaining misses are single instances:
`decretos_concejo_municipal → declaraciones_concejo_municipal` and
`resoluciones_concejo_municipal → resoluciones` — both the council/non-council distinction.

### The safety net caught everything

All 10 wrong predictions were escalated to `human_review`. Zero wrong labels reached storage
unreviewed.

An earlier version of this document reported one uncaught `convenios` miss and called it a
structural hole, reasoning that BETO v2 was never trained on `convenios` so the second
opinion could not disagree. **That conclusion was wrong** — an artefact of reading the
mutable `review_route` after a reviewer had resolved the item. The document *was* escalated.

The underlying observation still holds and is worth watching: `convenios` and
`compendios_de_boletines` are LLM-only labels, so the second opinion cannot contradict the
primary classifier on them. That is a real gap in the disagreement signal — it simply has
not produced an uncaught miss in this corpus.

### Confidence does not separate right from wrong

| Route | Mean confidence |
|---|---|
| `accept` | 0.950 |
| `human_review` | 0.941 |

Escalated documents are, on average, as confident as accepted ones. The model reports high
confidence whether or not it is correct, so routing is driven almost entirely by **classifier
disagreement and OOD signals** — not by the confidence score.

This is the empirical justification for BETO v2 existing at all. A confidence-threshold gate
would have accepted nearly everything, including all 10 misses.

### `compendios_de_boletines` is untested

A real category — 27 documents in the source corpus, its own prompt anchor ("covers a RANGE
of boletín numbers, not one issue") — but none ingested locally. Worth closing, because a
compendio is exactly what a boletín gets confused with: `boletines` recall of 0.82 is
measured without its nearest confusable neighbour present, so it is probably optimistic.

---

## How ground truth is obtained

Two independent sources, both stored on `classification_records`:

**`expected_label` — the corpus filing convention.**
`classification/ground_truth.py` derives the category from the filename, since the archive
names every file after the category it was filed under (`ordenanza_9964_2019.pdf`). Longest
prefix wins, so `decreto_cm_` and `decreto_ordenanza_` are matched before the bare
`decreto_` they both start with. Documents that aren't municipal acts follow no naming
convention and are listed explicitly as `otro`. Applied automatically at classification
time, and backfilled for historical rows by migration `0015`.

**`original_label` — human corrections.**
When a reviewer overrides a classification, the machine's prediction is preserved rather
than overwritten. The reviewer's label is then the truth and `original_label` the miss. This
outranks the filename convention: a human adjudicated the document, the filename is a guess.

**`machine_review_route` — the safety net's original decision.**
`review_route` is mutated to `accept` when a reviewer resolves an item, which would erase
whether the miss had been caught. `machine_review_route` freezes the route chosen for the
machine's own prediction and is never updated by a human decision.

### Caveats

- **These are weak labels.** The filename reflects how the source archive filed a document,
  not an independent adjudication. Good enough for per-category rates at this scale; not a
  substitute for expert review on a contested document.
- **Corrections are a biased sample.** They only exist for documents the system already
  escalated — the hard ones. Metrics from corrections alone describe the review queue, not
  overall performance.
- **13 corrections predate `original_label`** and are excluded entirely. Migration `0015`
  reconstructed their `machine_review_route` (an override proves escalation, since the
  decision endpoint rejects anything not in `human_review`), but a lost prediction cannot be
  recovered.
- **Historical `machine_review_route` is derived, not recorded.** Rows classified after the
  migration carry the real value; the 68 existing rows carry an inference.

---

## Data-quality signals

Two fields exist to make gaps visible rather than let them read as coverage:

**`unevaluatedCategories`** — taxonomy members with zero labelled examples. Currently
`compendios_de_boletines`. An unevaluated category is not a category scoring 1.0.

**`unknownLabels`** — labels present in the database that are *not* `DocumentCategory`
members. Such records are still scored (dropping them would hide data), but they signal
stale or corrupt rows. Currently empty.

Both appear in the CLI output and on the Metrics page.

---

## Reproducing these numbers

```bash
uv run poe accuracy
```

Prints the same figures and writes a timestamped markdown report to `storage/reports/`.
Same `MetricsService` that backs the Metrics page, so the CLI, the API and this document
cannot disagree about what a number means.

**Verified 2026-09-04:** the CLI and the API were run against the same database and agree
on every figure — 77 ingested, 9 never classified, 68 classified, 55 scoreable, 45 correct,
10 escalated, 0 filed, 81,8 % / 100 %. Migration `0015` was verified separately against a
fresh revision-0013 fixture database (`tests/test_migration_0015.py`), not this one.
