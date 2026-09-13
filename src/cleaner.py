"""Remove site noise and duplicates without discarding source metadata."""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

from config import Settings, settings
from src.utils import content_hash, save_json


NOISE_PATTERNS = (
    r"^skip to (?:main )?content$",
    r"^javascript(?: is)? required$",
    r"^accept (?:all )?cookies?$",
    r"^cookie (?:policy|preferences)$",
    r"^follow us(?: on)?$",
    r"^loading visitor count",
    r"^all rights reserved",
    r"^©\s*pace institute",
)


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _is_noise(line: str) -> bool:
    lowered = line.lower()
    return any(re.search(pattern, lowered) for pattern in NOISE_PATTERNS)


class TextCleaner:
    def __init__(self, config: Settings = settings) -> None:
        self.config = config

    @staticmethod
    def _to_common_records(webpages: Iterable[dict], pdf_pages: Iterable[dict]) -> list[dict]:
        records: list[dict] = []
        for page in webpages:
            headings = page.get("headings", [])
            title = page.get("title") or "PACE webpage"
            if title.strip().lower() in {"pace", "home", "pace home"} and headings:
                title = headings[0]
            records.append(
                {
                    "title": title,
                    "headings": headings,
                    "text": page.get("text", ""),
                    "source_url": page.get("url", ""),
                    "document_type": "webpage",
                    "department": page.get("department"),
                    "page": None,
                    "category": page.get("category", "general"),
                }
            )
        records.extend(pdf_pages)
        return records

    def clean(self, webpages: Iterable[dict], pdf_pages: Iterable[dict]) -> dict:
        records = self._to_common_records(webpages, pdf_pages)
        line_counts: Counter[str] = Counter()
        normalized_documents: list[list[str]] = []
        for record in records:
            unique_lines = {
                _normalize_line(line).lower()
                for line in record.get("text", "").splitlines()
                if _normalize_line(line)
            }
            line_counts.update(unique_lines)

        repeated_threshold = max(3, int(len(records) * 0.25))
        for record in records:
            lines: list[str] = []
            for raw_line in record.get("text", "").splitlines():
                line = _normalize_line(raw_line)
                if not line or _is_noise(line):
                    continue
                repeated = line_counts[line.lower()] >= repeated_threshold
                if repeated and len(line) < 180:
                    continue
                if not lines or lines[-1].lower() != line.lower():
                    lines.append(line)
            normalized_documents.append(lines)

        cleaned: list[dict] = []
        seen_hashes: set[tuple] = set()
        duplicate_count = 0
        for record, lines in zip(records, normalized_documents, strict=True):
            text = "\n".join(lines).strip()
            if len(text.split()) < 5:
                continue
            digest = content_hash(text)
            identity = (record.get("source_url"), record.get("page"), digest)
            if identity in seen_hashes:
                duplicate_count += 1
                continue
            seen_hashes.add(identity)
            clean_record = dict(record)
            clean_record["text"] = text
            clean_record["content_hash"] = digest
            cleaned.append(clean_record)

        result = {
            "documents": cleaned,
            "stats": {
                "input_documents": len(records),
                "clean_documents": len(cleaned),
                "duplicates_removed": duplicate_count,
            },
        }
        save_json(self.config.cleaned_dir / "documents.json", result)
        return result
