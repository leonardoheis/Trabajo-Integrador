from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class ChatLlm(ABC):
    """Streaming chat completion, one provider per implementation.

    Implementations must raise only `ChatLlmError` / `ChatRefusalError` subclasses of
    `KnowledgeError` so callers never have to catch provider-specific exceptions.

    Deliberately free of any provider import: `chat/` depends on this module, and
    pulling anthropic or llama_cpp in here would load both providers regardless of
    which one Settings.chat_llm_provider selects.
    """

    @abstractmethod
    def astream(self, system: str, user: str) -> AsyncIterator[str]:
        """Stream the completion for one system/user prompt pair.

        Returns:
            An async iterator over response text fragments.
        """
