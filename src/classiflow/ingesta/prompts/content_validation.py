import contextlib
import json
import re

from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

_TEMPLATE = """\
Task: decide if this excerpt is real text from an official municipal act \
(ordenanza, decreto, resolución, convenio) of the Municipalidad de Rosario, \
or spam/unrelated content a scraper picked up by mistake.
Ignore length, OCR noise, and language — already checked elsewhere.

Legitimate signals: VISTO, CONSIDERANDO, ARTÍCULO, DECRETA, RESUELVE, \
ORDENANZA, numbered clauses, references to municipal authorities, act \
numbers, or dates.
Not legitimate: ads, unrelated topics, web navigation/cookie text, \
placeholder or fabricated text.

If unsure, use a lower confidence — do not guess.
Answer with a single JSON object and nothing else.

Text: {text_excerpt}
Language: {detected_language}

JSON:
{{"is_legitimate": true or false,"confidence": 0.0 to 1.0,
"reasoning": "one sentence explaining why"}}"""

# Matches a single non-nested JSON object: the outermost { ... }
_JSON_RE = re.compile(r"\{[^{}]+\}", re.DOTALL)

# Field-by-field fallback for when the model's "reasoning" sentence quotes a term
# from the source text (e.g. `legal references ("Ordenanza", ...)`) without escaping
# the inner quotes -- syntactically invalid JSON, even though each field is still
# individually readable. Matches the field order the prompt asks for.
_IS_LEGITIMATE_RE = re.compile(r'"is_legitimate"\s*:\s*(true|false)', re.IGNORECASE)
_CONFIDENCE_RE = re.compile(r'"confidence"\s*:\s*([0-9]*\.?[0-9]+)')
_REASONING_RE = re.compile(r'"reasoning"\s*:\s*"(.*)"\s*,\s*"confidence"', re.DOTALL)


class LegitimacyDecisionOutput(BaseModel):
    # Defaults make a malformed/partial SLM response (a real occurrence with a small
    # quantized local model -- e.g. it omits "confidence") fail safe into the low-
    # confidence/not-legitimate review path in node3, instead of crashing the node.
    reasoning: str = ""
    confidence: float = 0.5
    is_legitimate: bool = False


def _extract(text: str) -> LegitimacyDecisionOutput:
    for m in _JSON_RE.finditer(text):
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            return LegitimacyDecisionOutput.model_validate(json.loads(m.group()))
    is_legitimate_match = _IS_LEGITIMATE_RE.search(text)
    confidence_match = _CONFIDENCE_RE.search(text)
    if is_legitimate_match is None or confidence_match is None:
        msg = f"No valid JSON object found in LLM output: {text!r}"
        raise ValueError(msg)
    reasoning_match = _REASONING_RE.search(text)
    return LegitimacyDecisionOutput(
        reasoning=reasoning_match.group(1) if reasoning_match else "",
        confidence=float(confidence_match.group(1)),
        is_legitimate=is_legitimate_match.group(1).lower() == "true",
    )


def build_content_chain(llm: BaseLLM) -> Runnable[dict[str, str], LegitimacyDecisionOutput]:
    prompt = PromptTemplate(
        template=_TEMPLATE,
        input_variables=["text_excerpt", "detected_language"],
    )
    return prompt | llm | StrOutputParser() | RunnableLambda(_extract)
