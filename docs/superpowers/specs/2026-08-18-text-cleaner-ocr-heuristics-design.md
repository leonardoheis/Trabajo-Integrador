# Design: Text Cleaner — gibberish-line and fuzzy header/footer detection

> **Outcome (2026-08-18, after implementation and real-document testing):** Gibberish
> detection shipped as designed — validated against a real document with zero false
> positives found. Fuzzy header/footer dedup was **removed** after testing against the
> same document: single-linkage clustering deleted genuine content (confirmed real
> sentences, including actual poem lines, wrongly merged into "duplicate" clusters via
> weak transitive chains). Two fixes were tried (complete-linkage, average-linkage) —
> neither found a threshold that both catches the real header variants (which score as
> low as ~0.42 similarity to each other) and avoids merging unrelated short sentences
> (which coincidentally score just as high). Conclusion: character-level edit distance
> is not a strong enough signal for this problem at this string length; a real fix
> would need a different signal entirely (e.g. embeddings), not a threshold tweak.
> Decision 3 below is kept as a record of what was tried and why it didn't work, not
> as a description of shipped behavior.

## Context

Manually inspecting `TextCleanerNode`'s output on a real scanned municipal document
(`ordenanza_6801_1999.pdf`, run through the Stage 3 playground notebook) surfaced two
patterns the current cleaner doesn't catch, beyond the table-border-row and
wide-internal-gap fixes already shipped:

