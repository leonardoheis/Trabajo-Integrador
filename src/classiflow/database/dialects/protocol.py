from typing import Protocol, runtime_checkable


@runtime_checkable
class TuningCursor(Protocol):
    def execute(self, statement: str) -> object: ...
    def close(self) -> None: ...


@runtime_checkable
class TuningConnection(Protocol):
    """The slice of a DBAPI connection a tuning may use.

    Narrower than SQLAlchemy's DBAPIConnection on purpose: that one declares
    `cursor(*args: Any, **kwargs: Any)`, so anything implementing it -- a test double
    included -- has to admit `Any`. A tuning only ever opens a cursor, runs statements
    and closes it.
    """

    def cursor(self) -> TuningCursor: ...


@runtime_checkable
class DialectTuning(Protocol):
    """Per-engine configuration, applied when the engine is built.

    The three methods are the three things SQLAlchemy lets a dialect influence: which
    URLs it claims, what reaches `create_async_engine(connect_args=...)`, and what runs
    on each new pooled connection.
    """

    def matches(self, url: str) -> bool: ...

    # dict[str, object] rather than a model: SQLAlchemy splats this into the driver's
    # own connect(), so the keys are the driver's -- aiosqlite takes "timeout", asyncpg
    # takes "command_timeout" and "ssl". There is no shared field set to validate.
    def connect_args(self) -> dict[str, object]: ...

    def on_connect(self, connection: TuningConnection) -> None: ...
