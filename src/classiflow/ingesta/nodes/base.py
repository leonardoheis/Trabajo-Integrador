from abc import abstractmethod

from pydantic import BaseModel


class BaseNode(BaseModel):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def model_path(self) -> str | None:
        return None
