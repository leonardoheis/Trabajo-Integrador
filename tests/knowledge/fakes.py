from collections.abc import AsyncIterator

from classiflow.knowledge.domain.chunk import Embedding
from classiflow.knowledge.domain.document import DocumentMetadata
from classiflow.knowledge.llm.chat_llm import ChatLlm

TEXT = (
    "Artículo 1º — Apruébase el presupuesto municipal para el ejercicio fiscal."
    "\n\n"
    "Artículo 2º — La partida asignada asciende a un total en el Anexo I."
    "\n\n"
    "Artículo 3º — Comuníquese al Departamento Ejecutivo."
)


class FakeEmbedder:
    """Keyword-indicator vectors: deterministic and dependency-free.

    Duck-typed rather than a SentenceTransformerEmbedder subclass -- subclassing the
    real embedder would load the multilingual model just to hand back two floats.
    """

    def embed_documents(self, texts: list[str]) -> list[Embedding]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> Embedding:
        lowered = text.lower()
        return [
            1.0 if "presupuesto" in lowered else 0.0,
            1.0 if "comuníquese" in lowered else 0.0,
        ]


class FakeMetadataRepo:
    def resolve(self, filename: str) -> DocumentMetadata:
        return DocumentMetadata(
            filename=filename,
            doc_type="Ordenanza",
            number="10902",
            year="2026",
            subject="Presupuesto municipal",
            download_url="https://example.test/ordenanza",
        )


class FakeChatLlm(ChatLlm):
    def __init__(self, tokens: list[str] | None = None) -> None:
        self.tokens = tokens or ["Según ", "la Ordenanza 10902/2026, ", "sí."]
        self.last_system = ""
        self.last_user = ""

    async def astream(self, system: str, user: str) -> AsyncIterator[str]:
        self.last_system = system
        self.last_user = user
        for token in self.tokens:
            yield token
