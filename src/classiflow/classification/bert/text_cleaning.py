"""Ported from bert_tunning's src/ingestion/_text.py -- pure regex/stdlib, no
adaptation needed beyond reading the trained-municipality name from
ClassificationConfig instead of bert_tunning's own Settings singleton."""

import re
from difflib import SequenceMatcher
from typing import NamedTuple

from classiflow.classification.config_classification import ClassificationConfig

_MUNICIPALIDAD_DE_RE = re.compile(
    # [\s|]+ instead of \s+ throughout -- MarkItDown renders some PDF letterheads as
    # single-cell markdown tables, splitting "Municipalidad de la Ciudad de X" with a
    # stray "|". Treating "|" as just another separator stops it from being captured
    # as part of the name.
    r"municipalidad[\s|]+de[\s|]+(?:la[\s|]+)?(?:ciudad[\s|]+de[\s|]+)?([^\s,.;:()|\n]+)",
    re.IGNORECASE,
)
_CONTEXT_CHARS = 40

# Below this SequenceMatcher ratio, two short municipality names are similar enough
# that a mismatch is more likely OCR noise (a scanned "Rosario" misread as "Rpsario")
# than a genuinely different name -- confirmed against decreto_cm_69438_2026.pdf,
# whose scanner-corrupted text read "Rpsario" and was wrongly flagged as foreign.
_OCR_NOISE_SIMILARITY_THRESHOLD = 0.8


class ForeignMunicipalityMatch(NamedTuple):
    name: str
    context: str


def _looks_like_ocr_noise_of(name: str, reference: str) -> bool:
    return SequenceMatcher(a=name.lower(), b=reference.lower()).ratio() >= (
        _OCR_NOISE_SIMILARITY_THRESHOLD
    )


def clean_text(text: str) -> str:
    text = text.replace("\f", " ").replace("\xa0", " ")
    text = re.sub(r"\|[-: ]+\|[-: |]+", "", text)
    text = re.sub(r"^\|.*\|$", "", text, flags=re.MULTILINE)
    text = re.sub(r"#+ ", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def detect_foreign_municipality(
    text: str, config: ClassificationConfig
) -> ForeignMunicipalityMatch | None:
    reference = config.ood_trained_municipality
    for match in _MUNICIPALIDAD_DE_RE.finditer(text):
        name = match.group(1)
        if not name.lower().startswith(reference.lower()) and not _looks_like_ocr_noise_of(
            name, reference
        ):
            start = max(0, match.start() - _CONTEXT_CHARS)
            end = min(len(text), match.end() + _CONTEXT_CHARS)
            context = " ".join(text[start:end].split())
            return ForeignMunicipalityMatch(name=name, context=context)
    return None
