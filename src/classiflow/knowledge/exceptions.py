class KnowledgeError(Exception):
    """Base for every knowledge-base failure.

    Each capability defines its own subclasses in its `exceptions.py`; callers that
    do not care which stage failed can catch this one -- see
    `api/error_handlers/knowledge.py`.
    """
