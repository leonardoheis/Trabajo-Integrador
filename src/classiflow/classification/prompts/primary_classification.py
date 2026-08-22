import contextlib
import json
import re

from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnableLambda

from classiflow.classification.domain.categories import DocumentCategory
from classiflow.classification.domain.results import PrimaryClassificationOutput
from classiflow.domain.base import BaseEntity

# Canonical label set lives in classification/domain/categories.py (DocumentCategory) --
# the single source of truth for "what are the 10 valid labels," shared with Task 8's
# BETO label-normalization map. BETO v2 (the Second Opinion Agent, classification/bert/)
# was only ever trained on 8 of these -- the primary LLM classifier is the only signal
# that can pick CONVENIOS or COMPENDIOS_DE_BOLETINES at all. See the BERT spec's
# Decision 5 label-normalization map for the full BETO-to-Classiflow correspondence.
#
# Definitions below are domain knowledge about Argentine municipal act types
# (Concejo Municipal as the legislative body vs. Departamento Ejecutivo/Intendencia
# as the executive), NOT sourced from this project's own docs -- nothing in this repo
# defines these 10 categories. Validate against real corpus excerpts before trusting
# them, especially the three tightest pairs: decretos vs. decreto_ordenanzas vs.
# decretos_concejo_municipal; resoluciones vs. resoluciones_concejo_municipal;
# boletines vs. compendios_de_boletines. Anchors (literal opening phrases) over
# abstract prose -- Phi-4-mini pattern-matches "EL INTENDENTE MUNICIPAL DECRETA" far
# more reliably than it reasons about "acts of executive character." These rich
# definitions stay local to this prompt -- only the canonical label set is shared.
_CATEGORY_DEFS: dict[DocumentCategory, str] = {
    # The Spanish gazette name below is the real title, not a typo of "Official" --
    # both codespell-flagged occurrences are that literal proper noun.
    DocumentCategory.BOLETINES: (
        "Boletín Oficial Municipal: periodic official publication that "  # codespell:ignore oficial
        "republishes acts already sanctioned elsewhere (decretos, resoluciones, "
        "ordenanzas) for a single period. Opens with "
        '"Boletín Oficial Municipal N°" + a date/issue number; '  # codespell:ignore oficial
        "reads as a compilation of multiple distinct acts under one issue."
    ),
    DocumentCategory.COMPENDIOS_DE_BOLETINES: (
        "Compendio de Boletines: a bundled index/volume covering a RANGE of boletín "
        "issues, not a single issue. Extremely rare -- only pick this if the document "
        "literally contains the word 'Compendio' together with two distinct issue "
        "numbers joined by 'al' or a dash (e.g. two different numbers like 2050 and "
        "2075, not one number appearing once). A single number or act citation "
        "anywhere in the text (a decreto number, a folio number, a registry stamp) "
        "is NOT a range and does not qualify -- do not infer a range from one number."
    ),
    DocumentCategory.CONVENIOS: (
        "Convenio: a bilateral/multilateral agreement between the Municipalidad and "
        "another party (another municipality, the province, nación, a university, "
        'union, company). Names both parties explicitly ("...celebrado entre la '
        'Municipalidad de Rosario y..."), numbered clauses (PRIMERA, SEGUNDA...), '
        "signatures from both sides."
    ),
    DocumentCategory.DECLARACIONES_CONCEJO_MUNICIPAL: (
        "Declaración del Concejo Municipal: the Concejo (legislative body) "
        "expressing an opinion, adhesion, recognition, or repudiation -- NOT "
        'binding, creates no legal obligation. Opens with "...HA SANCIONADO LA '
        'SIGUIENTE: DECLARACION" -- issuing body is Concejo Municipal.'
    ),
    DocumentCategory.DECRETO_ORDENANZAS: (
        "Decreto-Ordenanza: an EXCEPTIONAL act -- the Departamento Ejecutivo "
        "legislating with ordinance-level force while the Concejo is in recess, "
        "under an extraordinary faculty granted by the municipal charter, subject "
        "to later Concejo ratification. Anchor: explicit invocation of that "
        'extraordinary faculty / recess, plus the term "Decreto-Ordenanza" itself. '
        "Rare -- do not default here just because a decreto has ordinance-like "
        "content."
    ),
    DocumentCategory.DECRETOS: (
        "Decreto: an ordinary unilateral act of the Intendente/Departamento "
        "Ejecutivo, within normal (non-recess) executive powers, general or "
        'particular in scope. Opens with "EL INTENDENTE MUNICIPAL DECRETA". This is '
        "the default executive-act category -- use decreto_ordenanzas only when the "
        "recess/extraordinary-faculty anchor is present."
    ),
    DocumentCategory.DECRETOS_CONCEJO_MUNICIPAL: (
        "Decreto del Concejo Municipal: an act of the Concejo (legislative body), "
        "on internal/administrative matters of the Concejo itself (e.g. "
        "council-member leave, internal appointments) -- narrower in scope than an "
        'ordenanza. Anchor: opens with "...HA SANCIONADO EL SIGUIENTE: DECRETO", '
        "issuing body is 'Concejo Municipal' / 'Honorable Concejo Municipal' (not "
        "the DECRETA verb -- that belongs to the executive decretos category)."
    ),
    DocumentCategory.ORDENANZAS: (
        "Ordenanza: a general, binding rule sanctioned by the Concejo Municipal "
        "(the municipal equivalent of a law), applying to citizens broadly, subject "
        'to executive promulgation. Opens with "LA MUNICIPALIDAD DE ROSARIO HA '
        'SANCIONADO LA SIGUIENTE: ORDENANZA".'
    ),
    DocumentCategory.RESOLUCIONES: (
        "Resolución: a narrower administrative act, typically from a "
        "Secretaría/Dirección municipal or the Ejecutivo on a specific internal "
        "matter (e.g. a single appointment or expense approval) -- lower in "
        'hierarchy than a decreto. Opens with "...RESUELVE", issuing body is an '
        "executive office, not the Concejo."
    ),
    DocumentCategory.RESOLUCIONES_CONCEJO_MUNICIPAL: (
        "Resolución del Concejo Municipal: like decretos_concejo_municipal but "
        "typically parliamentary/procedural matters (commissions, internal Concejo "
        'business). Anchor: opens with "...HA SANCIONADO LA SIGUIENTE: RESOLUCION", '
        "issuing body is 'Concejo Municipal'. This is the hardest pair to separate "
        "from decretos_concejo_municipal -- both share the same 'HA SANCIONADO...' "
        "opening and Concejo issuer; the deciding signal is specifically which noun "
        "(DECRETO vs. RESOLUCION) follows 'HA SANCIONADO EL/LA SIGUIENTE'."
    ),
}
_CATEGORIES_BLOCK = "\n".join(f"- {label.value}: {desc}" for label, desc in _CATEGORY_DEFS.items())


