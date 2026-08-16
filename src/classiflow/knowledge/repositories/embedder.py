from typing import Protocol, runtime_checkable

Embedding = list[float]


@runtime_checkable
class IEmbedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[Embedding]: ...

    def embed_query(self, text: str) -> Embedding: ...
