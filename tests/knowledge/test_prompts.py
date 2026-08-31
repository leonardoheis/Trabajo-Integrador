from classiflow.database.models import ConversationTurn
from classiflow.knowledge.domain.chat import RetrievedChunk
from classiflow.knowledge.memory.domain import ConversationHistory
from classiflow.knowledge.prompts.chat import build_user_prompt

_CHUNK = RetrievedChunk(
    chunk_id="c1",
    text="El decreto 810/2026 establece...",
    score=0.9,
    metadata={"doc_type": "Decreto", "number": "810", "year": "2026", "filename": "d.pdf"},
)


class TestBuildUserPromptWithoutHistory:
    def test_matches_existing_behavior_when_history_is_none(self) -> None:
        prompt = build_user_prompt("pregunta", [_CHUNK])
        assert "Contexto de la conversación" not in prompt
        assert "Pasajes:" in prompt
        assert "Pregunta: pregunta" in prompt

    def test_matches_existing_behavior_when_history_is_empty(self) -> None:
        empty_history = ConversationHistory(summary=None, recent_turns=[])
        with_none = build_user_prompt("pregunta", [_CHUNK])
        with_empty = build_user_prompt("pregunta", [_CHUNK], history=empty_history)
        assert with_none == with_empty


class TestBuildUserPromptWithHistory:
    def test_includes_the_summary(self) -> None:
        history = ConversationHistory(summary="resumen previo", recent_turns=[])
        prompt = build_user_prompt("pregunta", [_CHUNK], history=history)
        assert "resumen previo" in prompt

    def test_includes_recent_turns_in_order(self) -> None:
        turns = [
            ConversationTurn(user_email="u", question="q1", answer="a1"),
            ConversationTurn(user_email="u", question="q2", answer="a2"),
        ]
        history = ConversationHistory(summary=None, recent_turns=turns)
        prompt = build_user_prompt("pregunta", [_CHUNK], history=history)
        assert prompt.index("q1") < prompt.index("q2")
        assert "q1" in prompt
        assert "a1" in prompt

    def test_history_block_appears_before_passages(self) -> None:
        history = ConversationHistory(summary="s", recent_turns=[])
        prompt = build_user_prompt("pregunta", [_CHUNK], history=history)
        assert prompt.index("Contexto de la conversación") < prompt.index("Pasajes:")
