from dataclasses import dataclass

from classiflow.knowledge.exceptions import KnowledgeError


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
