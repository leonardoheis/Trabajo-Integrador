class LlmProviderError(Exception): ...


class ModelNotFoundError(LlmProviderError):
    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Model file not found: {self.path}"


class ModelLoadError(LlmProviderError):
    def __init__(self, path: str, cause: str) -> None:
        self.path = path
        self.cause = cause
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Failed to load model at '{self.path}': {self.cause}"
