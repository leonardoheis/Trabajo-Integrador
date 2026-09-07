from classiflow.database.dialects.protocol import DialectTuning, TuningConnection
from classiflow.database.dialects.sqlite import SqliteTuning


class DefaultTuning:
    """Terminator for the registry, not an engine: leaves SQLAlchemy's own defaults alone.

    A URL with no tuning is not an error. SQLAlchemy already supports every engine it
    ships, so tuning is a refinement -- failing closed here would break a working
    database to enforce a registry nobody needs.
    """

    @staticmethod
    def matches(_url: str) -> bool:
        return True

    @staticmethod
    def connect_args() -> dict[str, object]:
        return {}

    @staticmethod
    def on_connect(_connection: TuningConnection) -> None:
        return


# Append a new engine's tuning before DefaultTuning, which matches everything -- anything
# after it is unreachable. Kept an explicit tuple rather than self-registration: import
# order would otherwise decide whether a dialect exists, and a forgotten import would
# disable tuning silently instead of loudly.
TUNINGS: tuple[DialectTuning, ...] = (SqliteTuning(), DefaultTuning())


def resolve_tuning(url: str) -> DialectTuning:
    """Find the tuning that claims this database URL.

    Returns:
        The first matching tuning; DefaultTuning when no engine-specific one applies.
    """
    return next(tuning for tuning in TUNINGS if tuning.matches(url))