1. **Repeated institutional headers/footers that are never byte-identical.** OCR
   renders the same physical letterhead ("Municipalidad de Rosario / Secretaría de
   Cultura, Educación y Turismo") differently on every page it appears —
   `eAttmicijiat-clad de rJ!lioJa'tio` vs. `eAum'cijiaáclacl ele $to:Ja!Ü` vs. the
   occasional clean rendering. `repeated_line_min_count`'s exact-match dict can't
   group these; each variant is seen once.
2. **Whole lines of OCR failure**, e.g. `1 h  l . 1  1 1 1 1 1  1 ,  1 1 1 . 1 1 1 1 1 , h l  t f t  l t u  l 1 ...` —
   dense runs of isolated 1-2 character fragments with no recoverable content.
   `_NOISE_RE` targets stray symbol *characters* inside otherwise-real text; it has no
   mechanism for judging that an entire line is unsalvageable.

Both matter because `cleaned_text` is the literal Stage 5 RAG embedding input — noise
survives into retrieval, and false-positive stripping silently deletes real content.
That asymmetry (a miss costs a little noise; a false positive costs real information)
is the central design constraint below.

## Decisions

### 1. Both features ship config-gated and **default off**

Both are new heuristics validated against exactly one real document so far. Rather
than tune a threshold from a single sample and risk silently deleting real content
across the whole corpus, both get an explicit `_enabled` flag in `EnrichmentConfig`,
defaulting to `False`. `TextCleanerNode.clean()` runs its existing behavior unchanged
when disabled — enabling either is a config change, not a code change, once someone
has validated the threshold against a broader document sample.

### 2. Gibberish-line detection: token-length ratio, no new dependency

**Signal:** split the line on whitespace; if the fraction of tokens with length ≤ 2
characters exceeds a threshold, the line is unsalvageable garbage. This directly
targets the observed failure mode (dense runs of 1-2 char fragments) without
penalizing genuinely short real lines — `"Art. 2º.-"` has 2 tokens, both longer than
2 chars once trailing punctuation is part of the token; a real short line rarely has
*most* of its tokens at 1-2 chars.

**Rejected:** a dictionary/word-list lookup (real signal, but adds a data file and
Spanish-specific tooling for a check this token-ratio heuristic already covers
adequately) and a letter-density ratio over the whole line (weaker discriminator here
— the sample garbage block still contains plenty of alphabetic characters, just
arranged as short fragments; token length is the sharper signal for *this* failure
mode).

```python
class EnrichmentConfig(BaseModel):
    ...
    gibberish_detection_enabled: bool = False
    gibberish_short_token_ratio: float = 0.6  # fraction of ≤2-char tokens to flag a line
    gibberish_min_tokens: int = 4  # lines shorter than this are never flagged
    # (too little signal to judge reliably)
```

A line is dropped when `gibberish_detection_enabled` is true, it has at least
`gibberish_min_tokens` tokens, and the fraction of tokens with `len(token) <= 2`
is `>= gibberish_short_token_ratio`.

### 3. Fuzzy header/footer dedup: stdlib `difflib`, union-find clustering, digit-template guard

**Signal:** take every unique line at or under `fuzzy_dedup_max_line_len`, compare
each pair with `difflib.SequenceMatcher(None, a.casefold(), b.casefold()).ratio()`,
and union pairs scoring at or above `fuzzy_dedup_similarity_threshold` into the same
cluster (a plain union-find over the candidate lines — not a simple pairwise "does
line A match line B directly" check, since two OCR variants of the same header can
each be a strong match for a third variant without being a strong match for each
other; only the connected component captures that). Any cluster with
`fuzzy_dedup_min_count` or more members is dropped as header/footer noise.

**Why stdlib, not a fuzzy-matching library:** `difflib.SequenceMatcher` is stdlib,
needs no new dependency, and candidates are already restricted to short lines only
(see below) — a document's few hundred short unique lines compared pairwise is cheap
even at O(n²), no bucketing/indexing needed. Reach for `rapidfuzz` or a smarter
index only if profiling against real documents shows this is actually a bottleneck —
no evidence of that yet, and a length-bucket optimization was tried and dropped: real
OCR corruption changes line length enough (inserted/dropped characters) that two
variants of the same header can land in different length buckets and never get
compared, which is a correctness bug, not just a missed optimization.

**Only short lines are candidates.** Headers/footers are institutional boilerplate,
typically well under 80 characters; body paragraphs are not. Restricting fuzzy
comparison to lines under `fuzzy_dedup_max_line_len` both keeps the candidate set
small (cost) and avoids the semantically wrong case of two *unrelated* long
paragraphs being judged "similar enough" by edit-distance alone (correctness).

**Digit-template guard — required, not optional.** Verified empirically against the
sample document: enumerated content like `"Artículo 1"` / `"Artículo 2"` /
`"Artículo 3"` scores ~0.9 similarity to each other — *higher* than the real header
OCR variants (~0.42-0.55) — because character-level edit distance can't distinguish
"same template, different number" from "same template, OCR-corrupted." Left
unguarded, fuzzy dedup would delete real, distinct article text as confidently as it
catches real header noise. The fix: before comparing two candidate lines, replace
digit runs with a placeholder (`re.sub(r"\d+", "#", line)`) in both; if the results
are identical *and* the original lines weren't already identical, skip the pair —
that signature (same non-digit skeleton, different digits) is specifically the
enumerated-content pattern, not OCR corruption of a fixed institutional header. This
guard only ever prevents a merge, never causes one — it cannot introduce a new false
positive, only remove a specific, now-confirmed false-positive class.

```python
class EnrichmentConfig(BaseModel):
    ...
    fuzzy_dedup_enabled: bool = False
    fuzzy_dedup_max_line_len: int = 80  # only lines this short are candidates
    fuzzy_dedup_similarity_threshold: float = 0.5  # difflib ratio() to count as "same" line
    fuzzy_dedup_min_count: int = 3  # cluster size needed to strip, mirrors
    # repeated_line_min_count's role
```

**Open risk, stated explicitly:** 0.5 is already close to the noise floor — it's the
threshold verified to catch the one real example seen so far, with headroom of only
~0.05 before it would start missing that same example. The digit-template guard
closes the one false-positive class already found; it does not guarantee there
isn't another. This is exactly why decision #1 keeps it opt-in — the threshold and
guard need validating against more real documents before either is trusted as a
default.

### 4. Both checks run in the same single pass `clean()` already does

No new node, no new coordinator step, no new `TextCleaningResult` field — these are
additional line-filtering conditions inside the existing loop in
`TextCleanerNode.clean()`, evaluated alongside the existing repeated-line/page-number/
table-border checks. Gibberish detection is a per-line, self-contained check (fits
directly in the existing loop). Fuzzy dedup needs a first pass to build the
length-bucketed similarity groups (mirroring how the existing `counts` dict is
already built in a first pass over `lines`) before the second pass decides what to
keep.

## Testing

Both ship with the same `TextCleanerNode`/`EnrichmentConfig`-override pattern already
used in `tests/enrichment/test_text_cleaner.py`: construct the node with an
`EnrichmentConfig` that turns the feature on, assert behavior; a config with the
feature off (the default) must leave the existing behavior byte-identical, verified
with a test that passes gibberish/fuzzy-duplicate content straight through unchanged
when disabled.

## Open items / risks

| Risk | Mitigation |
|---|---|
| Fuzzy dedup threshold tuned from one sample document, sitting close to the noise floor (0.5) | Ships disabled by default (Decision 1); revisit once validated against more real documents |
| Character-level similarity conflates "same template, different number" with "same template, OCR-corrupted" (confirmed: `"Artículo 1/2/3"` scores *higher* than real header variants) | Digit-template guard (Decision 3) — verified to fix this specific case; only ever prevents a merge, can't introduce a new false positive |
| Gibberish token-ratio threshold could misjudge a genuinely short, real line | `gibberish_min_tokens` floor + disabled-by-default; tune before enabling broadly |
| `difflib` pairwise comparison is O(n²) over candidate short lines | Acceptable for now — candidates are already restricted to short lines, no evidence of a real perf problem on real documents; revisit only if profiling shows otherwise |
