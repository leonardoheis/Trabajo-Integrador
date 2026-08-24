from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from classiflow.config_loader import load_yaml_config
from classiflow.settings import Settings


class ClassificationConfig(BaseModel):
    confidence_threshold: float = 0.75
    smell_review_risk_threshold: int = 4
    max_input_tokens: int = 512
    second_opinion_enabled: bool = True
    foreign_municipality_enabled: bool = True
    bert_model_path: str = "models/bert_tunning_beto_v2"
    ood_mahalanobis_p_threshold: float = 0.001
    ood_cosine_threshold: float = 13.7366
    ood_knn_distance_threshold: float = 26.125
    ood_tfidf_cosine_threshold: float = 2.5
    ood_pca_components: int = 64
    ood_trained_municipality: str = "rosario"


@lru_cache(maxsize=1)
def get_classification_config() -> ClassificationConfig:
    return load_yaml_config(Path(Settings.classification_config_path), ClassificationConfig)
