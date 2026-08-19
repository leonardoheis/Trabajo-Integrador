import contextlib
import json
import re

from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnableLambda

from classiflow.classification.domain.results import PrimaryClassificationOutput
from classiflow.domain.base import BaseEntity

# Classiflow's 10 municipal document categories (README.md). BETO v2 (the Second
# Opinion Agent, classification/bert/) was only ever trained on 8 of these -- the
# primary LLM classifier is the only signal that can pick "convenios" or
# "compendios_de_boletines" at all. See the BERT spec's Decision 5 label-normalization
# map for the full BETO-to-Classiflow correspondence.
_CATEGORIES = (
    "boletines",
    "compendios_de_boletines",
    "convenios",
    "declaraciones_concejo_municipal",
    "decreto_ordenanzas",
    "decretos",
    "decretos_concejo_municipal",
    "ordenanzas",
    "resoluciones",
    "resoluciones_concejo_municipal",
)
_CATEGORIES_BLOCK = "\n".join(f"- {c}" for c in _CATEGORIES)


class PrimaryClassificationInput(BaseEntity):
    cleaned_text: str  # truncated to config.max_input_tokens by the node before this is built


_TEMPLATE = """\
Task: classify this excerpt of an official municipal document of the \
Municipalidad de Rosario into exactly one of the following categories:
{categories}

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
