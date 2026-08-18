from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from classiflow.config_loader import load_yaml_config

_CONFIG_PATH = Path(__file__).parents[3] / "config" / "duplicate_control.yaml"


class DuplicateControlConfig(BaseModel):
    cosine_similarity_threshold: float = 0.85


@lru_cache(maxsize=1)
def get_duplicate_control_config() -> DuplicateControlConfig:
    return load_yaml_config(_CONFIG_PATH, DuplicateControlConfig)
