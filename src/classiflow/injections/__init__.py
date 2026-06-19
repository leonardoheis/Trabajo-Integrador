from functools import cache

from .production import Container
from .test import TestContainer


@cache  # noqa: RUF067
def configure_container() -> Container:
    container = Container()
    container.wire(packages=["classiflow"])
    return container


__all__ = ["Container", "TestContainer", "configure_container"]
