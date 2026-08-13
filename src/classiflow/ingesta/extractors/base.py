from abc import ABC, abstractmethod


class ExtractorBase(ABC):
    @abstractmethod
    def extract(self, file_bytes: bytes, filename: str) -> str: ...
