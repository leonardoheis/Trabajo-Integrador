"""Tests unitarios — orchestrator (nodos individuales + pipeline completo)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents import orchestrator as orch_module
from agents.orchestrator import (
    OrchestrationState,
    _get_graph,
    _node_azure_analysis,
    _node_confidence_check,
    _node_enrichment,
    _node_field_extraction,
    _node_routing,
    orchestrate,
)
from models.document import AzureAnalysisResult, DocumentType, IngestionResult


def _base_state(job_id: str = "test-job") -> OrchestrationState:
    return OrchestrationState(
        job_id=job_id,
        ingestion_result=IngestionResult(filename="doc.pdf", format="pdf", size_bytes=1024),
        file_bytes=b"%PDF minimal",
        azure_result=None,
        confidence=0.0,
        is_above_threshold=False,
        fields={},
        tags=[],
        metadata={},
        output_path="",
        error=None,
    )


@pytest.mark.unit
class TestNodeAzureAnalysis:
    async def test_success_sets_azure_result(self, invoice_azure_result: AzureAnalysisResult) -> None:
        mock_client = MagicMock()
        mock_client.analyze = AsyncMock(return_value=invoice_azure_result)
        with patch("agents.orchestrator.get_client", return_value=mock_client):
            result = await _node_azure_analysis(_base_state())
        assert result["azure_result"] == invoice_azure_result

    async def test_exception_sets_fallback_and_error(self) -> None:
        mock_client = MagicMock()
        mock_client.analyze = AsyncMock(side_effect=RuntimeError("Azure down"))
        with patch("agents.orchestrator.get_client", return_value=mock_client):
            result = await _node_azure_analysis(_base_state())
        assert result["azure_result"].doc_type == DocumentType.UNKNOWN
        assert result["error"] == "Azure down"


@pytest.mark.unit
class TestNodeConfidenceCheck:
    async def test_with_azure_result(self, invoice_azure_result: AzureAnalysisResult) -> None:
        state = _base_state()
        state["azure_result"] = invoice_azure_result
        result = await _node_confidence_check(state)
        assert result["confidence"] == pytest.approx(0.92)
        assert result["is_above_threshold"] is True

    async def test_without_azure_result(self) -> None:
        result = await _node_confidence_check(_base_state())
        assert result["confidence"] == 0.0
        assert result["is_above_threshold"] is False


@pytest.mark.unit
class TestNodeFieldExtraction:
    async def test_with_azure_result(self, invoice_azure_result: AzureAnalysisResult) -> None:
        state = _base_state()
        state["azure_result"] = invoice_azure_result
        result = await _node_field_extraction(state)
        assert isinstance(result["fields"], dict)
        assert "vendor_name" in result["fields"]

    async def test_without_azure_result(self) -> None:
        result = await _node_field_extraction(_base_state())
        assert result["fields"] == {}


@pytest.mark.unit
class TestNodeEnrichment:
    async def test_with_full_state(self, invoice_azure_result: AzureAnalysisResult) -> None:
        state = _base_state()
        state["azure_result"] = invoice_azure_result
        state["fields"] = {"vendor_name": "Acme"}
        result = await _node_enrichment(state)
        assert "tags" in result
        assert "metadata" in result

    async def test_without_ingestion(self) -> None:
        state = _base_state()
        state["ingestion_result"] = None  # type: ignore[assignment]
        result = await _node_enrichment(state)
        assert result["tags"] == []
        assert result["metadata"] == {}

    async def test_without_azure_result(self) -> None:
        result = await _node_enrichment(_base_state())
        assert result["tags"] == []


@pytest.mark.unit
class TestNodeRouting:
    async def test_routes_file(self, tmp_output_dir, invoice_azure_result: AzureAnalysisResult) -> None:
        state = _base_state()
        state["azure_result"] = invoice_azure_result
        state["confidence"] = 0.92
        result = await _node_routing(state)
        assert result["output_path"] != ""

    async def test_without_azure_result_returns_error(self) -> None:
        result = await _node_routing(_base_state())
        assert result["error"] is not None
        assert result["output_path"] == ""

    async def test_without_ingestion_returns_error(self, invoice_azure_result: AzureAnalysisResult) -> None:
        state = _base_state()
        state["azure_result"] = invoice_azure_result
        state["ingestion_result"] = None  # type: ignore[assignment]
        result = await _node_routing(state)
        assert result["error"] is not None


@pytest.mark.unit
class TestGetGraph:
    def test_get_graph_returns_same_instance(self) -> None:
        orch_module._compiled_graph = None  # reset singleton
        g1 = _get_graph()
        g2 = _get_graph()
        assert g1 is g2


@pytest.mark.unit
class TestOrchestrate:
    async def test_full_pipeline(
        self,
        tmp_output_dir,
        ingestion_result: IngestionResult,
        invoice_azure_result: AzureAnalysisResult,
    ) -> None:
        mock_client = MagicMock()
        mock_client.analyze = AsyncMock(return_value=invoice_azure_result)
        orch_module._compiled_graph = None  # ensure fresh graph
        with patch("agents.orchestrator.get_client", return_value=mock_client):
            final = await orchestrate(
                job_id="pipeline-test",
                ingestion_result=ingestion_result,
                file_bytes=b"%PDF minimal",
            )
        assert final["azure_result"] is not None
        assert final["output_path"] != ""
