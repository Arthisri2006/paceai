from __future__ import annotations

from dataclasses import replace

import pymupdf

from config import settings
from src.chunker import DocumentChunker
from src.cleaner import TextCleaner
from src.pdf_loader import PacePdfLoader


def test_pdf_extraction_preserves_page_numbers_and_url(tmp_path) -> None:
    path = tmp_path / "r23-syllabus.pdf"
    document = pymupdf.open()
    first = document.new_page()
    first.insert_text((72, 72), "R23 Computer Science syllabus semester one")
    second = document.new_page()
    second.insert_text((72, 72), "R23 Computer Science syllabus semester two")
    document.save(path)
    document.close()

    pages = PacePdfLoader.extract_file(path, "https://pace.ac.in/docs/r23-syllabus.pdf")

    assert [page["page"] for page in pages] == [1, 2]
    assert all(page["document_type"] == "pdf" for page in pages)
    assert all(page["source_url"].startswith("https://pace.ac.in/") for page in pages)


def test_cleaning_and_chunking_preserve_required_metadata(tmp_path) -> None:
    configured = replace(
        settings,
        cleaned_dir=tmp_path / "cleaned",
        chunk_size=12,
        chunk_overlap=3,
    )
    repeated_footer = "© PACE Institute of Technology and Sciences"
    webpages = [
        {
            "title": f"Page {number}",
            "headings": ["Academic Regulations"],
            "text": f"{repeated_footer}\nR23 regulations provide detailed academic guidance number {number}. "
            "Students should consult the official document for programme rules and requirements.",
            "url": f"https://pace.ac.in/page-{number}",
            "department": None,
            "category": "academics",
        }
        for number in range(3)
    ]
    cleaned = TextCleaner(configured).clean(webpages, [])
    chunks = DocumentChunker(configured).chunk(cleaned["documents"])["chunks"]

    assert repeated_footer not in cleaned["documents"][0]["text"]
    assert len(chunks) >= 3
    required = {
        "title", "section", "source_url", "document_type", "department", "page", "category"
    }
    assert required.issubset(chunks[0])
