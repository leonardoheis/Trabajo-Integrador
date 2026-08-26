import re

# Matches a single non-nested JSON object -- shared by every *_extract() function that
# scrapes a JSON object out of raw LLM completion text (classification/prompts/,
# enrichment/prompts/, ingesta/prompts/content_validation.py).
JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)

# Small local models (llama.cpp completions used throughout this pipeline) routinely
# emit a trailing comma before a closing brace/bracket -- valid in many relaxed JSON
# dialects, invalid per the JSON spec that Python's json.loads enforces strictly. Strip
# it before parsing rather than accepting a whole third-party lenient-JSON dependency
# for one narrow failure mode.
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def strip_trailing_commas(text: str) -> str:
    return _TRAILING_COMMA_RE.sub(r"\1", text)
