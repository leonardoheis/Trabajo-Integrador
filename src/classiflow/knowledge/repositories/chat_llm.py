from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class IChatLlm(Protocol):
    """Streaming chat completion, one provider per implementation.

    Implementations must raise only `ChatLlmError` / `ChatRefusalError` subclasses of
    `KnowledgeError` so callers never have to catch provider-specific exceptions.
    """

    def astream(self, system: str, user: str) -> AsyncIterator[str]: ...
