from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class ChatLlm(ABC):
    """Streaming chat completion, one provider per implementation.

    Implementations must raise only `ChatLlmError` subclasses of `KnowledgeError` so
    callers never have to catch provider-specific exceptions.

    Deliberately free of any provider import: `chat/` depends on this module, and
    pulling llama_cpp in here would force it onto every caller regardless of whether a
    real or stub implementation is actually wired up.
    """

    @abstractmethod
    def astream(self, system: str, user: str) -> AsyncIterator[str]:
        """Stream the completion for one system/user prompt pair.

        Returns:
            An async iterator over response text fragments.
        """
