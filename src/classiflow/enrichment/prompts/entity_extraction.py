import contextlib
import json
import re

from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import Field

from classiflow.domain.base import BaseEntity


class EntityExtractionInput(BaseEntity):
    cleaned_text: str


_TEMPLATE = """\
Task: extract structured metadata from this excerpt of an official municipal \
act (ordenanza, decreto, resolución) of the Municipalidad de Rosario. Return \
only what is explicitly present in the text — use null for anything not \
found, do not guess or infer.

Text: {cleaned_text}

Answer with a single JSON object and nothing else.

JSON:
{{"doc_type_hint": "ordenanza, decreto, resolucion, or null", \
"number": "act number as it appears, or null", \
"year": "year as an integer, or null", \
"issuing_body": "issuing body name, or null", \
"signatories": ["list of signatory names, empty array if none found"], \
"article_count": "number of ARTÍCULO entries detected, or null"}}"""

# Matches a single non-nested JSON object -- same approach as
# ingesta/prompts/content_validation.py's _JSON_RE (the "signatories" array's own
# brackets don't confuse this, since [] aren't excluded from the character class).
# Uses * (zero or more) instead of + (one or more) to match empty objects like {}.
_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


class EntityExtractionOutput(BaseEntity):
    doc_type_hint: str | None = None
    number: str | None = None
    year: int | None = None
    issuing_body: str | None = None
    signatories: list[str] = Field(default_factory=list)
    article_count: int | None = None


def _extract(text: str) -> EntityExtractionOutput:
    for m in _JSON_RE.finditer(text):
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            return EntityExtractionOutput.model_validate(json.loads(m.group()))
    msg = f"No valid JSON object found in LLM output: {text!r}"
    raise ValueError(msg)


def _format_prompt(chain_input: EntityExtractionInput) -> str:
    return _TEMPLATE.format(cleaned_text=chain_input.cleaned_text)


def build_entity_extraction_chain(
    llm: BaseLLM,
) -> Runnable[EntityExtractionInput, EntityExtractionOutput]:
    return (
        RunnableLambda(_format_prompt)
        | llm
        | StrOutputParser()
        | RunnableLambda(_extract)
    )
