import contextlib
import json

from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import Field

from classiflow.classification.bert.ood_scorer import OodMetrics
from classiflow.classification.domain.results import JudgeOutput
from classiflow.domain.base import BaseEntity
from classiflow.llm_json import JSON_OBJECT_RE, strip_trailing_commas


class JudgeInput(BaseEntity):
    # Truncated to ClassificationConfig.judge_max_input_chars by LlmJudgeNode.run()
    # before this reaches the chain -- much more generous than
    # PrimaryClassificationInput's excerpt (the judge needs fuller context to
    # arbitrate disagreements), but not literally unbounded: a long document can
    # still overflow the shared SLM context window otherwise.
    cleaned_text: str
    primary_label: str
    primary_confidence: float
    second_opinion_label: str | None = None
    second_opinion_confidence: float | None = None
    ood_metrics: OodMetrics | None = None
    svm_agrees_with_prediction: bool = True
    smells: list[str] = Field(default_factory=list)
    risk_score: int = 0
    foreign_municipality: str | None = None


# Condensed from primary_classification.py's _CATEGORY_DEFS -- keep these two in
# sync (or share one source) if the anchors change.
#
# Corrected against real corpus samples (storage/documents samples, one-two per
# category) after the original anchors for the four Concejo-issued categories
# turned out to be wrong: none of ordenanzas/decretos_concejo_municipal/
# resoluciones_concejo_municipal/declaraciones_concejo_municipal actually contain
# a bare DECRETA/RESUELVE/DECLARA verb -- they all open with the shared formula
# "...HA SANCIONADO LA SIGUIENTE [ORDENANZA|DECRETO|RESOLUCION|DECLARACION]", and
# the noun after that formula is the real distinguishing signal. DECRETA/RESUELVE
# verbs only appear in the EXECUTIVE (Departamento Ejecutivo) decretos/resoluciones,
# confirmed via decreto_1000_2008.pdf ("EL INTENDENTE MUNICIPAL DECRETA") and
# resolucion_100_2020.pdf ("RESUELVE:").
_CATEGORY_ANCHORS = {
    "boletines": (
        'opens "Boletín Oficial Municipal N°..." '  # codespell:ignore oficial
        "-- a single dated issue"
    ),
    "compendios_de_boletines": (
        'covers a RANGE of boletín numbers ("Compendio de Boletines Nros. X al Y"), not one issue'
    ),
    "convenios": (
        'names two parties ("...celebrado entre la Municipalidad de Rosario y..."), '
        "numbered clauses, both sides sign"
    ),
    "declaraciones_concejo_municipal": (
        '"...HA SANCIONADO LA SIGUIENTE: DECLARACION" -- non-binding opinion/adhesion/repudio, '
        "issuing body is Concejo Municipal"
    ),
    "decreto_ordenanzas": (
        "rare -- Ejecutivo legislating during Concejo recess under an extraordinary "
        "faculty; explicit recess/faculty language or the literal term "
        '"Decreto-Ordenanza", not just ordinance-like content'
    ),
    "decretos": '"EL INTENDENTE MUNICIPAL DECRETA" -- ordinary executive act',
    "decretos_concejo_municipal": (
        '"...HA SANCIONADO EL SIGUIENTE: DECRETO" -- issuing body is Concejo Municipal, '
        "on internal/administrative Concejo matters (not DECRETA verb -- that's the "
        "executive decretos anchor)"
    ),
    "ordenanzas": (
        '"LA MUNICIPALIDAD DE ROSARIO HA SANCIONADO LA SIGUIENTE: ORDENANZA" -- '
        "general binding rule from the Concejo"
    ),
    "resoluciones": (
        'executive office (Secretaría/Dirección) + "...RESUELVE" on one specific matter'
    ),
    "resoluciones_concejo_municipal": (
        '"...HA SANCIONADO LA SIGUIENTE: RESOLUCION" -- issuing body is Concejo Municipal, '
        "on parliamentary/internal Concejo matters (not RESUELVE verb -- that's the "
        "executive resoluciones anchor)"
    ),
    "otro": (
        "the document is not from Municipalidad de Rosario at all -- a different "
        "issuing institution entirely (national agency, bank, another city's "
        "government). Not for genuinely-municipal documents that are merely "
        "ambiguous between two of the other categories."
    ),
}
_CATEGORY_ANCHORS_BLOCK = "\n".join(f"- {k}: {v}" for k, v in _CATEGORY_ANCHORS.items())

