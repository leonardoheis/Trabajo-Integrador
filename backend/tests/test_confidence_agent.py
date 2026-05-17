"""Tests unitarios — confidence_agent."""
from __future__ import annotations

import pytest

from agents.confidence_agent import check_confidence
from models.document import AzureAnalysisResult, DocumentType


@pytest.mark.unit
class TestCheckConfidence:
    def test_above_threshold_returns_true(self, invoice_azure_result: AzureAnalysisResult) -> None:
        score, above = check_confidence(invoice_azure_result)
        assert score == pytest.approx(0.92)
        assert above is True

    def test_below_threshold_returns_false(self, low_confidence_result: AzureAnalysisResult) -> None:
        score, above = check_confidence(low_confidence_result)
        assert score == pytest.approx(0.45)
        assert above is False

    def test_exactly_at_threshold_is_above(self) -> None:
        result = AzureAnalysisResult(
            doc_type=DocumentType.REPORT,
            confidence=0.85,  # igual al threshold por defecto
            fields={},
            raw_response={},
        )
        _, above = check_confidence(result)
        assert above is True

    def test_score_just_below_threshold(self) -> None:
        result = AzureAnalysisResult(
            doc_type=DocumentType.INVOICE,
            confidence=0.8499,
            fields={},
            raw_response={},
        )
        _, above = check_confidence(result)
        assert above is False

    def test_returns_correct_score_value(self, contract_azure_result: AzureAnalysisResult) -> None:
        score, _ = check_confidence(contract_azure_result)
        assert score == contract_azure_result.confidence

    def test_logs_warning_when_below_threshold(
        self, low_confidence_result: AzureAnalysisResult, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging
        with caplog.at_level(logging.WARNING, logger="agents.confidence_agent"):
            check_confidence(low_confidence_result)
        assert "below threshold" in caplog.text.lower()

    def test_logs_info_when_above_threshold(
        self, invoice_azure_result: AzureAnalysisResult, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging
        with caplog.at_level(logging.INFO, logger="agents.confidence_agent"):
            check_confidence(invoice_azure_result)
        assert "passed" in caplog.text.lower()