class PrimaryClassificationInput(BaseEntity):
    cleaned_text: str  # truncated to config.max_input_tokens by the node before this is built


_TEMPLATE = """\
Task: classify this excerpt of an official municipal document of the \
Municipalidad de Rosario into exactly one of the following categories. Each \
category is given with the phrase(s) it typically opens with -- use those as \
your primary signal, since document content can otherwise look similar \
across categories.

{categories}

Rules:
- Pick exactly one label, exactly as written above (the part before the colon).
- The issuing body (Departamento Ejecutivo/Intendente vs. Concejo Municipal) \
and the operative verb (decreta/resuelve/sanciona/declara) are stronger \
signals than the general topic of the text.
- The issuing body OVERRIDES the operative word alone: before finalizing a \
plain "decretos" or "resoluciones" label, check whether the literal phrase \
"Concejo Municipal" actually appears verbatim, word-for-word, in the Text \
below. Only if that exact phrase is genuinely present should you pick the \
matching "_concejo_municipal" variant instead. Do NOT infer, assume, or \
recall a "Concejo Municipal" mention that is not literally printed in the \
Text -- most decretos/resoluciones in this corpus are ordinary executive \
acts (issued by the Intendente/Departamento Ejecutivo/a Secretaría) with \
no Concejo Municipal involvement at all, and those stay plain \
"decretos"/"resoluciones". Re-read the Text below before applying this \
rule; do not apply it from memory of the examples above.
- decreto_ordenanzas and compendios_de_boletines are rare categories -- only \
pick them when their specific anchor (recess/extraordinary-faculty language; \
a range of boletín numbers) is actually present, not just because the text \
resembles a decreto or a boletín.
- An anchor phrase only counts as a signal when it introduces THIS \
document's own operative content -- typically the very first substantive \
line, immediately followed by that category's own structural markers (a \
decreto's own number is followed by "VISTO"/"CONSIDERANDO"/"DECRETA"; a \
convenio's own text follows with "Entre la Municipalidad..." and numbered \
clauses PRIMERA, SEGUNDA...). A citation to a DIFFERENT act's number \
appearing before or alongside the document's real content is administrative \
boilerplate, not the document's own category -- for example, real convenios \
are filed under a standing registry decree and routinely open with a \
"REGISTRO DE CONVENIOS" / "Decreto N° ..." stamp before their actual text \
begins; that stamp names the registry's founding decree, not this \
document's own type, and must not be read as a decreto anchor.
- If genuinely torn between two categories, pick the more likely one but \
reflect the uncertainty with a lower confidence rather than a high one.

Example: an excerpt starting "Decreto No 1437/2013\\nConvenio N° ...\\nRegistro \
de Convenios ... CONVENIO DE PRESTAMO DE USO GRATUITO ... Entre la \
MUNICIPALIDAD DE ROSARIO ... y ... acuerdan celebrar el presente convenio \
... PRIMERA: ..." must be labeled "convenios" (not "decretos") -- the \
leading "Decreto No 1437/2013" is only the registry stamp that files this \
convenio, not this document's own act; the real content (bilateral \
agreement between two parties, numbered clauses) is what anchors convenios.

Example: an excerpt starting "LA MUNICIPALIDAD DE ROSARIO HA SANCIONADO EL \
SIGUIENTE\\nDECRETO\\n(N'10.554)\\nHONORABLE CONCEJO MUNICIPAL:\\nLa Comisión \
de Planeamiento y Urbanismo ha considerado el proyecto presentado por los \
Concejales..." must be labeled "decretos_concejo_municipal" (not \
"decretos") -- the literal phrase "HONORABLE CONCEJO MUNICIPAL" is right \
there in the text, a few lines after "DECRETO", so the override applies. \
The same override applies to resoluciones issued by "Concejo Municipal" \
instead of by a Secretaría/Departamento Ejecutivo -- those are \
"resoluciones_concejo_municipal", not "resoluciones".

Contrast example: an excerpt starting "RESOLUCION N° 100\\nRosario, ... 14 \
de agosto de 2020.\\nVISTO:\\nEl Decreto Nacional de Necesidad y Urgencia \
N° 520/20 ... CONSIDERANDO: ..." must be labeled "resoluciones" (the plain \
category, NOT resoluciones_concejo_municipal) -- the phrase "Concejo \
Municipal" does not appear anywhere in this text, so the override rule \
above does not apply here; this is an ordinary executive resolución.

Text: {cleaned_text}

Answer with a single JSON object and nothing else.

JSON:
{{"label": "one of the categories above, exactly as written", \
"confidence": "your confidence in this label, a float between 0 and 1", \
"reasoning": "one short sentence justifying the label"}}"""

