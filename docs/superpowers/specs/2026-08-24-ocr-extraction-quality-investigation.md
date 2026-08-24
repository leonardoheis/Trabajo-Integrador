# OCR/Extraction Quality Investigation — Findings

## Status

Investigation complete. No code change made. This document records the findings for
future reference — the corpus's OCR/language-detection failures on old scanned
documents are accepted as a human-review case, not fixed at the extraction layer.

## Context

Decision 4 of the classification-accuracy-improvements spec
(`docs/superpowers/specs/2026-08-22-classification-accuracy-improvements-design.md`)
scoped this as a read-only investigation: confirm whether OCR quality (DPI,
`OCR_LANG`) is a meaningful contributor to misclassification on older scanned
documents, and produce a recommendation — not a guaranteed code change.

Three documents from `playground/samples/` were investigated, all old scanned
municipal records with no embedded text layer (so they go through the OCR fallback,
not MarkItDown):

- `declaracion_2501_1991.pdf`
- `decreto_ordenanza_1182_1976.pdf`
- `decreto_ordenanza_1314_1980.pdf`

`decreto_ordenanza_1314_1980.pdf` was previously observed (an earlier session) being
misdetected as Esperanto by the language detector (Lingua, in
`node3_content_validation.py`) and held for human review as a result.

## Method

Bypassed the full pipeline and called `OCRExtractor`'s underlying render+OCR steps
directly (`pymupdf.Page.get_pixmap(dpi=...)` → `easyocr.Reader(["es"],
gpu=True).readtext(...)`), matching production's actual code path
(`src/classiflow/ingesta/extractors/ocr.py`). Rendered the first page of each
document at DPI 200 (the current `Settings.OCR_RENDER_DPI` default), 300, and 400,
and compared the OCR text output character-for-character. Separately, ran the actual
DPI-200 OCR output for `decreto_ordenanza_1314_1980.pdf` through
`lingua.LanguageDetectorBuilder.from_all_languages().build()` (the exact detector
`node3_content_validation.py` uses) to see what it reports and at what confidence.

## Finding 1 — DPI does not meaningfully help

Character counts across the three tested DPIs were nearly identical for all three
documents (within ~1–2%), and OCR text quality was essentially unchanged — sometimes
marginally worse at higher DPI:

| Document | DPI 200 | DPI 300 | DPI 400 |
|---|---|---|---|
| `declaracion_2501_1991.pdf` | 1135 chars | 1140 chars | 1136 chars |
| `decreto_ordenanza_1182_1976.pdf` | 1656 chars | 1677 chars | 1676 chars |
| `decreto_ordenanza_1314_1980.pdf` | 2327 chars | 2467 chars | 2470 chars |

`decreto_ordenanza_1182_1976.pdf` and `decreto_ordenanza_1314_1980.pdf` are severely
garbled at every resolution tested (representative fragments: `"confcntle"`,
`"poblbllidua"`, `"Grvqulos"`). This is not a resampling problem — the source scans
themselves are low-quality (visibly old photocopies/mimeographs from the 1970s–80s),
and the information was never sharp enough in the original image to recover by
rendering at a higher DPI. `declaracion_2501_1991.pdf` is comparatively more legible
at all three DPIs (real Spanish words are readable throughout), reinforcing that
legibility here tracks the *source document's* condition, not the render resolution.

**Conclusion**: raising `Settings.OCR_RENDER_DPI` from its current default (200)
would slow down every OCR job (more pixels to process per page) for no measurable
accuracy gain on this corpus. Not recommended.

## Finding 2 — `OCR_LANG` is not the problem; it's a red herring

`OCR_LANG="es"` only constrains the `easyocr.Reader`'s recognition model at OCR time.
It has no relationship to the downstream language-detection step (Lingua in
`node3_content_validation.py`) that misclassified `decreto_ordenanza_1314_1980.pdf`'s
language.

Feeding the actual DPI-200 OCR output for this document into the real Lingua
detector returned a confident (score `1.0`, i.e. Lingua's maximum certainty) but
wrong result. In an earlier session's run it was reported as Esperanto; in this
investigation's separate run it came back as **Latin**. Neither is correct — the
document is genuinely Spanish. This confirms the misdetection is not a stable,
reproducible signal about the document's actual content; it is noise from feeding a
statistical language classifier text that has been sufficiently corrupted by OCR
that it no longer resembles real Spanish, not from any actual foreign-language
content. **No language is actually present in this corpus other than Spanish** —
confirmed directly with the user, who reviewed the sample documents — the
"Esperanto"/"Latin" outputs are false positives against real Spanish source
material, purely an artifact of OCR corruption feeding the statistical language
detector, not evidence of foreign-language content anywhere in the corpus.

Confirmed the causal direction directly: fed Lingua a cleanly-recognized OCR passage
from the same document (from the DPI 400 pass, a different, more legible section)
and it correctly detected Spanish. Fed it the badly garbled DPI-200 passage and it
confidently reported a wrong language. Same detector, same document, same language
setting — the only variable that changed the outcome was how corrupted the input
text was.

**Conclusion**: the language-detection failure is a downstream symptom of poor OCR
output, not an independent weakness in Lingua or a wrong `OCR_LANG` setting.
Changing `OCR_LANG` (e.g. to allow a broader language set) would not fix this —
Lingua's own language guess is already downstream of, and entirely dependent on, OCR
text quality that this specific hint has no influence over.

## Recommendation

No low-risk fix exists at the OCR/extraction-config layer for this corpus. The
actual bottleneck is source-image quality on decades-old scans — `pymupdf` render
DPI and `easyocr`'s language setting only affect how a *legible* scan gets read, not
how much real information survives in an already-degraded one.

A genuine fix would require real image-preprocessing work upstream of OCR
(deskewing, contrast enhancement, denoising, or a different/more robust OCR engine
entirely) — out of scope for a config change, and not attempted here per the
investigation's own scope (Decision 4 was explicit: report a finding, apply a fix
only if it's low-risk; this one is not).

**Accepted outcome, per explicit user decision**: documents this badly degraded are
expected to fail extraction/language-detection gracefully and route to human review
via `node3_content_validation.py`'s existing low-char-count / language-not-allowed
gates — exactly what already happens today. This is treated as correct, intended
behavior for this class of document, not a bug to chase further. No code change
made as a result of this investigation.

## Where this could be revisited

If OCR quality on old scans becomes a priority later, the concrete next steps would
be:
1. Try a preprocessing pass before OCR (deskew/contrast/denoise) on a document like
   `decreto_ordenanza_1182_1976.pdf` and re-run the same DPI comparison to see if
   *that* — not DPI alone — moves the needle.
2. Evaluate whether a different OCR engine (not `easyocr`) performs meaningfully
   better on this specific corpus's scan quality, ideally on a larger sample of
   badly-degraded documents than the three examined here.
3. Confirm with a larger sample whether `declaracion_2501_1991.pdf`'s relatively
   better legibility (vs. the other two) correlates with scan source/era, which
   would help scope how much of the corpus is actually affected.

None of this is scheduled — recorded here only so the investigation and its
reasoning aren't lost if the question comes up again.
