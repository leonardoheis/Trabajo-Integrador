# Classiflow — accuracy metrics

A snapshot of classification performance, and a guide to reading the numbers.

Measured from `data/classiflow.db` on 2026-09-02, over **67 labelled documents**.

> This file is a point-in-time picture. The live figures are on the **Metrics** page in
> the app (`/metrics`), or from `uv run poe accuracy`. Expect the numbers below to drift
> as more documents are ingested; the explanations will not.

---

## The pipeline funnel

Accuracy is measured over classified documents only, so the drop from ingested has to be
accounted for first:

| Stage | Count |
|---|---|
| Ingested | 76 |
| Rejected in Stage 1 (exact duplicates, node4) | −8 |
| Failed during processing | −1 |
| **Reached the classifier** | **67** |
| With a ground-truth label | 67 |

The 9 that never reached the classifier are **not** classification errors — a duplicate
correctly rejected is the pipeline working — so they are excluded from every rate below.
Counting them as misses would understate the classifier; ignoring the gap entirely would
leave a reader wondering where 9 documents went.

---

## Headline

| Metric | Value |
|---|---|
| **Strict accuracy** | **56 / 67 = 83,6 %** |
| **Safeguarded accuracy** | **66 / 67 = 98,5 %** |
| Wrong, escalated to human review | 10 |
| **Wrong, filed without review** | **1** |

**Strict accuracy** — the model's label matched the truth. This is what "accuracy" normally
means, and it is the number to quote when asked how good the classifier is.

**Safeguarded accuracy** — correct, *or* wrong but escalated to a human before anything was
filed. This is a claim about the **safety net**, not the classifier. Of 11 wrong
predictions, 10 were caught. Only one wrong label reached storage unreviewed.

Report both, labelled. Quoting only 98,5 % invites the reading that the classifier is that
accurate; it is not. Quoting only 83,6 % hides that the system rarely lets a mistake
through.

> The presentation's **58,3 % / 91,7 %** came from a 12-file sample. Over 67 documents the
> figures are **83,6 % / 98,5 %**. The old numbers understated the system: a 12-document
> sample moves 8,3 points per miss, and it scored `A0470.pdf` as wrong when the pipeline
> had actually handled it correctly.

---

## What recall, precision and F1 mean

Take one category — say `boletines`. Every document either is or isn't a boletín, and the
model either says it is or doesn't:

|  | Model says `boletines` | Model says something else |
|---|---|---|
| **Actually a boletín** | true positive (10) | false negative (2) |
| **Actually something else** | false positive (0) | true negative |

**Recall = found ÷ actually there.** Of all real boletines, what share did the model catch?
`boletines` recall is 10/12 = **0.83** — it missed 2. Low recall means documents of this
type are being filed under the wrong category. *"Are we finding them?"*

**Precision = right ÷ claimed.** Of everything the model *called* a boletín, what share
really was? `boletines` precision is 10/10 = **1.00** — when it says boletín, it is always
right. Low precision means this category is a dumping ground catching documents that
belong elsewhere. *"When it says this, can we believe it?"*

**F1 = the harmonic mean of the two.** A single number that is only high when *both* are
high — it punishes lopsidedness. A model that labels everything `decretos` gets perfect
recall on decretos and terrible precision; F1 exposes that, a raw accuracy figure doesn't.

**Support = how many documents genuinely belong to the category.** The recall denominator,
and the honesty check on the other three: recall 0.50 over 2 documents means one miss, not
a measured weakness.

### Which one matters here

They fail differently, and for a municipal archive the costs are not symmetric:

- **Low recall** on a category means documents of that type are scattered into other
  folders. Someone searching for all `convenios` will not find them all.
- **Low precision** means a folder is contaminated — you open `decretos` and find things
  that aren't decrees.

Classiflow escalates on classifier disagreement, so most errors of either kind become a
review-queue item rather than a misfiling. That is what the gap between 83,6 % and 98,5 %
is measuring.

---

## Per category