# Matches a single non-nested JSON object -- same approach as
# enrichment/prompts/entity_extraction.py's _JSON_RE.
_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


class _RawPrimaryOutput(BaseEntity):
    label: str
    confidence: float = 0.0
    reasoning: str = ""


def _extract(text: str) -> PrimaryClassificationOutput:
    for m in _JSON_RE.finditer(text):
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            raw = _RawPrimaryOutput.model_validate(json.loads(m.group()))
            # ponytail: all_scores is a single-point {label: confidence} map, not a
            # real per-class softmax distribution -- llama.cpp's plain text-completion
            # API used by get_llm_langchain() doesn't expose per-token logprobs across
            # all 10 categories here, and asking the model to hallucinate a full 10-way
            # distribution in freeform JSON would be unverifiable noise, not signal.
            # Upgrade path: switch to a logprob-exposing completion call if a genuine
            # distribution is ever needed downstream.
            return PrimaryClassificationOutput(
                label=raw.label,
                confidence=raw.confidence,
                all_scores={raw.label: raw.confidence},
            )
    msg = f"No valid JSON object found in LLM output: {text!r}"
    raise ValueError(msg)


def _format_prompt(chain_input: PrimaryClassificationInput) -> str:
    return _TEMPLATE.format(categories=_CATEGORIES_BLOCK, cleaned_text=chain_input.cleaned_text)


def build_classification_chain(
    llm: BaseLLM,
) -> Runnable[PrimaryClassificationInput, PrimaryClassificationOutput]:
    return RunnableLambda(_format_prompt) | llm | StrOutputParser() | RunnableLambda(_extract)
