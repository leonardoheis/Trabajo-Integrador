from dependency_injector.containers import DeclarativeContainer


class TestContainer(DeclarativeContainer):
    """This container overwrites the Production container for testing purposes."""
