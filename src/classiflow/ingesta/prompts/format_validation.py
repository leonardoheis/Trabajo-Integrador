from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import Runnable, RunnableLambda

from classiflow.domain.base import BaseEntity
from classiflow.ingesta.domain import FormatDecision


class FormatChainInput(BaseEntity):
    filename: str
    detected_mime: str
    expected_extensions: str


_TEMPLATE = """\
This file's MIME type is already on the accepted list, but its extension \
doesn't match what that MIME type normally has, and it isn't a known safe \
mismatch. Rule-based checks already ruled out disabled and unrecognized \
formats — decide only this one leftover case.

Filename: {filename}
Detected MIME type: {detected_mime}
Extension(s) normally expected for this MIME type: {expected_extensions}

Decide:
- accept: the mismatch looks like an honest naming error — a generic, \
misspelled, or missing extension, or a filename pattern typical of manual \
uploads/exports in a municipal office. The underlying MIME type is already \
known safe.
- reject: the mismatch looks like an attempt to disguise a risky file as a \
safe one — e.g. the filename claims a document extension but the name itself \
looks executable-style, has a double extension, or is otherwise designed to \
mislead.
- manual_review: you cannot confidently tell which of the above applies.

When unsure, prefer manual_review over guessing — this gates document \
ingestion into the system.

{format_instructions}

Respond with valid JSON only."""


class FormatDecisionOutput(BaseEntity):
    decision: FormatDecision
    confidence: float | None = None
    reasoning: str = ""


def build_format_chain(llm: BaseLLM) -> Runnable[FormatChainInput, FormatDecisionOutput]:
    parser: PydanticOutputParser[FormatDecisionOutput] = PydanticOutputParser(
        pydantic_object=FormatDecisionOutput
    )
    format_instructions = parser.get_format_instructions()

    def _format_prompt(chain_input: FormatChainInput) -> str:
        return _TEMPLATE.format(
            filename=chain_input.filename,
            detected_mime=chain_input.detected_mime,
            expected_extensions=chain_input.expected_extensions,
            format_instructions=format_instructions,
        )

    return RunnableLambda(_format_prompt) | llm | parser
