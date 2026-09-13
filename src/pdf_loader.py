"""Download public PACE PDFs and extract page-aware text with PyMuPDF."""

from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlsplit

import pymupdf
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import Settings, settings
from src.utils import classify_category, detect_department, save_json
from src.public_http import public_get, validate_public_url

LOGGER = logging.getLogger(__name__)


class PacePdfLoader:
    def __init__(
        self, config: Settings = settings, *, session: requests.Session | None = None
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        if session is None:
            retry = Retry(
                total=3,
                backoff_factor=0.6,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=("GET", "HEAD"),
            )
            self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.user_agent})
        self.pdf_dir = config.raw_dir / "pdfs"
        self._last_request_at = 0.0

    @staticmethod
    def _filename(url: str) -> str:
        original = unquote(Path(urlsplit(url).path).name) or "document.pdf"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", original).strip("-._")
        if not safe.lower().endswith(".pdf"):
            safe += ".pdf"
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
        return f"{digest}-{safe[:120]}"

    def download(self, url: str) -> Path:
        validate_public_url(url)
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        destination = self.pdf_dir / self._filename(url)
        if destination.exists() and destination.stat().st_size > 4:
            return destination

        maximum = self.config.max_pdf_mb * 1024 * 1024
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.config.request_delay - elapsed
        if self._last_request_at and remaining > 0:
            time.sleep(remaining)
        response = public_get(self.session,
            url, timeout=self.config.request_timeout, stream=True
        )
        self._last_request_at = time.monotonic()
        temporary = destination.with_suffix(".pdf.part")
        downloaded = 0
        try:
            response.raise_for_status()
            declared_size = int(response.headers.get("Content-Length", "0") or 0)
            if declared_size > maximum:
                raise ValueError(f"PDF exceeds {self.config.max_pdf_mb} MB limit: {url}")
            with temporary.open("wb") as output:
                for block in response.iter_content(chunk_size=128 * 1024):
                    if not block:
                        continue
                    downloaded += len(block)
                    if downloaded > maximum:
                        raise ValueError(
                            f"PDF exceeds {self.config.max_pdf_mb} MB limit: {url}"
                        )
                    output.write(block)
            with temporary.open("rb") as header:
                if header.read(4) != b"%PDF":
                    raise ValueError(f"Downloaded content is not a PDF: {url}")
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        finally:
            response.close()
        return destination

    @staticmethod
    def extract_file(path: Path, source_url: str) -> list[dict]:
        """Extract one record per non-empty page while preserving page numbers."""

        pages: list[dict] = []
        with pymupdf.open(path) as document:
            pdf_title = str(document.metadata.get("title") or "").strip()
            title = pdf_title or path.stem.split("-", 1)[-1].replace("-", " ")
            category = classify_category(source_url, title)
            department = detect_department(source_url, title)
            for page_number, page in enumerate(document, start=1):
                text = page.get_text("text", sort=True).strip()
                if not text:
                    continue
                pages.append(
                    {
                        "title": title,
                        "text": text,
                        "source_url": source_url,
                        "document_type": "pdf",
                        "department": department,
                        "page": page_number,
                        "category": category,
                        "local_path": str(path),
                    }
                )
        return pages

    def load_many(self, urls: Iterable[str]) -> dict:
        started_count = 0
        all_pages: list[dict] = []
        manifest: list[dict] = []
        for url in urls:
            try:
                path = self.download(url)
                pages = self.extract_file(path, url)
                all_pages.extend(pages)
                manifest.append(
                    {"url": url, "path": str(path), "pages": len(pages),
                     "status": "ok" if pages else "no_text"}
                )
                started_count += 1
            except (requests.RequestException, ValueError, OSError, pymupdf.FileDataError) as exc:
                LOGGER.warning("Skipping PDF %s: %s", url, exc)
                manifest.append({"url": url, "status": "error", "error": str(exc)})
        result = {
            "documents": all_pages,
            "manifest": manifest,
            "stats": {"pdfs": started_count, "pages": len(all_pages)},
        }
        save_json(self.config.raw_dir / "pdf_pages.json", result)
        return result
