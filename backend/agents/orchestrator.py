from __future__ import annotations

import logging
from typing import Any, Optional

from typing_extensions import TypedDict

from config import settings
from models import AzureAnalysisResult, DocumentType, IngestionResult
from agents import confidence_agent, enrichment_agent, field_extractor, routing_agent
from document_ai.client import get_client

logger = logging.getLogger(__name__)


class OrchestrationState(TypedDict, total=False):
    job_id: str
    ingestion_result: Optional[IngestionResult]
    file_bytes: bytes
    azure_result: Optional[AzureAnalysisResult]
    confidence: float
    is_above_threshold: bool
    fields: dict[str, Any]
    tags: list[str]
    metadata: dict[str, Any]
    output_path: str
    error: Optional[str]


def _build_graph():
    """Build and compile the LangGraph StateGraph."""
    from langgraph.graph import END, StateGraph

    graph = StateGraph(OrchestrationState)

    graph.add_node("azure_analysis", _node_azure_analysis)
    graph.add_node("confidence_check", _node_confidence_check)
    graph.add_node("field_extraction", _node_field_extraction)
    graph.add_node("enrichment", _node_enrichment)
    graph.add_node("routing", _node_routing)

    graph.set_entry_point("azure_analysis")

    graph.add_edge("azure_analysis", "confidence_check")
    graph.add_edge("confidence_check", "field_extraction")
    graph.add_edge("field_extraction", "enrichment")

    # After enrichment: always go to routing (routing itself decides the folder)
    graph.add_edge("enrichment", "routing")
    graph.add_edge("routing", END)

    return graph.compile()


# Build the graph once at module load time
_compiled_graph = None


def _get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_graph()
    return _compiled_graph


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------

async def _node_azure_analysis(state: OrchestrationState) -> OrchestrationState:
    logger.info("Node: azure_analysis — job_id=%s", state.get("job_id"))
    try:
        client = get_client()
        ingestion = state["ingestion_result"]
        result = await client.analyze(state["file_bytes"], ingestion.filename)
        return {**state, "azure_result": result}
    except Exception as exc:
        logger.error("Azure analysis failed: %s", exc)
        fallback = AzureAnalysisResult(
            doc_type=DocumentType.UNKNOWN,
            confidence=0.0,
            fields={},
            raw_response={"error": str(exc)},
        )
        return {**state, "azure_result": fallback, "error": str(exc)}


async def _node_confidence_check(state: OrchestrationState) -> OrchestrationState:
    logger.info("Node: confidence_check — job_id=%s", state.get("job_id"))
    azure_result = state.get("azure_result")
    if azure_result is None:
        return {**state, "confidence": 0.0, "is_above_threshold": False}
    score, above = confidence_agent.check_confidence(azure_result)
    return {**state, "confidence": score, "is_above_threshold": above}


async def _node_field_extraction(state: OrchestrationState) -> OrchestrationState:
    logger.info("Node: field_extraction — job_id=%s", state.get("job_id"))
    azure_result = state.get("azure_result")
    if azure_result is None:
        return {**state, "fields": {}}
    fields = field_extractor.extract_fields(azure_result, azure_result.doc_type)
    return {**state, "fields": fields}


async def _node_enrichment(state: OrchestrationState) -> OrchestrationState:
    logger.info("Node: enrichment — job_id=%s", state.get("job_id"))
    ingestion = state.get("ingestion_result")
    azure_result = state.get("azure_result")
    fields = state.get("fields", {})
    if ingestion is None or azure_result is None:
        return {**state, "tags": [], "metadata": {}}
    metadata = enrichment_agent.enrich(ingestion, azure_result, fields)
    return {**state, "tags": metadata.get("tags", []), "metadata": metadata}


async def _node_routing(state: OrchestrationState) -> OrchestrationState:
    logger.info("Node: routing — job_id=%s", state.get("job_id"))
    azure_result = state.get("azure_result")
    ingestion = state.get("ingestion_result")
    if azure_result is None or ingestion is None:
        return {**state, "output_path": "", "error": "Missing required state for routing"}

    output_path = await routing_agent.route(
        job_id=state["job_id"],
        doc_type=azure_result.doc_type,
        confidence=state.get("confidence", 0.0),
        file_bytes=state["file_bytes"],
        filename=ingestion.filename,
        metadata=state.get("metadata", {}),
    )
    return {**state, "output_path": output_path}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def orchestrate(
    job_id: str,
    ingestion_result: IngestionResult,
    file_bytes: bytes,
) -> OrchestrationState:
    """Run the full orchestration pipeline for a single document.

    Returns the final OrchestrationState after all nodes have executed.
    """
    initial_state: OrchestrationState = {
        "job_id": job_id,
        "ingestion_result": ingestion_result,
        "file_bytes": file_bytes,
        "azure_result": None,
        "confidence": 0.0,
        "is_above_threshold": False,
        "fields": {},
        "tags": [],
        "metadata": {},
        "output_path": "",
        "error": None,
    }

    graph = _get_graph()
    final_state: OrchestrationState = await graph.ainvoke(initial_state)
    logger.info(
        "Orchestration complete — job_id=%s output_path=%s error=%s",
        job_id,
        final_state.get("output_path"),
        final_state.get("error"),
    )
    return final_state
