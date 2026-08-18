from classiflow.enrichment.config_enrichment import EnrichmentConfig, get_enrichment_config

_EXPECTED_REPEATED_LINE_MIN_COUNT = 3
_EXPECTED_MAX_ENRICHMENT_RETRIES = 2


class TestEnrichmentConfig:
    def test_defaults(self) -> None:
        config = EnrichmentConfig()
        assert config.repeated_line_min_count == _EXPECTED_REPEATED_LINE_MIN_COUNT
        assert config.max_enrichment_retries == _EXPECTED_MAX_ENRICHMENT_RETRIES

    def test_get_enrichment_config_loads_real_yaml(self) -> None:
        config = get_enrichment_config()
        assert isinstance(config, EnrichmentConfig)
        assert config.repeated_line_min_count >= 1
        assert config.max_enrichment_retries >= 0
