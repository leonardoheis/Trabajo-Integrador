from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

_CONFIG_PATH = Path(__file__).parents[3] / "config" / "allowed_formats.yaml"


class AllowedFormatsConfig(BaseModel):
    allowed_mime_types: list[str]
    allowed_extensions: list[str]
    disabled_mime_types: list[str] = []
    disabled_extensions: list[str] = []
    mime_to_extensions: dict[str, list[str]] = {}
    max_file_size_mb: int

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_allowed_formats() -> AllowedFormatsConfig:
    return AllowedFormatsConfig.model_validate(
        yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
    )
