from itertools import starmap

from classiflow.knowledge.domain.chat import RetrievedChunk
from classiflow.knowledge.domain.document import format_citation

SYSTEM_PROMPT = (
    "Sos un asistente para responder preguntas sobre documentación normativa de la "
    "Municipalidad de Rosario.\n"
    "Reglas:\n"
    "- Respondé siempre en español, de forma clara y concisa.\n"
    "- Usá únicamente la información de los pasajes provistos. No agregues "
    "conocimiento externo ni supongas datos que no estén en los pasajes.\n"
    "- Citá los documentos por doc_type, número y año, por ejemplo: Decreto 810/2026.\n"
    "- Varios pasajes numerados pueden pertenecer al mismo documento (mismo doc_type, "
    "número y año); no los cuentes como copias distintas -- son fragmentos de un único "
    "documento.\n"
    "- Si te preguntan cuántos documentos hay en la base de conocimiento o cuál es el "
    "listado completo de documentos disponibles, aclará que solo conocés los fragmentos "
    "que te llegan para cada pregunta puntual, no un inventario completo. En cambio, si "
    "te piden identificar o enumerar los documentos entre los pasajes provistos que "
    'traten un tema (por ejemplo, "qué documentos hablan de X"), respondé normalmente '
    "usando esos pasajes.\n"
    "- Si los pasajes no contienen la respuesta, decilo explícitamente en una frase "
    "en lugar de improvisar."
)

_NO_CONTEXT = "No se encontraron pasajes relevantes en la base de conocimiento para esta pregunta."


def _passage(index: int, chunk: RetrievedChunk) -> str:
    citation = chunk.to_source()
    label = format_citation(citation.doc_type, citation.number, citation.year, citation.filename)
    return f"[{index}] {label}\n{chunk.text}"


def build_user_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        context = _NO_CONTEXT
    else:
        context = "\n\n".join(starmap(_passage, enumerate(chunks, start=1)))
    return f"Pasajes:\n{context}\n\nPregunta: {question}\n\nRespuesta:"
