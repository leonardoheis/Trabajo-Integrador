from dataclasses import dataclass


class LlmProviderError(Exception): ...


@dataclass
class ModelNotFoundError(LlmProviderError):
    path: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Model file not found: {self.path}"


@dataclass
class ModelLoadError(LlmProviderError):
    path: str
    cause: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Failed to load model at '{self.path}': {self.cause}"
