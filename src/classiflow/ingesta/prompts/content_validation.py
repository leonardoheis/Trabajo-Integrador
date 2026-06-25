from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel

_TEMPLATE = """\
You are a document legitimacy validator for a municipal document management system.
Given a text excerpt from a document, decide whether it appears to be a legitimate
municipal document (ordinance, resolution, decree, report, etc.).

Text excerpt (first 500 chars):
{text_excerpt}

Detected language: {detected_language}

Classify as legitimate if the text reads like an official document.
Classify as not legitimate if it appears to be spam, random characters, or unrelated content.

{format_instructions}

Respond with valid JSON only."""


class LegitimacyDecisionOutput(BaseModel):
    is_legitimate: bool
    confidence: float
    reasoning: str = ""


def build_content_chain(llm: BaseLLM) -> Runnable[dict[str, str], LegitimacyDecisionOutput]:
    parser: PydanticOutputParser[LegitimacyDecisionOutput] = PydanticOutputParser(
        pydantic_object=LegitimacyDecisionOutput
    )
    prompt = PromptTemplate(
        template=_TEMPLATE,
        input_variables=["text_excerpt", "detected_language"],
        partial_variables={"format_instructions": parser.get_format_instructions()},
    )
    return prompt | llm | parser
