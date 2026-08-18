# Text Cleaner OCR Heuristics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two config-gated, default-off heuristics to `TextCleanerNode.clean()` — gibberish-line detection and fuzzy header/footer dedup — so real OCR failure patterns observed in production samples can be filtered once validated, without risking silent data loss while unvalidated.

**Architecture:** Both are additional per-line filtering conditions inside `TextCleanerNode.clean()`'s existing single pass over lines. No new node, no new coordinator step, no new dependency (stdlib `difflib` for fuzzy matching). Each ships behind its own `EnrichmentConfig` boolean, defaulting to `False`.

**Tech Stack:** stdlib `re`, `difflib`. No new packages.

**Spec:** `docs/superpowers/specs/2026-08-18-text-cleaner-ocr-heuristics-design.md`

## Global Constraints

- Line length 100, double-quote strings (ruff-enforced).
- mypy strict: never use `Any`. Never use `from __future__ import annotations`. `TYPE_CHECKING` only if ruff's TC001 rule requires it for a genuinely annotation-only import — not introduced to dodge a circular import.
- `EnrichmentConfig` stays a plain pydantic `BaseModel` (config object, not a domain value object).
- **No `# noqa` suppressions** — restructure code (named constants, rewritten comparisons) instead of suppressing a lint finding.
- Both new features default to `False`/off. A test with the default config must prove existing behavior is unchanged when the feature is off.
- `uv run poe check` is the full verification gate — hand the exact command to the user and wait, do not run it yourself. Plain `pytest`/`ruff check`/`ruff format --check`/`mypy` runs during the TDD loop are fine to run directly.
- Git: never `git add`/`commit`/`push` without the user's explicit go-ahead in that message.

---

## Task 1: Gibberish-line detection

**Files:**
- Modify: `src/classiflow/enrichment/config_enrichment.py`
- Modify: `config/enrichment.yaml`
- Modify: `src/classiflow/enrichment/nodes/text_cleaner.py`
- Modify: `tests/enrichment/test_text_cleaner.py`
- Modify: `tests/enrichment/test_config_enrichment.py`

**Interfaces:**
- Produces: `EnrichmentConfig.gibberish_detection_enabled: bool = False`, `EnrichmentConfig.gibberish_short_token_ratio: float = 0.6`, `EnrichmentConfig.gibberish_min_tokens: int = 4`. `TextCleanerNode.clean()`'s existing per-line loop gains one more drop condition — no new public method.

- [ ] **Step 1: Write the failing tests**

Add to `tests/enrichment/test_text_cleaner.py` (config fixture per-test since this needs a feature-on variant distinct from the module's shared `_CONFIG`):

```python
    def test_gibberish_line_dropped_when_enabled(self) -> None:
        config = EnrichmentConfig(
            repeated_line_min_count=3, gibberish_detection_enabled=True
        )
        node = TextCleanerNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            config=config,
        )
        text = "Contenido real y legible\n1 h  l . 1  1 1 1 1 1  1 ,  1 1 1 . 1 1 1 1 1\nMás contenido"
        result = node.clean(text)
        assert "Contenido real y legible" in result.cleaned_text
        assert "Más contenido" in result.cleaned_text
        assert "1 h" not in result.cleaned_text

    def test_gibberish_detection_off_by_default(self) -> None:
        text = "1 h  l . 1  1 1 1 1 1  1 ,  1 1 1 . 1 1 1 1 1"
        result = _node().clean(text)
        assert "1 h" in result.cleaned_text

    def test_short_line_never_flagged_as_gibberish(self) -> None:
        config = EnrichmentConfig(
            repeated_line_min_count=3, gibberish_detection_enabled=True
        )
        node = TextCleanerNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            config=config,
        )
        result = node.clean("Art. 2º.-")
        assert "Art. 2º.-" in result.cleaned_text
```

Add `from classiflow.enrichment.config_enrichment import EnrichmentConfig` to the test file's imports if not already present (it already imports `EnrichmentConfig` per the module's `_CONFIG = EnrichmentConfig(repeated_line_min_count=3)` line — reuse that import).

