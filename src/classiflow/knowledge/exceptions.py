from dataclasses import dataclass


class KnowledgeError(Exception): ...


@dataclass
class VectorStoreError(KnowledgeError):
    operation: str
    cause: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Vector store '{self.operation}' failed: {self.cause}"


@dataclass
class EmbeddingError(KnowledgeError):
    model: str
    cause: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Embedding with '{self.model}' failed: {self.cause}"


@dataclass
class ChatLlmError(KnowledgeError):
    provider: str
    cause: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Chat provider '{self.provider}' failed: {self.cause}"


@dataclass
class ChatRefusalError(KnowledgeError):
    provider: str
    category: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Chat provider '{self.provider}' declined the request ({self.category})"


@dataclass
class MetadataSourceError(KnowledgeError):
    path: str
    cause: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Could not read document metadata from '{self.path}': {self.cause}"
