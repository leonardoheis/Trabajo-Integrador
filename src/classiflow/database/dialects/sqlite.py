from classiflow.database.dialects.protocol import TuningConnection
from classiflow.settings import Settings

_MILLISECONDS_PER_SECOND = 1000


class SqliteTuning:
    """The only place in `src/` that knows this project can run on SQLite."""

    @staticmethod
    def matches(url: str) -> bool:
        return url.startswith("sqlite")

    @staticmethod
    def connect_args() -> dict[str, object]:
        # SQLite defaults busy_timeout to 0: a writer that finds the file locked raises
        # instead of waiting. Bulk ingest writes jobs while background jobs write steps.
        return {"timeout": Settings.SQLITE_BUSY_TIMEOUT_SECONDS}

    @staticmethod
    def on_connect(connection: TuningConnection) -> None:
        cursor = connection.cursor()
        try:
            # busy_timeout first: switching journal mode itself needs an exclusive lock,
            # so without it this very pragma raises "database is locked" under the
            # concurrency WAL exists to relieve. connect_args' timeout does not cover
            # pragmas run here.
            timeout_ms = Settings.SQLITE_BUSY_TIMEOUT_SECONDS * _MILLISECONDS_PER_SECOND
            cursor.execute(f"PRAGMA busy_timeout={timeout_ms}")
            # WAL lets the once-per-second job polling read while a write is in flight,
            # rather than each waiting out the other.
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()
