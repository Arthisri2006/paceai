"""One canonical embedding input shared by token budgeting and vector storage."""


def embedding_text(chunk: dict) -> str:
    metadata = "\n".join(
        f"{field}: {chunk.get(field)}"
        for field in ("title", "section", "department", "category", "document_type")
        if chunk.get(field)
    )
    return f"{metadata}\ncontent: {chunk['text']}"
