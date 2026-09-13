"""Page-local chunks budgeted against the actual, complete embedding input.

Whole extracted lines (including course rows) are kept together when they fit.
Oversized lines are recursively split, never silently truncated. A semester
heading is carried into table continuations so rows retain their interpretation.
"""
from __future__ import annotations

import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import Settings, settings
from src.chunker import DocumentChunker
from src.embedding_text import embedding_text


class TokenDocumentChunker(DocumentChunker):
    def __init__(self, tokenizer, model_limit: int, config: Settings = settings):
        self.config = config
        self.tokenizer = tokenizer
        self.limit = min(config.chunk_token_limit, model_limit)
        if self.limit < 32 or not 0 <= config.chunk_token_overlap < self.limit // 2:
            raise ValueError("Token limit must be >=32 and overlap less than half the limit.")

    def count(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=True, truncation=False))

    def split_document(self, document: dict) -> list[str]:
        def size(text):
            return self.count(embedding_text({**document, "text": text}))

        if size("") + 16 > self.limit:
            raise ValueError("Document metadata leaves insufficient embedding space; shorten metadata explicitly.")
        if size(document["text"]) <= self.limit:
            return [document["text"].strip()] if document["text"].strip() else []
        chunks: list[str] = []
        lines: list[str] = []
        heading = ""
        table_header = next((line.strip() for line in document["text"].splitlines()
                             if "course structure" in line.lower()), "")

        def flush():
            text = "\n".join(lines).strip()
            if text:
                chunks.append(text)

        def continuation():
            tail: list[str] = []
            for line in reversed(lines):
                if self.count("\n".join([line, *tail])) > self.config.chunk_token_overlap:
                    break
                tail.insert(0, line)
            # Do not repeat pre-heading rows under a newer semester heading.
            if heading and heading in tail:
                tail = tail[tail.index(heading) + 1:]
            prefix = [line for line in (table_header, heading) if line]
            return prefix + [line for line in tail if line not in prefix]

        for raw in document["text"].splitlines():
            line = raw.strip()
            if not line:
                continue
            new_heading = bool(re.search(r"\bYear\b.*\bSemester\b", line, re.I))
            if new_heading:
                # Semester boundaries are useful semantic boundaries for tables.
                if heading:
                    flush()
                    lines = [table_header] if table_header else []
                heading = line
            candidate = "\n".join([*lines, line])
            if size(candidate) <= self.limit:
                lines.append(line)
                continue
            flush()
            carried = continuation()
            while carried and size("\n".join([*carried, line])) > self.limit:
                carried.pop()
            if size(line) <= self.limit:
                lines = [*carried, line]
                continue
            # Split only lines which cannot fit by themselves. Empty separator
            # is a last-resort character split for very long unbroken strings.
            available = self.limit - size("") - 4
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=available, chunk_overlap=min(self.config.chunk_token_overlap, available // 4),
                length_function=self.count, separators=[". ", "; ", ", ", " ", ""],
            )
            pieces = splitter.split_text(line)
            for piece in pieces:
                if size(piece) > self.limit:
                    raise ValueError("Unable to fit an extracted line inside the embedding budget.")
            chunks.extend(pieces[:-1])
            lines = pieces[-1:]  # Preserve exact text; no tokenizer decode round-trip.
        flush()
        if any(size(text) > self.limit for text in chunks):
            raise ValueError("Chunk exceeds complete embedding-input token budget.")
        return chunks