Add to `tests/enrichment/test_config_enrichment.py`:

```python
    def test_gibberish_detection_defaults(self) -> None:
        config = EnrichmentConfig()
        assert config.gibberish_detection_enabled is False
        assert config.gibberish_short_token_ratio == _EXPECTED_GIBBERISH_RATIO
        assert config.gibberish_min_tokens == _EXPECTED_GIBBERISH_MIN_TOKENS
```

with `_EXPECTED_GIBBERISH_RATIO = 0.6` and `_EXPECTED_GIBBERISH_MIN_TOKENS = 4` added alongside the file's existing `_EXPECTED_*` constants.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/enrichment/test_text_cleaner.py tests/enrichment/test_config_enrichment.py -v`
Expected: FAIL — `EnrichmentConfig` has no field `gibberish_detection_enabled` (pydantic extra-field or attribute error, depending on model config).

- [ ] **Step 3: Add the config fields**

In `src/classiflow/enrichment/config_enrichment.py`, add to `EnrichmentConfig`:

```python
    gibberish_detection_enabled: bool = False
    gibberish_short_token_ratio: float = 0.6
    gibberish_min_tokens: int = 4
```

In `config/enrichment.yaml`, append:

```yaml
# Gibberish-line detection: drop lines that are almost entirely OCR failure (dense
# runs of 1-2 character fragments), rather than noise mixed into otherwise-real text.
# Off by default -- validated against one real document so far; enable once tuned
# against a broader sample. See docs/superpowers/specs/2026-08-18-text-cleaner-ocr-heuristics-design.md.
gibberish_detection_enabled: false

# Fraction of a line's whitespace-separated tokens that must be <= 2 characters for
# the line to be flagged as gibberish.
gibberish_short_token_ratio: 0.6

# Lines with fewer tokens than this are never flagged -- too little signal to judge.
gibberish_min_tokens: 4
```

- [ ] **Step 4: Implement the check in `text_cleaner.py`**

Add a helper function and wire it into `clean()`'s existing loop:

```python
def _is_gibberish(stripped: str, config: EnrichmentConfig) -> bool:
    if not config.gibberish_detection_enabled:
        return False
    tokens = stripped.split()
    if len(tokens) < config.gibberish_min_tokens:
        return False
    short_count = sum(1 for token in tokens if len(token) <= 2)
    return (short_count / len(tokens)) >= config.gibberish_short_token_ratio
```

In `clean()`, add the check alongside the existing `_PAGE_NUMBER_RE`/`_TABLE_BORDER_RE` conditions:

```python
            if _TABLE_BORDER_RE.match(stripped):
                continue
            if _is_gibberish(stripped, self.config):
                continue
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/enrichment/test_text_cleaner.py tests/enrichment/test_config_enrichment.py -v`
Expected: PASS

- [ ] **Step 6: Lint/format/mypy**

Run: `uv run ruff check --fix src/classiflow/enrichment/config_enrichment.py src/classiflow/enrichment/nodes/text_cleaner.py tests/enrichment/test_text_cleaner.py tests/enrichment/test_config_enrichment.py`, then `uv run ruff check` (no `--fix`) and `uv run ruff format --check` on the same files to confirm clean. Run `uv run mypy src`.

- [ ] **Step 7: Commit**

```bash
git add src/classiflow/enrichment/config_enrichment.py config/enrichment.yaml src/classiflow/enrichment/nodes/text_cleaner.py tests/enrichment/test_text_cleaner.py tests/enrichment/test_config_enrichment.py
git commit -m "feat: add gibberish-line detection to text cleaner (default off)"
```

---

## Task 2: Fuzzy header/footer dedup [REMOVED after implementation]