_TEMPLATE = """\
Task: you are the final quality gate for the Municipalidad de Rosario's automated \
document classification pipeline. A primary classifier assigned a label but was not \
confident enough to auto-accept, or a second opinion disagreed with it. Decide ACCEPT \
(the label is correct, safe to finalize) or HUMAN_REVIEW (send to a person), and state \
which label the evidence actually supports as final_label.

Category anchors -- what the text for each label should actually contain:
{category_anchors}

Primary classifier's label: {primary_label} (confidence: {primary_confidence})
Second opinion label (independent model, "none" if disabled): {second_opinion_label} \
(confidence: {second_opinion_confidence})
Automated risk signals (heuristic, not verified against the text -- treat as a \
caution flag, not a verdict): smells={smells}, risk_score={risk_score}
Foreign municipality detected: {foreign_municipality}

Second opinion's own statistical grounding (how much to trust ITS disagreement, \
distinct from whether it agrees with the primary label):
{ood_signal_block}
SVM reviewer agreement with second opinion's own predicted label (a same-model \
internal consistency check on the second opinion, NOT the primary-vs-second-opinion \
disagreement itself): {svm_agrees_with_prediction}

Decide HUMAN_REVIEW, not ACCEPT, when any of these hold:
- foreign_municipality is not "none" -- the document may not even be from \
Municipalidad de Rosario, which no amount of label-matching fixes.
- the document text does not clearly match the anchor for {primary_label} above.
- second_opinion_label disagrees with the primary label AND you cannot tell from \
the text which of the two is actually correct.
Otherwise, a high risk_score or a non-empty smells list is a reason for caution -- \
mention it in your reasoning -- but not by itself a reason to override a label the \
text clearly supports.

When the primary and second-opinion labels disagree, decide which one the document \
text actually supports using the category anchors above, and return that exact label \
string as final_label -- never a different category, even if you believe neither \
candidate is fully correct. Trust the second opinion's disagreement more when its \
statistical grounding above is in-distribution/calibrated/SVM-consistent, and less \
when it is out-of-distribution, uncalibrated, or SVM-inconsistent -- that grounding \
describes how reliable the second opinion's OWN prediction is, separate from whether \
it agrees with the primary label. If the text is genuinely ambiguous between the two, \
still pick the more likely candidate and reflect the uncertainty in reasoning, not by \
refusing to choose. If second_opinion_label is "none" or matches the primary label, \
final_label is simply {primary_label}.

Document text: {cleaned_text}

Answer with a single JSON object and nothing else.

JSON:
{{"accept": "true or false -- true means the primary label is correct and safe to accept", \
"final_label": "the label the evidence actually supports -- must be exactly {primary_label} \
or {second_opinion_label}, never a third category", \
"reasoning": "one short sentence citing the specific evidence -- textual or signal-based -- \
behind your decision"}}"""


def _extract(text: str) -> JudgeOutput:
    for m in JSON_OBJECT_RE.finditer(text):
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            return JudgeOutput.model_validate(json.loads(strip_trailing_commas(m.group())))
    msg = f"No valid JSON object found in LLM output: {text!r}"
    raise ValueError(msg)


def _ood_signal_block(ood_metrics: OodMetrics | None) -> str:
    if ood_metrics is None:
        return "not available (second opinion disabled or OOD scoring not configured)"
    mahalanobis_note = (
        "-- degenerate calibration, this specific model's calibration step could not "
        "produce a reliable p-value here; do not treat this value as trustworthy evidence"
        if ood_metrics.mahalanobis_calibration_status == "refused_degenerate"
        else f"-- {ood_metrics.mahalanobis_calibration_status}"
    )
    return (
        f"- mahalanobis_p_value: {ood_metrics.mahalanobis_p_value} "
        f"(low = anomalous/atypical for the predicted class, high = statistically "
        f"typical) {mahalanobis_note}\n"
        f"- cosine_z: {ood_metrics.cosine_z} (near 0 = typical, large magnitude = "
        f"anomalous) -- {ood_metrics.cosine_calibration_status}\n"
        f"- knn_distance: {ood_metrics.knn_distance} (distance to nearest training "
        f"examples of the predicted class in embedding space; larger = less similar "
        f"to anything this model was trained on) "
        f"-- {ood_metrics.knn_distance_calibration_status}\n"
        f"- in_distribution: {ood_metrics.in_distribution} (headline summary: whether "
        f"any calibrated signal above actually fired as anomalous)"
    )


def _format_prompt(chain_input: JudgeInput) -> str:
    return _TEMPLATE.format(
        category_anchors=_CATEGORY_ANCHORS_BLOCK,
        cleaned_text=chain_input.cleaned_text,
        primary_label=chain_input.primary_label,
        primary_confidence=chain_input.primary_confidence,
        second_opinion_label=chain_input.second_opinion_label or "none",
        second_opinion_confidence=(
            "n/a"
            if chain_input.second_opinion_confidence is None
            else chain_input.second_opinion_confidence
        ),
        smells=", ".join(chain_input.smells) or "none",
        risk_score=chain_input.risk_score,
        foreign_municipality=chain_input.foreign_municipality or "none",
        ood_signal_block=_ood_signal_block(chain_input.ood_metrics),
        svm_agrees_with_prediction=chain_input.svm_agrees_with_prediction,
    )


def build_judge_chain(llm: BaseLLM) -> Runnable[JudgeInput, JudgeOutput]:
    return RunnableLambda(_format_prompt) | llm | StrOutputParser() | RunnableLambda(_extract)
