from classiflow.domain.base import BaseEntity
from classiflow.knowledge.domain.document import DocumentMetadata

# Chroma only accepts flat scalars in chunk metadata, which is also what its `where`
# filters can match on.
StoreMetadata = dict[str, str | int | float | bool]


class Chunk(BaseEntity):
    chunk_id: str
    job_id: str
    sha256: str
    chunk_index: int
    text: str
    metadata: DocumentMetadata

    # Deterministic id, so re-indexing the same document overwrites in place.
    @staticmethod
    def make_id(sha256: str, chunk_index: int) -> str:
        return f"{sha256}:{chunk_index}"

    def to_store_metadata(self) -> StoreMetadata:
        return {
            "job_id": self.job_id,
            "sha256": self.sha256,
            "chunk_index": self.chunk_index,
            "filename": self.metadata.filename,
            "doc_type": self.metadata.doc_type,
            "number": self.metadata.number,
            "year": self.metadata.year,
            "subject": self.metadata.subject,
            "download_url": self.metadata.download_url,
        }
