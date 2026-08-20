from dataclasses import dataclass

from classiflow.knowledge.exceptions import KnowledgeError


@dataclass
class MetadataSourceError(KnowledgeError):
    path: str
    cause: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Could not read document metadata from '{self.path}': {self.cause}"
