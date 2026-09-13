"""Polite, bounded crawler for public pages on pace.ac.in."""

from __future__ import annotations

import heapq
import itertools
import logging
import time
from dataclasses import dataclass
from typing import Callable
from urllib import robotparser

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import Settings, settings
from src.public_http import public_get
from src.utils import (
    PRIORITY_TERMS,
    classify_category,
    detect_department,
    is_pdf_url,
    normalize_url,
    save_json,
)

LOGGER = logging.getLogger(__name__)


@dataclass
class CrawlStats:
    pages: int = 0
    pdf_links: int = 0
    skipped: int = 0
    errors: int = 0
    elapsed_seconds: float = 0.0


class PaceCrawler:
    """Crawl only public PACE pages and save structured JSON records."""

    def __init__(
        self,
        config: Settings = settings,
        *,
        session: requests.Session | None = None,
        respect_robots: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.session = session or self._make_session()
        self.respect_robots = respect_robots
        self.sleep = sleep
        self._robots = self._load_robots() if respect_robots else None
        self._last_request_at = 0.0

    def _make_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=2,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "HEAD"),
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.headers.update(
            {"User-Agent": self.config.user_agent, "Accept": "text/html,application/pdf"}
        )
        return session

    def _load_robots(self) -> robotparser.RobotFileParser | None:
        robots_url = normalize_url("/robots.txt", self.config.base_url)
        parser = robotparser.RobotFileParser()
        parser.set_url(robots_url or f"{self.config.base_url.rstrip('/')}/robots.txt")
        try:
            response = public_get(self.session, parser.url, timeout=self.config.request_timeout)
            try:
                if response.status_code == 200:
                    parser.parse(response.text.splitlines())
                    return parser
                LOGGER.warning("robots.txt returned HTTP %s; continuing cautiously", response.status_code)
            finally:
                response.close()
        except requests.RequestException as exc:
            LOGGER.warning("Could not read robots.txt: %s", exc)
        return None

    def _allowed(self, url: str) -> bool:
        return self._robots is None or self._robots.can_fetch(self.config.user_agent, url)

    def _wait_for_slot(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.config.request_delay - elapsed
        if self._last_request_at and remaining > 0:
            self.sleep(remaining)

    def _get(self, url: str) -> requests.Response:
        self._wait_for_slot()
        response = public_get(self.session, url, timeout=self.config.request_timeout)
        self._last_request_at = time.monotonic()
        try:
            response.raise_for_status()
        except requests.RequestException:
            response.close()
            raise
        return response

    @staticmethod
    def _priority(url: str, anchor_text: str, depth: int) -> int:
        searchable = f"{url} {anchor_text}".lower()
        preferred = sum(term in searchable for term in PRIORITY_TERMS)
        return depth * 100 - preferred * 10

    @staticmethod
    def _pdf_priority(url: str) -> tuple[int, str]:
        """Prefer high-value student documents over repetitive event evidence PDFs."""

        text = url.lower().replace("_", " ").replace("-", " ")
        weights = {
            "r23": 120,
            "r21": 110,
            "regulation": 100,
            "syllabus": 95,
            "curriculum": 90,
            "question paper": 85,
            "academic calendar": 80,
            "student handbook": 70,
            "admission": 60,
            "placement": 55,
            "hostel": 55,
            "course": 45,
            "policy": 30,
            "2025": 15,
            "2024": 10,
        }
        penalties = {
            "feedback": 35,
            "achievement": 30,
            "internship": 25,
            "industrial interaction": 20,
        }
        score = sum(weight for term, weight in weights.items() if term in text)
        score -= sum(weight for term, weight in penalties.items() if term in text)
        return (-score, url)

    @staticmethod
    def _extract_page(url: str, html: str) -> tuple[dict, list[tuple[str, str]]]:
        soup = BeautifulSoup(html, "html.parser")
        links = [
            (anchor.get("href", ""), anchor.get_text(" ", strip=True))
            for anchor in soup.find_all("a", href=True)
        ]
        title = soup.title.get_text(" ", strip=True) if soup.title else url
        headings = [
            heading.get_text(" ", strip=True)
            for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
            if heading.get_text(" ", strip=True)
        ]
        if title.strip().lower() in {"pace", "home", "pace home"} and headings:
            title = headings[0]
        for tag in soup.select(
            "script, style, noscript, svg, canvas, iframe, form, nav, header, footer, aside"
        ):
            tag.decompose()
        content_root = soup.find("main") or soup.find("article") or soup.body or soup
        text = "\n".join(content_root.stripped_strings)
        record = {
            "url": url,
            "title": title,
            "headings": headings,
            "text": text,
            "category": classify_category(url, title, " ".join(headings)),
            "department": detect_department(url, title, " ".join(headings)),
            "document_type": "webpage",
        }
        return record, links

    def crawl(self) -> dict:
        """Run a bounded priority crawl and persist pages plus discovered PDFs."""

        started = time.perf_counter()
        start_url = normalize_url(self.config.base_url, self.config.base_url)
        if not start_url:
            raise ValueError(f"Invalid PACE base URL: {self.config.base_url}")

        queue: list[tuple[int, int, int, str]] = []
        sequence = itertools.count()
        heapq.heappush(queue, (0, next(sequence), 0, start_url))
        queued = {start_url}
        visited: set[str] = set()
        pdf_urls: set[str] = set()
        pages: list[dict] = []
        stats = CrawlStats()

        while queue and len(pages) < self.config.max_pages:
            _, _, depth, url = heapq.heappop(queue)
            if url in visited:
                continue
            visited.add(url)
            if not self._allowed(url):
                stats.skipped += 1
                continue
            response = None
            try:
                response = self._get(url)
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" not in content_type:
                    stats.skipped += 1
                    continue
                final_url = getattr(response, "url", None) or url
                page, links = self._extract_page(final_url, response.text)
                if len(page["text"].split()) < 20:
                    stats.skipped += 1
                else:
                    page["depth"] = depth
                    pages.append(page)
                if depth >= self.config.max_depth:
                    continue
                for raw_link, anchor_text in links:
                    normalized = normalize_url(raw_link, final_url)
                    if not normalized:
                        continue
                    if is_pdf_url(normalized):
                        pdf_urls.add(normalized)
                        continue
                    if normalized not in queued:
                        queued.add(normalized)
                        heapq.heappush(
                            queue,
                            (
                                self._priority(normalized, anchor_text, depth + 1),
                                next(sequence),
                                depth + 1,
                                normalized,
                            ),
                        )
            except requests.RequestException as exc:
                stats.errors += 1
                LOGGER.warning("Skipping %s: %s", url, exc)
            finally:
                if response is not None:
                    response.close()

        # Keep the most academically relevant PDFs if the site exposes more than
        # the configured limit. This avoids early navigation order deciding value.
        selected_pdfs = sorted(
            pdf_urls, key=self._pdf_priority
        )[: self.config.max_pdfs]
        stats.pages = len(pages)
        stats.pdf_links = len(selected_pdfs)
        stats.elapsed_seconds = round(time.perf_counter() - started, 3)
        result = {
            "pages": pages,
            "pdf_urls": selected_pdfs,
            "stats": stats.__dict__,
        }
        save_json(self.config.raw_dir / "crawl.json", result)
        return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    settings.ensure_directories()
    outcome = PaceCrawler().crawl()
    print(outcome["stats"])
