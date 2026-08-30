from classiflow.knowledge.domain.chunk import Embedding


def dot(left: Embedding, right: Embedding) -> float:
    """Dot product of two embeddings.

    Equivalent to cosine similarity when both vectors are already normalized, which
    is how the embedder produces them.

    Returns:
        The scalar product of the overlapping components.
    """
    return float(sum(a * b for a, b in zip(left, right, strict=False)))
