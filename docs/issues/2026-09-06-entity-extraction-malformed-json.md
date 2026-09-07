# Entity extraction fails deterministically on malformed SLM JSON

**Status:** open — documented, not fixed
**Observed:** 2026-09-06, `resolucion_190_2026.pdf`
**Node:** `enrichment_entity_extractor`
**Severity:** one document per occurrence lands in review; no data loss

## Symptom

A document completes ingesta (file reception, format validation, extraction, content
validation, duplicate control) and text cleaning, then fails entity extraction three
times in a row and is routed to review with:

```
Enrichment failed after retries: Entity extraction failed:
No valid JSON object found in LLM output
```

In the UI the document shows an Audit timeline ending at `enrichment_entity_extractor`
with no Classification section, and every content tab is empty — there is no enriched
record, no classification, and no indexed chunks, because none were ever produced.

## The offending output

The SLM emitted (verbatim, both occurrences byte-for-byte identical):

```json
{
  "doc_type_hint": "ordenanza",
  "number": null,
  "year": 2026,
  "issuing_body": "Secretar<mojibake>a de Hacienda y Econom<mojibake>a",
  "signatories": ["Lic. GUIDO F. BOGGIAN'"]],
  "article_count": 3
}
```

The defect is a single extra `]` on the `signatories` line. Every other field is
well-formed. The likely trigger is the apostrophe inside the signatory name
(`BOGGIAN'`) disrupting the model's bracket accounting — the source PDF signature block
reads `Lic. GUIDO F. BOGGIANO`.

The mojibake in `issuing_body` is the separately-known encoding problem already noted in
`src/classiflow/knowledge/retrieval/retriever.py:13-16`; it is not what causes this
failure.

## Why it fails

`_extract()` (`src/classiflow/enrichment/prompts/entity_extraction.py:48`):

```python
def _extract(text: str) -> EntityExtractionOutput:
    for m in JSON_OBJECT_RE.finditer(text):
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            cleaned = strip_trailing_commas(m.group())
            return EntityExtractionOutput.model_validate(json.loads(cleaned))
    msg = f"No valid JSON object found in LLM output: {text!r}"
    raise ValueError(msg)
```

`JSON_OBJECT_RE` is `\{[^{}]*\}` (`src/classiflow/llm_json.py:6`). It *does* match this
output — the character class excludes only braces, so the `signatories` array's brackets
pass through, as the comment at `entity_extraction.py:36-38` intends. The match is
therefore the whole object including the stray `]`, `json.loads` raises
`JSONDecodeError`, `contextlib.suppress` swallows it, `finditer` yields no further
candidate, and the loop falls through to the `ValueError`.

The existing repair step, `strip_trailing_commas()`, handles a different defect (a comma
before a closing brace or bracket) and does not apply here.

## Why retrying does not help

`PipelineService._run_enrichment` retries the whole enrichment coordinator up to
`max_enrichment_retries` times against the same node instance —
`EntityExtractorNode._resolve_chain()` deliberately keeps its chain across retries for
exactly this reason (`entity_extractor.py:68-79`).

But the SLM runs with a fixed `Settings.slm_seed`, and the retry re-sends an identical
prompt. Generation is therefore deterministic: **every retry reproduces the same
malformed output.** The observed log shows all three attempts failing within 3 seconds:

```
22:40:03  enrichment_entity_extractor  failed
22:40:04  enrichment_entity_extractor  failed
22:40:06  enrichment_entity_extractor  failed
```

Re-ingesting the document from scratch reproduces it identically as well — confirmed
across two separate jobs (`f4c8cada-…` and `ac54567b-…`), same byte-for-byte output.

The retry loop, as configured, cannot resolve any parse failure of this kind. It costs
three model invocations to arrive at the same answer.

## Scope

This affects any document whose extracted text leads the SLM to emit near-miss JSON.
`resolucion_190_2026.pdf` is one confirmed case; the failure mode is general, not
specific to this file. The same `_extract` / `JSON_OBJECT_RE` pattern is used by
`classification/prompts/`, `ingesta/prompts/content_validation.py`, and this module, so
a fix at the `llm_json` level would cover all three.

Content validation already anticipates this class of failure and routes to review rather
than crashing (`ingesta/nodes/node3_content_validation.py:173-184`). Enrichment behaves
the same way. The pipeline is working as designed — the document is parked for a human,
not lost.

## Candidate fixes

Not implemented; recorded for a later decision.

1. **Tolerant JSON repair before parsing.** Extend `llm_json.py` alongside
   `strip_trailing_commas` to also correct unbalanced trailing brackets. Fixes this and
   the surrounding class of near-miss output, and benefits all three call sites. Needs
   care: a repair that guesses wrong silently produces wrong metadata, which is worse
   than a visible failure.
2. **Vary the seed per retry attempt.** Retrying a deterministic model with identical
   input is currently a no-op; passing a different seed on attempts 2 and 3 would make
   the existing retry budget mean something. Small change, does not fix the parse defect
   itself but would likely clear this document.
3. **Constrained decoding (GBNF grammar).** llama.cpp can enforce a JSON schema at
   sampling time, making malformed output structurally impossible. Strongest fix,
   largest change, and would apply to every SLM call in the pipeline.
4. **Do nothing.** Affected documents land in review and a human supplies the entities.

Options 1 and 2 are complementary and independent.

## Reproduction

Ingest `resolucion_190_2026.pdf`. It fails at `enrichment_entity_extractor` after three
attempts and lands in `review` with `failed_at_node = enrichment` and
`review_action_needed = enrichment_failed`.
