from typing import Protocol, runtime_checkable

from classiflow.knowledge.domain.document import DocumentMetadata


@runtime_checkable
class IDocumentMetadataRepository(Protocol):
    def resolve(self, filename: str) -> DocumentMetadata: ...
