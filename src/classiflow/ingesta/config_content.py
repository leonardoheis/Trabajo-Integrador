from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

_CONFIG_PATH = Path(__file__).parents[3] / "config" / "content_validation.yaml"


class ContentValidationConfig(BaseModel):
    min_chars: int
    max_chars: int
    ocr_char_threshold: int = 10
    allowed_languages: list[str]
    slm_confidence_threshold: float = 0.75


@lru_cache(maxsize=1)
def get_content_validation_config() -> ContentValidationConfig:
    return ContentValidationConfig.model_validate(
        yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
    )
