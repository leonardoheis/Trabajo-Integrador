from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from classiflow.ingesta.domain.results import FormatDecision

_TEMPLATE = """\
You are a document format validator for a municipal document management system.
Given a filename and detected MIME type, decide whether the document is acceptable.

Filename: {filename}
Detected MIME type: {detected_mime}

Accepted formats: PDF, DOCX, JPEG, PNG, TIFF.
Reject HTML, executable files, and formats that pose security risks.
Use MANUAL_REVIEW only when you genuinely cannot determine whether the format is safe.

{format_instructions}

Respond with valid JSON only."""


class FormatDecisionOutput(BaseModel):
    decision: FormatDecision
    confidence: float
    reasoning: str = ""


def build_format_chain(llm: BaseLLM) -> Runnable[dict[str, str], FormatDecisionOutput]:
    parser: PydanticOutputParser[FormatDecisionOutput] = PydanticOutputParser(
        pydantic_object=FormatDecisionOutput
    )
    prompt = PromptTemplate(
        template=_TEMPLATE,
        input_variables=["filename", "detected_mime"],
        partial_variables={"format_instructions": parser.get_format_instructions()},
    )
    return prompt | llm | parser
