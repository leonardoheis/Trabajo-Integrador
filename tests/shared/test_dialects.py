"""Per-engine tuning resolved from a database URL.

These need no engine, no driver and no server: a tuning is a plain object, which is the
point of having the seam.
"""

import pytest

from classiflow.database.base import get_engine
from classiflow.database.dialects import (
    TUNINGS,
    DefaultTuning,
    DialectTuning,
    SqliteTuning,
    registry,
    resolve_tuning,
)
from classiflow.database.dialects.protocol import TuningConnection
from classiflow.settings import Settings

pytestmark = pytest.mark.anyio

_SQLITE_URL = "sqlite+aiosqlite:///./data/classiflow.db"
_POSTGRES_URL = "postgresql+asyncpg://user:pass@localhost/db"
_STUB_CACHED_STATEMENTS = 7


class _RecordingCursor:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.closed = False

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def close(self) -> None:
        self.closed = True


class _RecordingConnection:
    """Satisfies DBAPIConnection structurally; only `cursor` is ever exercised."""

    def __init__(self) -> None:
        self.cursor_ = _RecordingCursor()

    def cursor(self) -> _RecordingCursor:
        return self.cursor_

    def commit(self) -> None:
        return

    def rollback(self) -> None:
        return

    def close(self) -> None:
        return


class TestResolveTuning:
    def test_a_sqlite_url_resolves_to_the_sqlite_tuning(self) -> None:
        assert isinstance(resolve_tuning(_SQLITE_URL), SqliteTuning)

    def test_an_unregistered_url_falls_back_to_the_default(self) -> None:
        assert isinstance(resolve_tuning(_POSTGRES_URL), DefaultTuning)

    def test_the_default_is_last_so_nothing_after_it_is_unreachable(self) -> None:
        assert isinstance(TUNINGS[-1], DefaultTuning)
        assert not any(isinstance(tuning, DefaultTuning) for tuning in TUNINGS[:-1])


class TestSqliteTuning:
    def test_claims_only_sqlite_urls(self) -> None:
        tuning = SqliteTuning()
        assert tuning.matches(_SQLITE_URL)
        assert not tuning.matches(_POSTGRES_URL)

    def test_connect_args_carry_the_busy_timeout(self) -> None:
        assert SqliteTuning().connect_args() == {"timeout": Settings.SQLITE_BUSY_TIMEOUT_SECONDS}

    def test_sets_the_busy_timeout_before_switching_journal_mode(self) -> None:
        """Order matters: the journal-mode switch itself needs a lock to wait for."""
        connection = _RecordingConnection()
        SqliteTuning().on_connect(connection)
        first, second = connection.cursor_.statements
        assert first.startswith("PRAGMA busy_timeout=")
        assert second == "PRAGMA journal_mode=WAL"

    def test_closes_the_cursor(self) -> None:
        connection = _RecordingConnection()
        SqliteTuning().on_connect(connection)
        assert connection.cursor_.closed


class TestDefaultTuning:
    def test_matches_every_url(self) -> None:
        assert DefaultTuning().matches(_POSTGRES_URL)

    def test_adds_no_connect_args(self) -> None:
        assert DefaultTuning().connect_args() == {}

    def test_on_connect_touches_nothing(self) -> None:
        connection = _RecordingConnection()
        DefaultTuning().on_connect(connection)
        assert connection.cursor_.statements == []


class TestProtocolConformance:
    def test_every_registered_tuning_satisfies_the_protocol(self) -> None:
        assert all(isinstance(tuning, DialectTuning) for tuning in TUNINGS)


class _StubTuning:
    """A dialect that is not SQLite, added without touching get_engine."""

    def __init__(self) -> None:
        self.connected = 0

    def matches(self, url: str) -> bool:
        return url.startswith("sqlite")

    def connect_args(self) -> dict[str, object]:
        return {"cached_statements": _STUB_CACHED_STATEMENTS}

    def on_connect(self, _connection: TuningConnection) -> None:
        self.connected += 1


class TestAddingADialectNeedsNoChangeToGetEngine:
    async def test_the_registry_alone_decides_what_tunes_the_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = _StubTuning()
        monkeypatch.setattr(registry, "TUNINGS", (stub, DefaultTuning()))
        monkeypatch.setattr(Settings, "DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        get_engine.cache_clear()
        try:
            engine = get_engine()
            async with engine.connect():
                pass
            await engine.dispose()
        finally:
            get_engine.cache_clear()
        assert stub.connected == 1

    def test_a_stub_satisfies_the_protocol_from_outside_the_package(self) -> None:
        assert isinstance(_StubTuning(), DialectTuning)
