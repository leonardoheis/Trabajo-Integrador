import time
from collections.abc import Callable
from functools import lru_cache
from typing import Protocol

import faiss
import numpy as np
import numpy.typing as npt
from pydantic import ConfigDict, Field
from sentence_transformers import SentenceTransformer

from classiflow.ingesta.config_duplicate import DuplicateControlConfig, get_duplicate_control_config
from classiflow.ingesta.domain.results import DuplicateControlResult
from classiflow.ingesta.nodes.base import BaseNode
from classiflow.shared.audit.service import AuditService
from classiflow.shared.database.repositories.audit import AuditDetail
from classiflow.shared.database.repositories.hash import IHashRepository
from classiflow.shared.domain.job import JobStatus, NodeEvent
from classiflow.shared.events.broadcaster import EventBroadcaster

_EMBED_DIM = 384
_MODEL_NAME = "all-MiniLM-L6-v2"

EmbedFn = Callable[[str], npt.NDArray[np.float32]]


class _VectorIndex(Protocol):
    @property
    def ntotal(self) -> int: ...

    def search(
        self, x: npt.NDArray[np.float32], k: int
    ) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.int64]]: ...

    def add(self, x: npt.NDArray[np.float32]) -> None: ...


@lru_cache(maxsize=1)
def _get_sentence_model() -> SentenceTransformer:
    return SentenceTransformer(_MODEL_NAME)  # type: ignore[no-any-return]


def _default_embed(text: str) -> npt.NDArray[np.float32]:
    vec = _get_sentence_model().encode(text, normalize_embeddings=True)
    return np.array(vec, dtype=np.float32)


def _normalize(vec: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0 else vec


class EmbeddingStore:
    def __init__(
        self,
        dim: int = _EMBED_DIM,
        embed_fn: EmbedFn = _default_embed,
    ) -> None:
        self._index: _VectorIndex = faiss.IndexFlatIP(dim)
        self._embed_fn = embed_fn

    def find_similarity(self, text: str) -> float:
        if self._index.ntotal == 0:
            return 0.0
        vec = _normalize(self._embed_fn(text)).reshape(1, -1)
        D, _ = self._index.search(vec, 1)
        return float(D[0][0])

    def add(self, text: str) -> None:
        vec = _normalize(self._embed_fn(text)).reshape(1, -1)
        self._index.add(vec)


class DuplicateControlNode(BaseNode):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def name(self) -> str:
        return "node4_duplicate_control"

    hash_repo: IHashRepository
    audit: AuditService
    broadcaster: EventBroadcaster
    embedding_store: EmbeddingStore = Field(default_factory=EmbeddingStore)
    config: DuplicateControlConfig = Field(default_factory=get_duplicate_control_config)

    async def run(
        self,
        job_id: str,
        filename: str,
        sha256: str,
        text: str,
    ) -> DuplicateControlResult:
        start = time.monotonic()

        await self.broadcaster.emit(
            NodeEvent(job_id=job_id, node=self.name, status=JobStatus.STARTED)
        )

        result = await self._check(job_id, sha256, text)
        duration_ms = int((time.monotonic() - start) * 1000)

        status = JobStatus.PASSED if result.passed else JobStatus.FAILED
        await self.broadcaster.emit(NodeEvent(job_id=job_id, node=self.name, status=status))

        await self.audit.record(
            job_id,
            self.name,
            status.value,
            duration_ms=duration_ms,
            detail=AuditDetail.model_validate({
                "filename": filename,
                "sha256": sha256,
                "is_duplicate": result.is_duplicate,
                "duplicate_type": result.duplicate_type,
                "similarity_score": result.similarity_score,
                "passed": result.passed,
                "rejection_reason": result.rejection_reason,
            }),
        )

        return result

    async def _check(self, job_id: str, sha256: str, text: str) -> DuplicateControlResult:
        if await self.hash_repo.exists(sha256):
            return DuplicateControlResult(
                passed=False,
                is_duplicate=True,
                duplicate_type="exact",
                similarity_score=1.0,
                rejection_reason="Exact duplicate: SHA-256 already in store",
            )

        similarity = self.embedding_store.find_similarity(text)
        if similarity >= self.config.cosine_similarity_threshold:
            return DuplicateControlResult(
                passed=False,
                is_duplicate=True,
                duplicate_type="semantic",
                similarity_score=similarity,
                rejection_reason=f"Near-duplicate: cosine similarity {similarity:.3f}",
            )

        await self.hash_repo.save(sha256, job_id)
        self.embedding_store.add(text)
        return DuplicateControlResult(passed=True, is_duplicate=False)
