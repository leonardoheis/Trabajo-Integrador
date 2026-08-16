from collections.abc import AsyncIterator

import numpy as np
import numpy.typing as npt
from dependency_injector import containers, providers

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.database.repositories.document import InMemoryDocumentRepository
from classiflow.database.repositories.document_steps import InMemoryDocumentStepsRepository
from classiflow.database.repositories.hash import InMemoryHashRepository
from classiflow.database.repositories.human_decision import InMemoryHumanDecisionRepository
from classiflow.database.repositories.job import InMemoryJobRepository
from classiflow.database.repositories.user import InMemoryUserRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.coordinator import build_coordinator
from classiflow.ingesta.nodes.node1_file_reception import FileReceptionNode
from classiflow.ingesta.nodes.node2_format_validation import FormatValidationNode
from classiflow.ingesta.nodes.node3_content_validation import ContentValidationNode
from classiflow.ingesta.nodes.node4_duplicate_control import DuplicateControlNode, EmbeddingStore
from classiflow.ingesta.nodes.node5_knowledge_indexing import KnowledgeIndexingNode
from classiflow.knowledge.chunker import ChunkerService
from classiflow.knowledge.domain.document import DocumentMetadata
from classiflow.knowledge.indexer import IndexerService
from classiflow.knowledge.infrastructure.chroma_store import InMemoryVectorStore
from classiflow.knowledge.rag import RagService
from classiflow.services.audit.service import AuditService
from classiflow.services.auth.service import AuthService
from classiflow.services.pipeline.service import PipelineService

# ponytail: fixed Spanish sample instead of real extraction — tests need deterministic,
# non-empty, allowed-language text to reach node3/node4, and shouldn't pay for real
# MarkItDown/OCR calls (or their model downloads) on every test run.
_TEST_TEXT = (
    "El Concejo Municipal de Rosario sanciona la siguiente ordenanza: "
    "Artículo 1º — Apruébase el presupuesto municipal para el ejercicio fiscal "
    "correspondiente al año en curso, conforme al detalle que se adjunta como Anexo I."
)


def _test_mime_detector(file_bytes: bytes) -> str:
    return "application/pdf" if file_bytes.startswith(b"%PDF") else "application/octet-stream"


def _test_embed(_text: str) -> npt.NDArray[np.float32]:
    return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


class _StubEmbedder:
    """Deterministic 3-d embedding: no model download, no inference in tests."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:  # noqa: PLR6301
        lowered = text.lower()
        return [
            1.0 if "ordenanza" in lowered else 0.0,
            1.0 if "presupuesto" in lowered else 0.0,
            float(len(lowered) % 3) / 3.0,
        ]


class _StubChatLlm:
    """Echoes a fixed Spanish answer, mirroring MockLlm's role for the SLM nodes."""

    def __init__(self, response: str = "Según los pasajes provistos, no hay datos.") -> None:
        self._response = response

    async def astream(self, _system: str, _user: str) -> AsyncIterator[str]:
        yield self._response


class _StubMetadataRepository:
    def resolve(self, filename: str) -> DocumentMetadata:  # noqa: PLR6301
        return DocumentMetadata(
            filename=filename,
            doc_type="Ordenanza",
            number="10902",
            year="2026",
            subject="Presupuesto municipal",
            download_url="https://www.rosario.gob.ar/normativa/ver/test",
        )


class TestContainer(containers.DeclarativeContainer):
    hash_repo = providers.Factory(InMemoryHashRepository)
    audit_repo = providers.Factory(InMemoryAuditRepository)
    # ponytail: Singleton so state (seeded users, created jobs/steps/decisions) survives
    # across the multiple requests one test makes against the shared `client` fixture.
    user_repo = providers.Singleton(InMemoryUserRepository)
    document_steps_repo = providers.Singleton(InMemoryDocumentStepsRepository)
    human_decision_repo = providers.Singleton(InMemoryHumanDecisionRepository)
    job_repo = providers.Singleton(InMemoryJobRepository)

    audit_service = providers.Factory(AuditService, repo=audit_repo)
    auth_service = providers.Factory(AuthService, user_repo=user_repo)
    broadcaster = providers.Singleton(EventBroadcaster)

    text_extractor = providers.Object(lambda _b, _f: _TEST_TEXT)
    node1 = providers.Factory(
        FileReceptionNode,
        audit=audit_service,
        broadcaster=broadcaster,
        mime_detector=_test_mime_detector,
    )
    node2 = providers.Factory(FormatValidationNode, audit=audit_service, broadcaster=broadcaster)
    node3 = providers.Factory(ContentValidationNode, audit=audit_service, broadcaster=broadcaster)
    node4 = providers.Factory(
        DuplicateControlNode,
        audit=audit_service,
        broadcaster=broadcaster,
        hash_repo=hash_repo,
        embedding_store=providers.Factory(EmbeddingStore, dim=4, embed_fn=_test_embed),
    )
    document_repo = providers.Singleton(InMemoryDocumentRepository)
    vector_store = providers.Singleton(InMemoryVectorStore)
    embedder = providers.Singleton(_StubEmbedder)
    chat_llm = providers.Singleton(_StubChatLlm)
    chunker = providers.Factory(ChunkerService)
    document_metadata_repo = providers.Singleton(_StubMetadataRepository)
    indexer = providers.Factory(
        IndexerService,
        chunker=chunker,
        embedder=embedder,
        vector_store=vector_store,
        metadata_repo=document_metadata_repo,
    )
    rag_service = providers.Factory(
        RagService,
        embedder=embedder,
        vector_store=vector_store,
        chat_llm=chat_llm,
    )
    node5 = providers.Factory(
        KnowledgeIndexingNode,
        audit=audit_service,
        broadcaster=broadcaster,
        indexer=indexer,
        document_repo=document_repo,
    )
    coordinator = providers.Factory(
        build_coordinator,
        node1=node1,
        node2=node2,
        node3=node3,
        node4=node4,
        node5=node5,
        text_extractor=text_extractor,
    )
    pipeline_service = providers.Factory(
        PipelineService,
        job_repo=job_repo,
        document_steps_repo=document_steps_repo,
        broadcaster=broadcaster,
        coordinator=coordinator,
    )
