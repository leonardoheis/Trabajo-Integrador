from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

_CONFIG_PATH = Path(__file__).parents[3] / "config" / "duplicate_control.yaml"


class DuplicateControlConfig(BaseModel):
    cosine_similarity_threshold: float = 0.85
    on_duplicate: str = "reject"


@lru_cache(maxsize=1)
def get_duplicate_control_config() -> DuplicateControlConfig:
    return DuplicateControlConfig.model_validate(
        yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
    )
