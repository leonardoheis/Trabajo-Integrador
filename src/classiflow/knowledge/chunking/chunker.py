from classiflow.knowledge.domain.chunk import Chunk
from classiflow.knowledge.domain.document import DocumentMetadata
from classiflow.knowledge.utils.text import split_paragraphs
from classiflow.settings import Settings


class ChunkerService:
    """Splits a document into overlapping, paragraph-aware windows.

    Each chunk is prefixed with a one-line header naming the document, so a passage
    retrieved on its own still carries its identity -- retrieval returns single chunks,
    and a bare fragment of legal prose is often unattributable without it.
    """

    def __init__(self, chunk_size: int = 0, chunk_overlap: int = 0) -> None:
        self._chunk_size = chunk_size or Settings.chunk_size
        self._chunk_overlap = chunk_overlap or Settings.chunk_overlap
        if self._chunk_overlap >= self._chunk_size:
            # Otherwise the window never advances and chunking does not terminate.
            self._chunk_overlap = self._chunk_size // 4

    def split(self, text: str, job_id: str, sha256: str, metadata: DocumentMetadata) -> list[Chunk]:
        windows = self._windows(text)
        header = self._header(metadata)
        return [
            Chunk(
                chunk_id=Chunk.make_id(sha256, index),
                job_id=job_id,
                sha256=sha256,
                chunk_index=index,
                text=f"{header}\n{window}" if header else window,
                metadata=metadata,
            )
            for index, window in enumerate(windows)
        ]

    @staticmethod
    def _header(metadata: DocumentMetadata) -> str:
        return metadata.citation

    def _windows(self, text: str) -> list[str]:
        paragraphs = split_paragraphs(text)
        if not paragraphs:
            return []

        windows: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if len(paragraph) > self._chunk_size:
                if current:
                    windows.append(current)
                    current = ""
                windows.extend(self._hard_split(paragraph))
                continue
            candidate = f"{current}\n\n{paragraph}" if current else paragraph
            if len(candidate) > self._chunk_size:
                windows.append(current)
                current = paragraph
            else:
                current = candidate
        if current:
            windows.append(current)
        return windows

    def _hard_split(self, paragraph: str) -> list[str]:
        # A single paragraph longer than the window (common in scanned norms with no
        # blank lines at all) is cut on a fixed stride with overlap.
        step = self._chunk_size - self._chunk_overlap
        return [
            paragraph[start : start + self._chunk_size]
            for start in range(0, len(paragraph), step)
            if paragraph[start : start + self._chunk_size].strip()
        ]
