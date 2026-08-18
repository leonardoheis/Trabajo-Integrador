from classiflow.enrichment.config_enrichment import EnrichmentConfig, get_enrichment_config


class TestEnrichmentConfig:
    def test_defaults(self) -> None:
        config = EnrichmentConfig()
        assert config.repeated_line_min_count == 3  # noqa: PLR2004
        assert config.max_enrichment_retries == 2  # noqa: PLR2004

    def test_get_enrichment_config_loads_real_yaml(self) -> None:
        config = get_enrichment_config()
        assert isinstance(config, EnrichmentConfig)
        assert config.repeated_line_min_count >= 1
        assert config.max_enrichment_retries >= 0
