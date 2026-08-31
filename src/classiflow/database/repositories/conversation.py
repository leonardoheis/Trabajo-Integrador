from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.database.models import ConversationSummary, ConversationTurn


class SqlConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_turn(self, user_email: str, question: str, answer: str) -> None:
        self._session.add(ConversationTurn(user_email=user_email, question=question, answer=answer))
        await self._session.flush()

    async def recent_turns(self, user_email: str, limit: int) -> list[ConversationTurn]:
        # created_at alone is not a reliable tie-breaker: SQLite's func.now() only has
        # second-level resolution, so rows inserted within the same second compare
        # equal and ORDER BY created_at can return them in an arbitrary order. id is
        # monotonically increasing (autoincrement), so it disambiguates ties.
        result = await self._session.execute(
            select(ConversationTurn)
            .where(ConversationTurn.user_email == user_email)
            .order_by(ConversationTurn.created_at.desc(), ConversationTurn.id.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def all_turns(self, user_email: str) -> list[ConversationTurn]:
        result = await self._session.execute(
            select(ConversationTurn)
            .where(ConversationTurn.user_email == user_email)
            .order_by(ConversationTurn.created_at.asc(), ConversationTurn.id.asc())
        )
        return list(result.scalars().all())

    async def turn_count(self, user_email: str) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(ConversationTurn)
            .where(ConversationTurn.user_email == user_email)
        )
        return result.scalar_one()

    async def get_summary(self, user_email: str) -> str | None:
        result = await self._session.execute(
            select(ConversationSummary).where(ConversationSummary.user_email == user_email)
        )
        row = result.scalar_one_or_none()
        return row.summary_text if row is not None else None

    async def save_summary(self, user_email: str, summary_text: str) -> None:
        existing = await self._session.execute(
            select(ConversationSummary).where(ConversationSummary.user_email == user_email)
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            row.summary_text = summary_text
        else:
            self._session.add(ConversationSummary(user_email=user_email, summary_text=summary_text))
        await self._session.flush()

    async def clear(self, user_email: str) -> None:
        await self._session.execute(
            delete(ConversationTurn).where(ConversationTurn.user_email == user_email)
        )
        await self._session.execute(
            delete(ConversationSummary).where(ConversationSummary.user_email == user_email)
        )
        await self._session.flush()


class InMemoryConversationRepository:
    def __init__(self) -> None:
        self._turns: dict[str, list[ConversationTurn]] = {}
        self._summaries: dict[str, str] = {}

    async def save_turn(self, user_email: str, question: str, answer: str) -> None:
        # server_default=func.now() only fires on a real SQL INSERT, which this
        # in-memory repository never performs -- same fix already applied to
        # DocumentKb.indexed_at in PipelineService._build_document_kb.
        self._turns.setdefault(user_email, []).append(
            ConversationTurn(
                user_email=user_email,
                question=question,
                answer=answer,
                created_at=datetime.now(timezone.utc),
            )
        )

    async def recent_turns(self, user_email: str, limit: int) -> list[ConversationTurn]:
        return self._turns.get(user_email, [])[-limit:]

    async def all_turns(self, user_email: str) -> list[ConversationTurn]:
        return list(self._turns.get(user_email, []))

    async def turn_count(self, user_email: str) -> int:
        return len(self._turns.get(user_email, []))

    async def get_summary(self, user_email: str) -> str | None:
        return self._summaries.get(user_email)

    async def save_summary(self, user_email: str, summary_text: str) -> None:
        self._summaries[user_email] = summary_text

    async def clear(self, user_email: str) -> None:
        self._turns.pop(user_email, None)
        self._summaries.pop(user_email, None)
