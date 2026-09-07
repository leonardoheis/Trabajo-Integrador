SUMMARY_SYSTEM_PROMPT = (
    "Resumís conversaciones para dar contexto a un asistente. Sé breve y concreto: "
    "conservá nombres propios, números de decreto/ordenanza, fechas y temas puntuales "
    "mencionados. No inventes información que no esté en el resumen anterior ni en el "
    "nuevo intercambio."
)


def build_summary_prompt(old_summary: str, exchanges: str) -> str:
    summary_block = old_summary or "(sin resumen previo)"
    return (
        f"Resumen anterior:\n{summary_block}\n\n"
        f"Nuevos intercambios:\n{exchanges}\n\n"
        "Resumen actualizado (incorporá los nuevos intercambios al resumen anterior):"
    )