| Category | Support | Predicted | Correct | Recall | Precision | F1 |
|---|---|---|---|---|---|---|
| `decretos_concejo_municipal` | 17 | 13 | 13 | 0.76 | 1.00 | 0.87 |
| `decretos` | 14 | 22 | 14 | 1.00 | **0.64** | 0.78 |
| `boletines` | 12 | 10 | 10 | 0.83 | 1.00 | 0.91 |
| `ordenanzas` | 8 | 8 | 7 | 0.88 | 0.88 | 0.88 |
| `resoluciones` | 5 | 5 | 4 | 0.80 | 0.80 | 0.80 |
| `resoluciones_concejo_municipal` | 4 | 3 | 3 | 0.75 | 1.00 | 0.86 |
| `convenios` | 3 | 2 | 2 | 0.67 | 1.00 | 0.80 |
| `decreto_ordenanzas` | 2 | 1 | 1 | 0.50 | 1.00 | 0.67 |
| `declaraciones_concejo_municipal` | 1 | 2 | 1 | 1.00 | 0.50 | 0.67 |
| `otro` | 1 | 1 | 1 | 1.00 | 1.00 | 1.00 |
| `compendios_de_boletines` | 0 | 0 | — | — | — | — |

Read the **Support** column first. Only the top four rows (8+ documents) carry enough weight
to draw conclusions from; below that, one document swings recall by 25–50 points.

---

## What the numbers say

### `decretos` is a sink — this is the one real finding

Recall **1.00**, precision **0.64**. It never misses a decree, but 8 of its 22 predictions
were something else. Every miss in the corpus except three landed here:

| Truth | Predicted `decretos` |
|---|---|
| `decretos_concejo_municipal` | 3 |
| `boletines` | 2 |
| `resoluciones` | 1 |
| `ordenanzas` | 1 |
| `decreto_ordenanzas` | 1 |

**8 of 11 total misses are documents absorbed into `decretos`.** The model's failure mode is
not random confusion — it defaults to the largest category when uncertain. This is also the
mechanism behind the other categories' recall gaps: `decretos_concejo_municipal` at 0.76 and
`boletines` at 0.83 are low *because* their misses went to `decretos`, not because those
categories are intrinsically hard.

The primary-classification prompt already warns about the `decretos` /
`decretos_concejo_municipal` / `decreto_ordenanzas` trio. The data confirms the warning is
warranted and not yet sufficient.

### The one uncaught miss is structural

| Expected | Predicted | Route |
|---|---|---|
| `convenios` | `ordenanzas` | `accept` — filed unreviewed |

`convenios` is one of two categories **BETO v2 was never trained on**. The second-opinion
classifier cannot predict it, so it could not disagree, so the confidence gate never fired
and the document was auto-accepted with a wrong label.

This is a hole in the safety net, not bad luck: every `convenios` and
`compendios_de_boletines` document is unprotected by the second opinion. It is the single
most actionable finding here — 10 of 11 misses were caught, and the one that escaped did so
through a known, fixable gap.

### Confidence does not separate right from wrong

| Route | Mean confidence |
|---|---|
| `accept` | 0.950 |
| `human_review` | 0.941 |

Escalated documents are, on average, as confident as accepted ones. The model reports high
confidence whether or not it is correct, so routing is driven almost entirely by
**classifier disagreement and OOD signals** — not by the confidence score.

This is the empirical justification for BETO v2 existing at all. A confidence-threshold gate
would have accepted nearly everything, including the 10 misses that were caught.

### `compendios_de_boletines` is untested

A real category — 27 documents in the source corpus, its own prompt anchor ("covers a RANGE
of boletín numbers, not one issue") — but none ingested locally. Worth closing, because a
compendio is exactly what a boletín gets confused with: `boletines` recall of 0.83 is
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
time, so the labelled set grows with the corpus.

**`original_label` — human corrections.**
When a reviewer overrides a classification, the machine's prediction is preserved rather
than overwritten. Each correction is then a labelled example: the reviewer's label is the
truth, `original_label` is the miss.

### Caveats on both

- **These are weak labels.** The filename reflects how the archive filed a document, not an
  independent adjudication. Good enough for per-category rates at this scale; not a
  substitute for expert review on a contested document.
- **Corrections are a biased sample.** They only exist for documents the system already
  escalated — the hard ones. Metrics from corrections alone describe the review queue, not
  overall performance.
- **13 corrections predate the fix** and have no `original_label`. That data is
  unrecoverable; capture begins with the next correction.

---

## Reproducing these numbers

```bash
uv run poe accuracy
```

Prints the same figures and writes a timestamped markdown report to `storage/reports/`.
Same `MetricsService` that backs the Metrics page, so the CLI, the API and this document
cannot disagree about what a number means.
