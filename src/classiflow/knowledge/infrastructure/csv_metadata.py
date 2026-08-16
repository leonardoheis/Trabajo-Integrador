import csv
import html
import re
from collections.abc import Iterable
from pathlib import Path

from loguru import logger

from classiflow.knowledge.domain.document import DocumentMetadata
from classiflow.settings import Settings

# Mirrors scrapper/downloader.py's CSV_CONFIG: each downloaded file is named
# "{prefix}_{NUMERO}_{ANIO}.pdf", so the stem maps back to a CSV row. Compendiums are
# excluded on purpose -- they are named "{COMPENDIO}_{PERIODO}.pdf" and carry no
# número/año, so they resolve to filename-only metadata.
_CSV_SOURCES: dict[str, tuple[str, str, str]] = {
    # prefix: (csv file, link column, fallback doc_type)
    "boletin": ("boletines.csv", "LINK", "Boletín"),
    "convenio": ("convenios.csv", "TEXTO_VIGENTE_NORMA", "Convenio"),
    "declaracion": (
        "declaraciones_concejo_municipal.csv",
        "TEXTO_VIGENTE_NORMA",
        "Declaración",
    ),
    "decreto_ordenanza": ("decreto_ordenanzas.csv", "TEXTO_VIGENTE_NORMA", "Decreto Ordenanza"),
    "decreto": ("decretos.csv", "TEXTO_VIGENTE_NORMA", "Decreto"),
    "decreto_cm": ("decretos_concejo_municipal.csv", "TEXTO_VIGENTE_NORMA", "Decreto CM"),
    "ordenanza": ("ordenanzas.csv", "TEXTO_VIGENTE_NORMA", "Ordenanza"),
    "resolucion": ("resoluciones.csv", "TEXTO_VIGENTE_NORMA", "Resolución"),
    "resolucion_cm": ("resoluciones_concejo_municipal.csv", "TEXTO_VIGENTE_NORMA", "Resolución CM"),
}

# The downloader appends "_doc_<id>" when one bulletin page yields several PDFs.
_DOC_SUFFIX = re.compile(r"_doc_\d+$")

_STEM_PARTS = 3


def _clean(value: str) -> str:
    # The CSVs carry HTML-escaped URLs ("&amp;idNormativa=..."), which are not valid
    # links until unescaped.
    return html.unescape(value.strip().strip('"'))


# "decreto_cm_810_2026.pdf" -> ("decreto_cm", "810", "2026"). Splitting from the
# right keeps multi-word prefixes ("decreto_cm", "decreto_ordenanza") intact.
def _parse_stem(filename: str) -> tuple[str, str, str] | None:
    stem = _DOC_SUFFIX.sub("", Path(filename).stem)
    parts = stem.rsplit("_", 2)
    if len(parts) != _STEM_PARTS:
        return None
    prefix, number, year = parts
    if not number.isdigit() or not year.isdigit():
        return None
    return prefix, number, year


def _read_rows(
    reader: Iterable[dict[str, str]],
    link_column: str,
    fallback_type: str,
    csv_name: str,
) -> dict[tuple[str, str], DocumentMetadata]:
    rows: dict[tuple[str, str], DocumentMetadata] = {}
    for row in reader:
        number = _clean(row.get("NUMERO", ""))
        year = _clean(row.get("ANIO", ""))
        if not number or not year:
            continue
        rows[number, year] = DocumentMetadata(
            filename="",
            doc_type=_clean(row.get("TIPO", "")) or fallback_type,
            number=number,
            year=year,
            subject=_clean(row.get("ASUNTO", "")),
            sanction_date=_clean(row.get("FEC_SANCION", "")),
            publication_date=_clean(
                row.get("FEC_PUBLICACION_BOLETIN", "") or row.get("PUBLICACION", "")
            ),
            bulletin_number=_clean(row.get("NRO_BOLETIN", "")),
            download_url=_clean(row.get(link_column, "")),
            source_csv=csv_name,
        )
    return rows


class CsvDocumentMetadataRepository:
    """Resolves a document's municipal metadata and download link from the CSVs.

    Rows are loaded lazily, one CSV per prefix, the first time a file of that kind is
    resolved -- loading all ten up front would cost ~13k rows for a single lookup.
    """

    def __init__(self, scrapper_dir: str = "") -> None:
        self._dir = Path(scrapper_dir or Settings.scrapper_dir)
        self._cache: dict[str, dict[tuple[str, str], DocumentMetadata]] = {}

    def resolve(self, filename: str) -> DocumentMetadata:
        parsed = _parse_stem(filename)
        if parsed is None:
            return DocumentMetadata(filename=filename)
        prefix, number, year = parsed
        if prefix not in _CSV_SOURCES:
            return DocumentMetadata(filename=filename)

        rows = self._rows_for(prefix)
        found = rows.get((number, year))
        if found is None:
            return DocumentMetadata(filename=filename)
        return found.model_copy(update={"filename": filename})

    def _rows_for(self, prefix: str) -> dict[tuple[str, str], DocumentMetadata]:
        cached = self._cache.get(prefix)
        if cached is not None:
            return cached

        csv_name, link_column, fallback_type = _CSV_SOURCES[prefix]
        rows: dict[tuple[str, str], DocumentMetadata] = {}
        path = self._dir / csv_name
        if not path.exists():
            # A missing CSV degrades to filename-only metadata rather than failing the
            # pipeline: indexing still succeeds, the source just has no link.
            logger.warning("Metadata CSV not found: {}", path)
            self._cache[prefix] = rows
            return rows

        try:
            with path.open(newline="", encoding="utf-8") as handle:
                rows.update(
                    _read_rows(csv.DictReader(handle), link_column, fallback_type, csv_name)
                )
        except OSError as exc:
            logger.warning("Could not read metadata CSV {}: {}", path, exc)

        self._cache[prefix] = rows
        return rows