> Implemented as specified below, then tested against a real document. Confirmed it
> deleted genuine content (real sentences merged into false "duplicate" clusters via
> transitive chaining) with no safe threshold found — see the spec's Outcome note.
> Removed entirely: `fuzzy_dedup_*` config fields, `_UnionFind`, `_cluster_similar_lines`,
> `_looks_like_enumerated_variant`, `_fuzzy_duplicate_lines`, and their tests. Kept
> below as a record of what was built and why it didn't survive contact with real data.

**Files:**
- Modify: `src/classiflow/enrichment/config_enrichment.py`
- Modify: `config/enrichment.yaml`
- Modify: `src/classiflow/enrichment/nodes/text_cleaner.py`
- Modify: `tests/enrichment/test_text_cleaner.py`
- Modify: `tests/enrichment/test_config_enrichment.py`

**Interfaces:**
- Consumes: stdlib `difflib.SequenceMatcher`.
- Produces: `EnrichmentConfig.fuzzy_dedup_enabled: bool = False`, `fuzzy_dedup_max_line_len: int = 80`, `fuzzy_dedup_similarity_threshold: float = 0.5`, `fuzzy_dedup_min_count: int = 3`. `TextCleanerNode.clean()` gains a pre-pass building a fuzzy-duplicate line set, consulted in the existing per-line loop.

**Verified against real data before writing this task** (see spec Decision 3): naive
pairwise similarity conflates enumerated content (`"Artículo 1"` vs `"Artículo 2"`
scores ~0.9) with genuine OCR header corruption (real variants scored ~0.42-0.55) —
the digit-template guard below is required, not optional polish, and the clustering
must be a proper union-find over connected pairs, not independent per-line "hub"
comparisons (two header variants can each match a third without matching each
other directly).

- [ ] **Step 1: Write the failing tests**

Add to `tests/enrichment/test_text_cleaner.py`:

```python
    def test_fuzzy_duplicate_headers_dropped_when_enabled(self) -> None:
        config = EnrichmentConfig(
            repeated_line_min_count=3,
            fuzzy_dedup_enabled=True,
            fuzzy_dedup_similarity_threshold=0.5,
            fuzzy_dedup_min_count=3,
        )
        node = TextCleanerNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            config=config,
        )
        text = "\n".join([
            "Municipalidad de Rosario",
            "Artículo 1",
            "eAttmicijiat-clad de rJ!lioJa'tio",
            "Artículo 2",
            "eAum'cijiaáclacl ele $to:Ja!Ü",
            "Artículo 3",
        ])
        result = node.clean(text)
        assert "Municipalidad de Rosario" not in result.cleaned_text
        assert "eAttmicijiat-clad" not in result.cleaned_text
        assert "eAum'cijiaáclacl" not in result.cleaned_text
        # Sequential/enumerated content must survive -- verified against real OCR
        # data that naive similarity alone would wrongly cluster these together
        # (see spec Decision 3's digit-template guard).
        assert "Artículo 1" in result.cleaned_text
        assert "Artículo 2" in result.cleaned_text
        assert "Artículo 3" in result.cleaned_text

    def test_enumerated_lines_not_treated_as_fuzzy_duplicates(self) -> None:
        config = EnrichmentConfig(
            repeated_line_min_count=99,  # disable exact-match stripping for this test
            fuzzy_dedup_enabled=True,
            fuzzy_dedup_similarity_threshold=0.5,
            fuzzy_dedup_min_count=3,
        )
        node = TextCleanerNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            config=config,
        )
        text = "Artículo 1\nArtículo 2\nArtículo 3"
        result = node.clean(text)
        assert "Artículo 1" in result.cleaned_text
        assert "Artículo 2" in result.cleaned_text
        assert "Artículo 3" in result.cleaned_text

    def test_fuzzy_dedup_off_by_default(self) -> None:
        text = "\n".join([
            "Municipalidad de Rosario",
            "Artículo 1",
            "eAttmicijiat-clad de rJ!lioJa'tio",
        ])
        result = _node().clean(text)
        assert "Municipalidad de Rosario" in result.cleaned_text
        assert "eAttmicijiat-clad" in result.cleaned_text

    def test_fuzzy_dedup_ignores_long_lines(self) -> None:
        config = EnrichmentConfig(
            repeated_line_min_count=3,
            fuzzy_dedup_enabled=True,
            fuzzy_dedup_max_line_len=20,
            fuzzy_dedup_similarity_threshold=0.5,
            fuzzy_dedup_min_count=2,
        )
        node = TextCleanerNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            config=config,
        )
        long_a = "Este es un párrafo largo que supera el límite de longitud configurado."
        long_b = "Este es otro párrafo largo que supera el límite de longitud configurado."
        result = node.clean(f"{long_a}\n{long_b}")
        assert long_a in result.cleaned_text
        assert long_b in result.cleaned_text
```

