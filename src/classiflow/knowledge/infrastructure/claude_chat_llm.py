from collections.abc import AsyncIterator

import anthropic

from classiflow.knowledge.exceptions import ChatLlmError, ChatRefusalError
from classiflow.settings import Settings

_PROVIDER = "claude"


class ClaudeChatLlm:
    """Anthropic-backed chat completion.

    No `temperature` / `top_p` / `top_k`: those are rejected on current Claude models.
    Thinking is left at the model default rather than disabled -- disabling it on
    Opus-tier models can leak internal tags into the visible answer.
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        max_tokens: int = 0,
    ) -> None:
        self._api_key = api_key or Settings.anthropic_api_key
        self._model = model or Settings.anthropic_model
        self._max_tokens = max_tokens or Settings.chat_max_tokens
        self._client: anthropic.AsyncAnthropic | None = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is not None:
            return self._client
        try:
            # An empty key is not passed through: the SDK then resolves credentials
            # from the environment or a configured profile.
            self._client = (
                anthropic.AsyncAnthropic(api_key=self._api_key)
                if self._api_key
                else anthropic.AsyncAnthropic()
            )
        except Exception as exc:
            raise ChatLlmError(provider=_PROVIDER, cause=str(exc)) from exc
        return self._client

    async def astream(self, system: str, user: str) -> AsyncIterator[str]:
        client = self._get_client()
        try:
            async with client.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
        except anthropic.APIError as exc:
            raise ChatLlmError(provider=_PROVIDER, cause=str(exc)) from exc

        # A safety decline arrives as a successful response, not an exception, so it
        # has to be checked explicitly after the stream drains.
        if final.stop_reason == "refusal":
            details = getattr(final, "stop_details", None)
            category = getattr(details, "category", None) or "unspecified"
            raise ChatRefusalError(provider=_PROVIDER, category=str(category))
