from itertools import starmap

from classiflow.knowledge.domain.chat import RetrievedChunk

SYSTEM_PROMPT = (
    "Sos un asistente que responde preguntas sobre documentación normativa de la "
    "Municipalidad de Rosario.\n"
    "Reglas:\n"
    "- Respondé siempre en español, de forma clara y concisa.\n"
    "- Usá únicamente la información de los pasajes provistos. No agregues "
    "conocimiento externo ni supongas datos que no estén en los pasajes.\n"
    "- Citá los documentos por doc_type, número y año, por ejemplo: Decreto 810/2026.\n"
    "- Si los pasajes no contienen la respuesta, decilo explícitamente en una frase "
    "en lugar de improvisar."
)

_NO_CONTEXT = "No se encontraron pasajes relevantes en la base de conocimiento para esta pregunta."


def _passage(index: int, chunk: RetrievedChunk) -> str:
    citation = chunk.to_source()
    label = (
        f"{citation.doc_type} {citation.number}/{citation.year}"
        if citation.doc_type and citation.number and citation.year
        else citation.filename
    )
    return f"[{index}] {label}\n{chunk.text}"


def build_user_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        context = _NO_CONTEXT
    else:
        context = "\n\n".join(starmap(_passage, enumerate(chunks, start=1)))
    return f"Pasajes:\n{context}\n\nPregunta: {question}\n\nRespuesta:"