Add `_EXPECTED_FUZZY_MAX_LEN = 80`, `_EXPECTED_FUZZY_SIMILARITY = 0.5`, `_EXPECTED_FUZZY_MIN_COUNT = 3` to `tests/enrichment/test_config_enrichment.py` alongside a new test:

```python
    def test_fuzzy_dedup_defaults(self) -> None:
        config = EnrichmentConfig()
        assert config.fuzzy_dedup_enabled is False
        assert config.fuzzy_dedup_max_line_len == _EXPECTED_FUZZY_MAX_LEN
        assert config.fuzzy_dedup_similarity_threshold == _EXPECTED_FUZZY_SIMILARITY
        assert config.fuzzy_dedup_min_count == _EXPECTED_FUZZY_MIN_COUNT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/enrichment/test_text_cleaner.py tests/enrichment/test_config_enrichment.py -v`
Expected: FAIL — missing config fields.

- [ ] **Step 3: Add the config fields**

In `src/classiflow/enrichment/config_enrichment.py`, add to `EnrichmentConfig`:

```python
    fuzzy_dedup_enabled: bool = False
    fuzzy_dedup_max_line_len: int = 80
    fuzzy_dedup_similarity_threshold: float = 0.5
    fuzzy_dedup_min_count: int = 3
```

In `config/enrichment.yaml`, append:

```yaml
# Fuzzy header/footer dedup: catches the same institutional letterhead OCR'd
# differently on every page (never byte-identical, so repeated_line_min_count's
# exact-match check misses it). Off by default -- the useful similarity threshold is
# uncomfortably close to false-positive territory on real OCR corruption; validate
# against more documents before enabling. See
# docs/superpowers/specs/2026-08-18-text-cleaner-ocr-heuristics-design.md.
fuzzy_dedup_enabled: false

# Only lines at or under this length are compared -- keeps candidates to
# header/footer-shaped lines, not full paragraphs.
fuzzy_dedup_max_line_len: 80

# difflib.SequenceMatcher.ratio() at or above this counts two lines as "the same"
# line for dedup purposes. Verified against one real document at the edge of what
# catches actual OCR corruption -- see the spec's Open Risks.
fuzzy_dedup_similarity_threshold: 0.5

# A line's fuzzy-duplicate cluster needs at least this many members to be stripped.
fuzzy_dedup_min_count: 3
```

- [ ] **Step 4: Implement the fuzzy-dedup pre-pass in `text_cleaner.py`**

Add `import difflib` to the top of the file (alongside the existing `import re`/`import unicodedata`). Add a digit-template guard, a union-find helper, and the function that builds the set of lines to drop:

