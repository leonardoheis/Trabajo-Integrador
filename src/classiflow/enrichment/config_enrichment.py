from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from classiflow.config_loader import load_yaml_config
from classiflow.settings import Settings


class EnrichmentConfig(BaseModel):
    repeated_line_min_count: int = 3
    max_enrichment_retries: int = 2
    entity_excerpt_len: int = 5000


@lru_cache(maxsize=1)
def get_enrichment_config() -> EnrichmentConfig:
    return load_yaml_config(Path(Settings.enrichment_config_path), EnrichmentConfig)
