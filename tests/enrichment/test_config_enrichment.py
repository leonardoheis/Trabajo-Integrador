from classiflow.enrichment.config_enrichment import EnrichmentConfig, get_enrichment_config

_EXPECTED_REPEATED_LINE_MIN_COUNT = 3
_EXPECTED_MAX_ENRICHMENT_RETRIES = 2
_EXPECTED_GIBBERISH_RATIO = 0.6
_EXPECTED_GIBBERISH_MIN_TOKENS = 4


class TestEnrichmentConfig:
    def test_defaults(self) -> None:
        config = EnrichmentConfig()
        assert config.repeated_line_min_count == _EXPECTED_REPEATED_LINE_MIN_COUNT
        assert config.max_enrichment_retries == _EXPECTED_MAX_ENRICHMENT_RETRIES

    def test_gibberish_detection_defaults(self) -> None:
        config = EnrichmentConfig()
        assert config.gibberish_detection_enabled is False
        assert config.gibberish_short_token_ratio == _EXPECTED_GIBBERISH_RATIO
        assert config.gibberish_min_tokens == _EXPECTED_GIBBERISH_MIN_TOKENS

    def test_get_enrichment_config_loads_real_yaml(self) -> None:
        config = get_enrichment_config()
        assert isinstance(config, EnrichmentConfig)
        assert config.repeated_line_min_count >= 1
        assert config.max_enrichment_retries >= 0
