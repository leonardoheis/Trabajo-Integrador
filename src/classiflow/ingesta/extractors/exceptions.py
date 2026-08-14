from dataclasses import dataclass


class ExtractionError(Exception): ...


@dataclass
class MarkItDownError(ExtractionError):
    filename: str
    cause: Exception

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"MarkItDown could not convert '{self.filename}': {self.cause}"


@dataclass
class OcrError(ExtractionError):
    filename: str
    cause: Exception

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"OCR failed for '{self.filename}': {self.cause}"
