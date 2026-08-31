from dataclasses import dataclass

from classiflow.database.models import ConversationTurn


@dataclass
class ConversationHistory:
    summary: str | None
    recent_turns: list[ConversationTurn]
