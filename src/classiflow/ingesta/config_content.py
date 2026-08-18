from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from classiflow.config_loader import load_yaml_config

_CONFIG_PATH = Path(__file__).parents[3] / "config" / "content_validation.yaml"


class ContentValidationConfig(BaseModel):
    min_chars: int
    ocr_char_threshold: int = 10
    excerpt_len: int = 500
    allowed_languages: list[str]
    slm_confidence_threshold: float = 0.75


@lru_cache(maxsize=1)
def get_content_validation_config() -> ContentValidationConfig:
    return load_yaml_config(_CONFIG_PATH, ContentValidationConfig)
