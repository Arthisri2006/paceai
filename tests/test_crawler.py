from __future__ import annotations

from dataclasses import replace

import requests

from config import settings
from src.crawler import PaceCrawler
from src.utils import normalize_url


class FakeResponse:
    def __init__(self, html: str, content_type: str = "text/html") -> None:
        self.text = html
        self.headers = {"Content-Type": content_type}
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def close(self) -> None:
        pass


class FakeSession:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    def get(self, url: str, timeout: int, **kwargs) -> FakeResponse:
        assert kwargs["allow_redirects"] is False
        if url not in self.pages:
            raise requests.RequestException(f"Unexpected URL: {url}")
        return FakeResponse(self.pages[url])


def test_normalize_url_removes_queries_and_rejects_external_assets() -> None:
    assert normalize_url("/academics/?ref=menu#top", "https://pace.ac.in/") == (
        "https://pace.ac.in/academics"
    )
    assert normalize_url("https://example.com/page", "https://pace.ac.in/") is None
    assert normalize_url("/images/logo.png", "https://pace.ac.in/") is None


def test_crawler_deduplicates_and_finds_pdfs(tmp_path) -> None:
    home = "https://pace.ac.in/"
    academics = "https://pace.ac.in/academics"
    fake_pages = {
        home: """
            <html><head><title>PACE Home</title></head><body>
            <nav>Repeated menu</nav><main><h1>Welcome to PACE</h1>
            <p>This is meaningful public campus information for students and visitors.</p>
            <p>PACE provides academic programmes, facilities, and student support services.</p>
            <a href='/academics?from=home'>Academics</a>
            <a href='/academics#again'>Duplicate</a>
            <a href='/docs/r23.pdf'>R23 syllabus</a>
            <a href='https://outside.example/page'>Outside</a></main></body></html>
        """,
        academics: """
            <html><head><title>Academics</title></head><body><main>
            <h1>Academic programmes</h1>
            <p>Students can find curriculum, syllabus, regulations, calendars, and courses.</p>
            <p>Departments publish official programme information on these public pages.</p>
            </main></body></html>
        """,
    }
    test_settings = replace(
        settings,
        max_pages=5,
        max_depth=2,
        request_delay=0,
        raw_dir=tmp_path / "raw",
    )
    crawler = PaceCrawler(
        test_settings,
        session=FakeSession(fake_pages),
        respect_robots=False,
        sleep=lambda _: None,
    )

    result = crawler.crawl()

    assert result["stats"]["pages"] == 2
    assert result["pdf_urls"] == ["https://pace.ac.in/docs/r23.pdf"]
    assert result["pages"][1]["category"] == "academics"
    assert (tmp_path / "raw" / "crawl.json").exists()


def test_pdf_priority_prefers_regulations_over_event_evidence() -> None:
    urls = [
        "https://pace.ac.in/files/2024-student-achievement.pdf",
        "https://pace.ac.in/files/cse-r23-regulations.pdf",
        "https://pace.ac.in/files/industrial-interaction.pdf",
    ]
    assert sorted(urls, key=PaceCrawler._pdf_priority)[0].endswith(
        "cse-r23-regulations.pdf"
    )
