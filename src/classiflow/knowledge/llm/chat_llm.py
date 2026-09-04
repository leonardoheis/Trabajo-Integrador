from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator


class ChatLlm(ABC):
    """Streaming chat completion, one provider per implementation.

    Implementations must raise only `ChatLlmError` subclasses of `KnowledgeError` so
    callers never have to catch provider-specific exceptions.

    Deliberately free of any provider import: `chat/` depends on this module, and
    pulling llama_cpp in here would force it onto every caller regardless of whether a
    real or stub implementation is actually wired up.
    """

    @abstractmethod
    def astream(self, system: str, user: str) -> AsyncGenerator[str, None]:
        """Stream the completion for one system/user prompt pair.

        Returns:
            An async generator over response text fragments. Generator, not iterator, so
            callers can aclose() it -- an abandoned stream must release provider
            resources rather than wait for garbage collection.
        """
