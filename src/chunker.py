"""Turn cleaned documents into metadata-rich retrieval chunks."""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import Settings, settings
from src.utils import content_hash, save_json


class DocumentChunker:
    def __init__(self, config: Settings = settings) -> None:
        self.config = config
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            length_function=lambda value: len(value.split()),
            separators=["\n\n", "\n", ". ", "; ", ", ", " "],
        )

    def chunk(self, documents: list[dict]) -> dict:
        chunks: list[dict] = []
        seen: set[tuple] = set()
        for document in documents:
            title = document.get("title") or "PACE source"
            headings = document.get("headings") or []
            section = headings[0] if headings else title
            metadata = {**document, "title": title, "section": section}
            for position, text in enumerate(self.split_document(metadata)):
                digest = content_hash(text)
                identity = (document["source_url"], document.get("page"), digest)
                if identity in seen:
                    continue
                seen.add(identity)
                chunks.append(
                    {
                        "id": f"chunk-{len(chunks):06d}-{digest[:10]}",
                        "text": text,
                        "title": title,
                        "section": section,
                        "source_url": document["source_url"],
                        "document_type": document["document_type"],
                        "department": document.get("department"),
                        "page": document.get("page"),
                        "category": document.get("category", "general"),
                        "position": position,
                    }
                )
        result = {"chunks": chunks, "stats": {"chunks": len(chunks)}}
        save_json(self.config.cleaned_dir / "chunks.json", result)
        return result

    def split_document(self, document: dict) -> list[str]:
        return self.splitter.split_text(document["text"])
