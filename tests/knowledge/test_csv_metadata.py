from pathlib import Path

import pytest

from classiflow.knowledge.indexing.csv_metadata import CsvDocumentMetadataRepository

_NORM_HEADER = (
    '"TIPO","NUMERO","ANIO","ASUNTO","FEC_SANCION","NRO_BOLETIN","ANIO_BOLETIN",'
    '"FEC_PUBLICACION_BOLETIN","FUE_ACTUALIZADA","TEXTO_VIGENTE_NORMA"\n'
)
_NORM_ROW = (
    '"Decreto",810,2026,"Licitación Pública. Prórroga.","14/05/2026",2036,2026,'
    '"15/05/2026","NO","https://www.rosario.gob.ar/normativa/ver/visualExterna.do'
    '?accion=verNormativa&amp;idNormativa=261544"\n'
)


@pytest.fixture
def scrapper_dir(tmp_path: Path) -> Path:
    (tmp_path / "decretos.csv").write_text(_NORM_HEADER + _NORM_ROW, encoding="utf-8")
    (tmp_path / "ordenanzas.csv").write_text(
        '"TIPO","NUMERO","ANIO","ASUNTO","FEC_SANCION","FEC_PROMULGACION","NRO_BOLETIN",'
        '"ANIO_BOLETIN","FEC_PUBLICACION_BOLETIN","FUE_ACTUALIZADA","TEXTO_VIGENTE_NORMA"\n'
        '"Ordenanza",10902,2026,"Plazoleta. Designación.","09/04/2026","20/04/2026",2035,'
        '2026,"14/05/2026","NO","https://example.test/ordenanza"\n',
        encoding="utf-8",
    )
    (tmp_path / "decretos_concejo_municipal.csv").write_text(
        _NORM_HEADER + '"Decreto CM",55,2025,"Asunto CM.","01/02/2025",2000,2025,"02/02/2025","NO",'
        '"https://example.test/decreto-cm"\n',
        encoding="utf-8",
    )
    (tmp_path / "boletines.csv").write_text(
        '"NUMERO","ANIO","PUBLICACION","CANTIDAD_NORMAS","LINK"\n'
        '2036,2026,"15/05/2026",3,"https://www.rosario.gob.ar/normativa/ver/documento.do'
        '?accion=getPdf&amp;id=2267"\n',
        encoding="utf-8",
    )
    return tmp_path


class TestCsvDocumentMetadataRepository:
    def test_resolves_a_decreto_with_its_download_link(self, scrapper_dir: Path) -> None:
        repo = CsvDocumentMetadataRepository(str(scrapper_dir))

        metadata = repo.resolve("decreto_810_2026.pdf")

        assert metadata.doc_type == "Decreto"
        assert metadata.number == "810"
        assert metadata.year == "2026"
        assert metadata.subject == "Licitación Pública. Prórroga."
        assert metadata.sanction_date == "14/05/2026"
        assert metadata.bulletin_number == "2036"
        assert metadata.citation == "Decreto 810/2026"

    def test_html_entities_in_the_link_are_unescaped(self, scrapper_dir: Path) -> None:
        repo = CsvDocumentMetadataRepository(str(scrapper_dir))

        metadata = repo.resolve("decreto_810_2026.pdf")

        # "&amp;" in the CSV is not a usable URL until unescaped.
        assert "&amp;" not in metadata.download_url
        assert metadata.download_url.endswith("&idNormativa=261544")

    def test_multi_word_prefix_is_not_confused_with_the_plain_one(self, scrapper_dir: Path) -> None:
        repo = CsvDocumentMetadataRepository(str(scrapper_dir))

        cm = repo.resolve("decreto_cm_55_2025.pdf")

        assert cm.doc_type == "Decreto CM"
        assert cm.download_url == "https://example.test/decreto-cm"

    def test_bulletin_uses_the_link_column(self, scrapper_dir: Path) -> None:
        repo = CsvDocumentMetadataRepository(str(scrapper_dir))

        metadata = repo.resolve("boletin_2036_2026.pdf")

        assert metadata.doc_type == "Boletín"
        assert metadata.download_url.endswith("&id=2267")
        assert metadata.publication_date == "15/05/2026"

    def test_doc_suffix_from_multi_pdf_bulletins_is_stripped(self, scrapper_dir: Path) -> None:
        repo = CsvDocumentMetadataRepository(str(scrapper_dir))

        metadata = repo.resolve("boletin_2036_2026_doc_5.pdf")

        assert metadata.number == "2036"
        assert metadata.download_url

    def test_ordenanza_resolves_from_its_own_csv(self, scrapper_dir: Path) -> None:
        repo = CsvDocumentMetadataRepository(str(scrapper_dir))

        metadata = repo.resolve("ordenanza_10902_2026.pdf")

        assert metadata.doc_type == "Ordenanza"
        assert metadata.source_csv == "ordenanzas.csv"

    def test_unmatched_upload_degrades_to_filename_only(self, scrapper_dir: Path) -> None:
        repo = CsvDocumentMetadataRepository(str(scrapper_dir))

        metadata = repo.resolve("informe interno.pdf")

        assert metadata.filename == "informe interno.pdf"
        assert not metadata.doc_type
        assert not metadata.download_url
        assert metadata.citation == "informe interno.pdf"

    def test_known_prefix_with_unknown_number_degrades_gracefully(self, scrapper_dir: Path) -> None:
        repo = CsvDocumentMetadataRepository(str(scrapper_dir))

        metadata = repo.resolve("decreto_999999_1999.pdf")

        assert metadata.filename == "decreto_999999_1999.pdf"
        assert not metadata.download_url

    def test_missing_csv_does_not_raise(self, tmp_path: Path) -> None:
        repo = CsvDocumentMetadataRepository(str(tmp_path / "nope"))

        metadata = repo.resolve("decreto_810_2026.pdf")

        assert metadata.filename == "decreto_810_2026.pdf"
        assert not metadata.doc_type
