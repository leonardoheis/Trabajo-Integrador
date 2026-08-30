from functools import lru_cache

from sentence_transformers import SentenceTransformer

from classiflow.knowledge.domain.chunk import Embedding
from classiflow.knowledge.embeddings.exceptions import EmbeddingError
from classiflow.settings import Settings


@lru_cache(maxsize=2)
def get_sentence_model(model_name: str) -> SentenceTransformer:
    try:
        # local_files_only: the model is downloaded once and cached ahead of time,
        # like every other model this project uses -- never fetched at request time.
        return SentenceTransformer(model_name, local_files_only=True)  # type: ignore[no-any-return]
    except Exception as exc:
        raise EmbeddingError(model=model_name, cause=str(exc)) from exc


class SentenceTransformerEmbedder:
    """Retrieval embedder.

    Separate from node 4's duplicate-control model on purpose: this one is
    multilingual (the corpus is Spanish), node 4's threshold is calibrated against
    all-MiniLM-L6-v2 and must not move.
    """

    def __init__(self, model_name: str = "") -> None:
        self._model_name = model_name or Settings.embedding_model

    @property
    def model_name(self) -> str:
        return self._model_name

    def _encode(self, texts: list[str]) -> list[Embedding]:
        model = get_sentence_model(self._model_name)
        try:
            vectors = model.encode(texts, normalize_embeddings=True)
        except Exception as exc:
            raise EmbeddingError(model=self._model_name, cause=str(exc)) from exc
        return [[float(x) for x in vector] for vector in vectors]

    def embed_documents(self, texts: list[str]) -> list[Embedding]:
        if not texts:
            return []
        return self._encode(texts)

    def embed_query(self, text: str) -> Embedding:
        return self._encode([text])[0]
