from classiflow.classification.config_classification import (
    ClassificationConfig,
    get_classification_config,
)

_EXPECTED_CONFIDENCE_THRESHOLD = 0.75
_EXPECTED_SMELL_REVIEW_RISK_THRESHOLD = 4
_EXPECTED_MAX_INPUT_TOKENS = 512
_EXPECTED_BERT_MODEL_PATH = "models/bert_tunning_beto_v2"


class TestClassificationConfig:
    def test_defaults(self) -> None:
        config = ClassificationConfig()
        assert config.confidence_threshold == _EXPECTED_CONFIDENCE_THRESHOLD
        assert config.smell_review_risk_threshold == _EXPECTED_SMELL_REVIEW_RISK_THRESHOLD
        assert config.max_input_tokens == _EXPECTED_MAX_INPUT_TOKENS
        assert config.second_opinion_enabled is True
        assert config.foreign_municipality_enabled is True
        assert config.bert_model_path == _EXPECTED_BERT_MODEL_PATH

    def test_get_classification_config_loads_real_yaml(self) -> None:
        config = get_classification_config()
        assert isinstance(config, ClassificationConfig)
        assert config.confidence_threshold > 0
        assert config.smell_review_risk_threshold >= 0
