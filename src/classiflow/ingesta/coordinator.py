from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from classiflow.ingesta.domain import (
    ContentValidationResult,
    DuplicateControlResult,
    ExtractionResult,
    FileReceptionResult,
    FormatDecision,
    FormatValidationResult,
    JobContext,
    JobState,
    NodeUpdate,
)
from classiflow.ingesta.nodes import (
    ContentValidationNode,
    DuplicateControlNode,
    ExtractionStep,
    FileReceptionNode,
    FormatValidationNode,
)

NodeUpdateValue = (
    str
    | FileReceptionResult
    | FormatValidationResult
    | ExtractionResult
    | ContentValidationResult
    | DuplicateControlResult
)

_AnyResult = (
    FileReceptionResult | FormatValidationResult | ContentValidationResult | DuplicateControlResult
)


def _dump(update: NodeUpdate) -> dict[str, NodeUpdateValue]:
    # Not .model_dump(exclude_none=True): that recursively dumps nested BaseModel
    # fields (reception, format_validation, ...) into plain dicts, but downstream
    # routing (_route_node1 etc.) and node.run() do attribute access (r.passed) on
    # them, expecting the actual result objects. Iterating the model instead yields
    # each field's raw value undumped, so nested instances survive intact.
    return {k: v for k, v in update if v is not None}


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
    extraction_step: ExtractionStep,
) -> CompiledStateGraph:  # type: ignore[type-arg]
    async def _node1(state: JobState) -> dict[str, NodeUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await node1.run(ctx, state.get("file_bytes"))
        return _dump(NodeUpdate(reception=result))

    async def _node2(state: JobState) -> dict[str, NodeUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await node2.run(ctx, state["reception"])
        return _dump(NodeUpdate(format_validation=result))

    async def _extract(state: JobState) -> dict[str, NodeUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        file_bytes = state.get("file_bytes") or b""
        result = await extraction_step.run(ctx, file_bytes, state["filename"])
        return _dump(NodeUpdate(text=result.text, extraction=result))

    async def _node3(state: JobState) -> dict[str, NodeUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await node3.run(ctx, state.get("text", ""), state["reception"])
        return _dump(NodeUpdate(content_validation=result))

    async def _node4(state: JobState) -> dict[str, NodeUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await node4.run(ctx, state["reception"].sha256, state.get("text", ""))
        return _dump(NodeUpdate(duplicate_control=result))

    def _accept(_state: JobState) -> dict[str, NodeUpdateValue]:
        return _dump(NodeUpdate(final_status="accepted"))

    def _reject(state: JobState) -> dict[str, NodeUpdateValue]:
        return _dump(
            NodeUpdate(final_status="rejected", rejection_reason=_get_rejection_reason(state))
        )

    def _review(state: JobState) -> dict[str, NodeUpdateValue]:
        return _dump(
            NodeUpdate(final_status="review", rejection_reason=_get_rejection_reason(state))
        )

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
