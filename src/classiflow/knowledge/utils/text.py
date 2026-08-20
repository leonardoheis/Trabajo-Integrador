import re

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_WHITESPACE = re.compile(r"[ \t]+")


def normalize_whitespace(text: str) -> str:
    """Collapse runs of spaces and tabs into one space and trim the ends.

    Returns:
        The normalized text.
    """
    return _WHITESPACE.sub(" ", text).strip()


def split_paragraphs(text: str) -> list[str]:
    """Split on blank lines, normalize each paragraph, and drop the empty ones.

    Returns:
        Non-empty, whitespace-normalized paragraphs in document order.
    """
    paragraphs = [normalize_whitespace(p) for p in _PARAGRAPH_BREAK.split(text)]
    return [p for p in paragraphs if p]
