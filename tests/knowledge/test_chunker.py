from classiflow.knowledge.chunking.chunker import ChunkerService
from classiflow.knowledge.domain.document import DocumentMetadata

_META = DocumentMetadata(
    filename="decreto_810_2026.pdf",
    doc_type="Decreto",
    number="810",
    year="2026",
    subject="Licitación pública. Prórroga.",
)
_BARE_META = DocumentMetadata(filename="subido_a_mano.pdf")
_WINDOW = 100


class TestChunkerService:
    def test_short_document_is_a_single_chunk(self) -> None:
        chunker = ChunkerService(chunk_size=1000, chunk_overlap=100)

        chunks = chunker.split("Artículo 1º — Apruébase.", "job-1", "abc", _META)

        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert chunks[0].chunk_id == "abc:0"
        assert chunks[0].job_id == "job-1"

    def test_empty_document_yields_no_chunks(self) -> None:
        chunker = ChunkerService(chunk_size=100, chunk_overlap=10)

        assert chunker.split("   \n\n  ", "job-1", "abc", _META) == []

    def test_every_chunk_carries_the_context_header(self) -> None:
        chunker = ChunkerService(chunk_size=120, chunk_overlap=20)
        text = "\n\n".join(f"Párrafo número {i} con texto suficiente." for i in range(8))

        chunks = chunker.split(text, "job-1", "abc", _META)

        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.text.startswith("Decreto 810/2026 — Licitación pública. Prórroga.")

    def test_header_falls_back_to_filename_without_csv_metadata(self) -> None:
        chunker = ChunkerService(chunk_size=200, chunk_overlap=20)

        chunks = chunker.split("Texto del documento.", "job-1", "abc", _BARE_META)

        assert chunks[0].text.startswith("subido_a_mano.pdf")

    def test_chunk_ids_are_deterministic_and_sequential(self) -> None:
        chunker = ChunkerService(chunk_size=120, chunk_overlap=20)
        text = "\n\n".join(f"Párrafo número {i} con texto suficiente." for i in range(6))

        first = chunker.split(text, "job-1", "abc", _META)
        second = chunker.split(text, "job-2", "abc", _META)

        assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
        assert [c.chunk_index for c in first] == list(range(len(first)))

    def test_paragraph_longer_than_window_is_split_with_overlap(self) -> None:
        chunker = ChunkerService(chunk_size=_WINDOW, chunk_overlap=25)
        # One paragraph, no blank lines -- the shape OCR produces on scanned norms.
        text = "palabra " * 60

        chunks = chunker.split(text, "job-1", "abc", _META)

        assert len(chunks) > 1
        # Body length is bounded by the window; the header is added on top of it.
        bodies = [c.text.split("\n", 1)[1] for c in chunks]
        assert all(len(body) <= _WINDOW for body in bodies)

    def test_overlap_not_smaller_than_size_is_corrected(self) -> None:
        # A misconfiguration that would otherwise make the sliding window never advance.
        chunker = ChunkerService(chunk_size=100, chunk_overlap=200)

        chunks = chunker.split("palabra " * 60, "job-1", "abc", _META)

        assert len(chunks) > 1

    def test_store_metadata_is_flat_and_carries_the_download_link(self) -> None:
        chunker = ChunkerService(chunk_size=500, chunk_overlap=50)
        meta = _META.model_copy(update={"download_url": "https://example.test/doc.pdf"})

        chunk = chunker.split("Texto.", "job-1", "abc", meta)[0]
        stored = chunk.to_store_metadata()

        assert stored["download_url"] == "https://example.test/doc.pdf"
        assert stored["doc_type"] == "Decreto"
        assert stored["chunk_index"] == 0
        assert all(isinstance(v, (str, int, float, bool)) for v in stored.values())
