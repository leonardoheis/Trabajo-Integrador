from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from classiflow.ingesta.config_loader import load_yaml_config
from classiflow.settings import Settings


class ExtractionConfig(BaseModel):
    min_text_for_ocr: int = 50
    min_usable_text: int = 20
    max_concurrent_extractions: int = 2


@lru_cache(maxsize=1)
def get_extraction_config() -> ExtractionConfig:
    return load_yaml_config(Path(Settings.extraction_config_path), ExtractionConfig)
