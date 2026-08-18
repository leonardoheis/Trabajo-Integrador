import unicodedata

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.enrichment.config_enrichment import EnrichmentConfig
from classiflow.enrichment.nodes.text_cleaner import TextCleanerNode
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_CONFIG = EnrichmentConfig(repeated_line_min_count=3)


def _node() -> TextCleanerNode:
    return TextCleanerNode(
        audit=AuditService(InMemoryAuditRepository()),
        broadcaster=EventBroadcaster(),
        config=_CONFIG,
    )


class TestTextCleanerClean:
    def test_strips_lines_repeated_3_or_more_times(self) -> None:
        text = (
            "Municipalidad de Rosario\nArtículo 1\nMunicipalidad de Rosario"
            "\nArtículo 2\nMunicipalidad de Rosario"
        )
        result = _node().clean(text)
        assert "Municipalidad de Rosario" not in result.cleaned_text
        assert "Artículo 1" in result.cleaned_text
        assert "Artículo 2" in result.cleaned_text

    def test_keeps_lines_repeated_fewer_than_threshold_times(self) -> None:
        text = "Header\nBody line\nHeader"
        result = _node().clean(text)
        assert "Header" in result.cleaned_text

    def test_strips_page_numbers(self) -> None:
        text = "Contenido real\nPágina 3\n5\n3/10"
        result = _node().clean(text)
        assert "Contenido real" in result.cleaned_text
        assert "Página 3" not in result.cleaned_text
        assert "3/10" not in result.cleaned_text

    def test_normalizes_unicode_to_nfc(self) -> None:
        nfd_text = unicodedata.normalize("NFD", "Municipalidad de Rosarió")
        assert not unicodedata.is_normalized("NFC", nfd_text)  # sanity: input really is NFD
        result = _node().clean(nfd_text)
        assert unicodedata.is_normalized("NFC", result.cleaned_text)
        assert result.cleaned_text == unicodedata.normalize("NFC", nfd_text)

    def test_empty_text_yields_empty_result(self) -> None:
        result = _node().clean("")
        assert not result.cleaned_text

    def test_strips_ocr_noise_but_keeps_ordinal_and_currency(self) -> None:
        text = "Artículo 1° — Presupuesto $500.000 #@%&*junk"
        result = _node().clean(text)
        assert "1°" in result.cleaned_text
        assert "$500.000" in result.cleaned_text
        assert "#@%&*" not in result.cleaned_text

    def test_line_that_is_entirely_noise_is_dropped_not_blank(self) -> None:
        text = "Contenido real\n#@%&*\nMás contenido"
        result = _node().clean(text)
        lines = result.cleaned_text.split("\n")
        assert "" not in lines


class TestTextCleanerRun:
    async def test_run_emits_started_and_passed(self) -> None:
        broadcaster = EventBroadcaster()
        node = TextCleanerNode(
            audit=AuditService(InMemoryAuditRepository()), broadcaster=broadcaster, config=_CONFIG
        )
        ctx = JobContext(job_id="job-1", filename="doc.pdf")
        result = await node.run(ctx, "Artículo 1º — texto de prueba.")
        assert "Artículo 1" in result.cleaned_text
