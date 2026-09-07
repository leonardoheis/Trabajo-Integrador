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


# A quote that opens or closes a JSON string is always adjacent to structure -- a colon,
# comma, brace or bracket, modulo whitespace. One that is not came from the source
# document (OCR noise routinely carries stray quotes) and the model copied it into a
# value without escaping it, which json.loads rejects.
_INTERIOR_QUOTE_RE = re.compile(r'(?<![:,\[{\s])"(?![:,\]}\s])')


def escape_interior_quotes(text: str) -> str:
    """Escape quotes that sit inside a JSON string value rather than delimiting one.

    Returns:
        The text with interior quotes backslash-escaped, ready for a second parse attempt.
    """
    # A lambda, not a template string: re.sub reads backslashes in the replacement, so a
    # literal "\\\"" template emits two backslashes and breaks the value it repairs.
    return _INTERIOR_QUOTE_RE.sub(lambda _: '\\"', text)
