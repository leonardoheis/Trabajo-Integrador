from enum import Enum


class ReviewRoute(str, Enum):
    """Classification coordinator's review-route outcome -- set by ConfidenceGateNode,
    consumed by the coordinator's conditional edge, RoutingNode, and the human-review
    decision endpoint. LLM_JUDGE is a legitimate transient value (spec Decision 5's
    "never a persisted or routed terminal state") -- only Routing enforces the
    two-terminal-state rule."""

    ACCEPT = "accept"
    HUMAN_REVIEW = "human_review"
    LLM_JUDGE = "llm_judge"
