from dataclasses import dataclass

from classiflow.knowledge.exceptions import KnowledgeError


@dataclass
class EmbeddingError(KnowledgeError):
    model: str
    cause: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Embedding with '{self.model}' failed: {self.cause}"
