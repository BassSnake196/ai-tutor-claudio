from fastapi import HTTPException, status


MAX_PROMPT_LENGTH = 12_000


def sanitize_prompt(prompt: str) -> str:
    """Normalize untrusted user text before it reaches a model provider."""
    cleaned = prompt.replace("\x00", "").strip()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El prompt no puede estar vacío.")
    if len(cleaned) > MAX_PROMPT_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"El prompt supera el límite de {MAX_PROMPT_LENGTH} caracteres.",
        )
    return cleaned
