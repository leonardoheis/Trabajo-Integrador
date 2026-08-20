from abc import ABC, abstractmethod


class ExtractorBase(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def extract(self, file_bytes: bytes, filename: str) -> str: ...
