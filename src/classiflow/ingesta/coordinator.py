from collections.abc import Callable
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from classiflow.ingesta.domain.context import JobContext
from classiflow.ingesta.domain.results import (
    ContentValidationResult,
    DuplicateControlResult,
    FileReceptionResult,
    FormatDecision,
    FormatValidationResult,
)
from classiflow.ingesta.domain.state import JobState
from classiflow.ingesta.nodes.node1_file_reception import FileReceptionNode
from classiflow.ingesta.nodes.node2_format_validation import FormatValidationNode
from classiflow.ingesta.nodes.node3_content_validation import ContentValidationNode
from classiflow.ingesta.nodes.node4_duplicate_control import DuplicateControlNode

TextExtractFn = Callable[[bytes], str]

_AnyResult = (
    FileReceptionResult | FormatValidationResult | ContentValidationResult | DuplicateControlResult
)


def _get_rejection_reason(state: JobState) -> str:
    candidates: list[_AnyResult | None] = [
        state.get("duplicate_control"),
        state.get("content_validation"),
        state.get("format_validation"),
        state.get("reception"),
    ]
    for result in candidates:
        if result is not None and result.rejection_reason:
            return result.rejection_reason
    return ""


def _route_node1(state: JobState) -> str:
    r = state.get("reception")
    return "node2" if r and r.passed else "reject"


def _route_node2(state: JobState) -> str:
    fv = state.get("format_validation")
    if fv is None or not fv.passed:
        if fv and fv.decision == FormatDecision.MANUAL_REVIEW:
            return "review"
        return "reject"
    return "extract"


def _route_node3(state: JobState) -> str:
    cv = state.get("content_validation")
    if cv is None or not cv.passed:
        if cv and cv.needs_agent_review:
            return "review"
        return "reject"
    return "node4"


def _route_node4(state: JobState) -> str:
    dc = state.get("duplicate_control")
    return "accept" if dc and dc.passed else "reject"


def build_coordinator(
    node1: FileReceptionNode,
    node2: FormatValidationNode,
    node3: ContentValidationNode,
    node4: DuplicateControlNode,
    *,
    # ponytail: best-effort fallback; swap for MarkItDown once added as a dependency
    text_extractor: TextExtractFn = lambda b: b.decode("utf-8", errors="replace"),
) -> CompiledStateGraph:  # type: ignore[type-arg]
    async def _node1(state: JobState) -> dict[str, Any]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await node1.run(ctx, state.get("file_bytes"))
        return {"reception": result}

    async def _node2(state: JobState) -> dict[str, Any]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await node2.run(ctx, state["reception"])
        return {"format_validation": result}

    def _extract(state: JobState) -> dict[str, Any]:
        file_bytes = state.get("file_bytes") or b""
        return {"text": text_extractor(file_bytes)}

    async def _node3(state: JobState) -> dict[str, Any]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await node3.run(ctx, state.get("text", ""), state["reception"])
        return {"content_validation": result}

    async def _node4(state: JobState) -> dict[str, Any]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await node4.run(ctx, state["reception"].sha256, state.get("text", ""))
        return {"duplicate_control": result}

    def _accept(_state: JobState) -> dict[str, Any]:
        return {"final_status": "accepted"}

    def _reject(state: JobState) -> dict[str, Any]:
        return {"final_status": "rejected", "rejection_reason": _get_rejection_reason(state)}

    def _review(state: JobState) -> dict[str, Any]:
        return {"final_status": "review", "rejection_reason": _get_rejection_reason(state)}

    graph: StateGraph = StateGraph(JobState)  # type: ignore[type-arg]
    graph.add_node("node1", _node1)
    graph.add_node("node2", _node2)
    graph.add_node("extract", _extract)
    graph.add_node("node3", _node3)
    graph.add_node("node4", _node4)
    graph.add_node("accept", _accept)  # type: ignore[arg-type]
    graph.add_node("reject", _reject)
    graph.add_node("review", _review)

    graph.set_entry_point("node1")
    graph.add_conditional_edges("node1", _route_node1, {"node2": "node2", "reject": "reject"})
    graph.add_conditional_edges(
        "node2",
        _route_node2,
        {"extract": "extract", "reject": "reject", "review": "review"},
    )
    graph.add_edge("extract", "node3")
    graph.add_conditional_edges(
        "node3",
        _route_node3,
        {"node4": "node4", "reject": "reject", "review": "review"},
    )
    graph.add_conditional_edges("node4", _route_node4, {"accept": "accept", "reject": "reject"})
    graph.add_edge("accept", END)
    graph.add_edge("reject", END)
    graph.add_edge("review", END)

    return graph.compile()