```python
_DIGIT_RUN_RE = re.compile(r"\d+")


def _looks_like_enumerated_variant(line_a: str, line_b: str) -> bool:
    # "Artículo 1" vs "Artículo 2" ratio ~0.9 under raw edit distance -- higher than
    # real OCR-corrupted header variants (~0.42-0.55) score against each other.
    # Same non-digit skeleton + different digits means "sequential content", not
    # "the same header, OCR-mangled" -- skip the pair rather than merge it.
    template_a = _DIGIT_RUN_RE.sub("#", line_a)
    template_b = _DIGIT_RUN_RE.sub("#", line_b)
    return template_a == template_b and line_a != line_b


def _fuzzy_duplicate_lines(lines: list[str], config: EnrichmentConfig) -> set[str]:
    if not config.fuzzy_dedup_enabled:
        return set()

    candidates = [
        line.strip()
        for line in lines
        if line.strip() and len(line.strip()) <= config.fuzzy_dedup_max_line_len
    ]
    unique_lines = list(dict.fromkeys(candidates))

    parent = {line: line for line in unique_lines}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        root_x, root_y = find(x), find(y)
        if root_x != root_y:
            parent[root_x] = root_y

    for i, line_a in enumerate(unique_lines):
        for line_b in unique_lines[i + 1 :]:
            if _looks_like_enumerated_variant(line_a, line_b):
                continue
            ratio = difflib.SequenceMatcher(None, line_a.casefold(), line_b.casefold()).ratio()
            if ratio >= config.fuzzy_dedup_similarity_threshold:
                union(line_a, line_b)

    groups: dict[str, list[str]] = {}
    for line in unique_lines:
        groups.setdefault(find(line), []).append(line)

    to_drop: set[str] = set()
    for group in groups.values():
        if len(group) >= config.fuzzy_dedup_min_count:
            to_drop.update(group)
    return to_drop
```

In `clean()`, build the drop set once before the per-line loop, and check it alongside the existing conditions:

```python
    def clean(self, text: str) -> TextCleaningResult:
        text = unicodedata.normalize("NFC", text)

        lines = text.split("\n")
        counts: dict[str, int] = {}
        for line in lines:
            stripped = line.strip()
            if stripped:
                counts[stripped] = counts.get(stripped, 0) + 1

        fuzzy_duplicates = _fuzzy_duplicate_lines(lines, self.config)

        kept: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if counts[stripped] >= self.config.repeated_line_min_count:
                continue
            if stripped in fuzzy_duplicates:
                continue
            if _PAGE_NUMBER_RE.match(stripped):
                continue
            if _TABLE_BORDER_RE.match(stripped):
                continue
            if _is_gibberish(stripped, self.config):
                continue
            noise_stripped = _MULTI_SPACE_RE.sub(" ", _NOISE_RE.sub("", stripped))
            if noise_stripped:
                kept.append(noise_stripped)

        return TextCleaningResult(cleaned_text="\n".join(kept))
```

(This shows the full method after Task 1 + Task 2 are both applied — Task 1's `_is_gibberish` check stays where it already is; only the `fuzzy_duplicates` build-and-check is new here.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/enrichment/test_text_cleaner.py tests/enrichment/test_config_enrichment.py -v`
Expected: PASS

- [ ] **Step 6: Lint/format/mypy**

Run: `uv run ruff check --fix src/classiflow/enrichment/config_enrichment.py src/classiflow/enrichment/nodes/text_cleaner.py tests/enrichment/test_text_cleaner.py tests/enrichment/test_config_enrichment.py`, then `uv run ruff check` (no `--fix`) and `uv run ruff format --check` to confirm clean. Run `uv run mypy src`.

- [ ] **Step 7: Run the full test suite as a regression check**

Run: `pytest tests -q --override-ini=addopts= --log-level=CRITICAL`
Expected: PASS, full count (184 baseline + this task's new tests).

- [ ] **Step 8: Commit**

```bash
git add src/classiflow/enrichment/config_enrichment.py config/enrichment.yaml src/classiflow/enrichment/nodes/text_cleaner.py tests/enrichment/test_text_cleaner.py tests/enrichment/test_config_enrichment.py
git commit -m "feat: add fuzzy header/footer dedup to text cleaner (default off)"
```
