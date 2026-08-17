from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

from classiflow.settings import Settings


class ExtractionConfig(BaseModel):
    min_text_for_ocr: int = 50
    min_usable_text: int = 20
    max_concurrent_extractions: int = 2


@lru_cache(maxsize=1)
def get_extraction_config() -> ExtractionConfig:
    config_path = Path(Settings.extraction_config_path)
    return ExtractionConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))
