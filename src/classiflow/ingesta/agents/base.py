from abc import abstractmethod

from pydantic import BaseModel


class BaseAgent(BaseModel):
    @property
    @abstractmethod
    def name(self) -> str: ...
