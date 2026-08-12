import contextlib
import json
import re

from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

_TEMPLATE = """\
Classify the document excerpt below as legitimate or not.
Answer with a single JSON object and nothing else.

Text: {text_excerpt}
Language: {detected_language}

JSON:
{{"is_legitimate": true or false, "confidence": 0.0 to 1.0, "reasoning": "one sentence"}}"""

# Matches a single non-nested JSON object: the outermost { ... }
_JSON_RE = re.compile(r"\{[^{}]+\}", re.DOTALL)


class LegitimacyDecisionOutput(BaseModel):
    is_legitimate: bool
    confidence: float
    reasoning: str = ""


def _extract(text: str) -> LegitimacyDecisionOutput:
    for m in _JSON_RE.finditer(text):
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            return LegitimacyDecisionOutput.model_validate(json.loads(m.group()))
    msg = f"No valid JSON object found in LLM output: {text!r}"
    raise ValueError(msg)


def build_content_chain(llm: BaseLLM) -> Runnable[dict[str, str], LegitimacyDecisionOutput]:
    prompt = PromptTemplate(
        template=_TEMPLATE,
        input_variables=["text_excerpt", "detected_language"],
    )
    return prompt | llm | StrOutputParser() | RunnableLambda(_extract)
