"""Small reusable helpers shared by the ingestion and retrieval pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit


PACE_HOSTS = {"pace.ac.in", "www.pace.ac.in"}
IGNORED_EXTENSIONS = {
    ".7z", ".avi", ".css", ".doc", ".docx", ".gif", ".ico", ".jpeg",
    ".jpg", ".js", ".json", ".mkv", ".mov", ".mp3", ".mp4", ".png",
    ".ppt", ".pptx", ".rar", ".svg", ".tar", ".ttf", ".wav", ".webm",
    ".webp", ".woff", ".woff2", ".xls", ".xlsx", ".xml", ".zip",
}
PRIORITY_TERMS = (
    "academic", "department", "curriculum", "syllabus", "regulation",
    "calendar", "placement", "training", "admission", "facilit", "hostel",
    "examination", "student", "committee", "research", "course", "college",
)
DEPARTMENT_PATTERNS = {
    "Civil Engineering": ("civil",),
    "Electrical and Electronics Engineering": ("eee", "electrical"),
    "Mechanical Engineering": ("mech", "mechanical"),
    "Electronics and Communication Engineering": ("ece", "electronics"),
    "Computer Science and Engineering": ("cse", "computer science"),
    "Information Technology": ("information technology", "\bit\b"),
    "Artificial Intelligence and Data Science": ("ai & ds", "ai and ds", "data science"),
    "Artificial Intelligence and Machine Learning": ("ai & ml", "ai and ml", "machine learning"),
    "MBA": ("\bmba\b", "business administration"),
    "Humanities and Sciences": ("humanities", "h&s"),
}
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does",
    "for", "from", "how", "i", "in", "is", "it", "me", "of", "on", "or",
    "that", "the", "their", "there", "this", "to", "under", "was", "what",
    "when", "where", "which", "who", "will", "with", "would", "you",
}
TOKEN_NORMALIZATION = {
    "admissions": "admission",
    "courses": "course",
    "departments": "department",
    "facilities": "facility",
    "papers": "paper",
    "regulations": "regulation",
    "services": "service",
    "students": "student",
    "syllabi": "syllabus",
}


def normalize_url(url: str, base_url: str) -> str | None:
    """Return a canonical PACE URL, or None for unsupported/external links."""

    absolute = urljoin(base_url, url.strip())
    parts = urlsplit(absolute)
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or host not in PACE_HOSTS:
        return None
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    suffix = Path(path.lower()).suffix
    if suffix in IGNORED_EXTENSIONS:
        return None
    # Query strings and fragments are intentionally removed to prevent duplicates.
    return urlunsplit(("https", "pace.ac.in", path, "", ""))


def is_pdf_url(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(".pdf")


def classify_category(*values: str) -> str:
    text = " ".join(values).lower()
    category_aliases = {
        "academics": ("academic", "curriculum", "syllabus", "regulation"),
        "departments": ("department", "civil", "cse", "ece", "eee", "mech"),
        "placements": ("placement", "training", "career", "tpo"),
        "admissions": ("admission", "course", "fee"),
        "campus": ("campus", "hostel", "facility", "sports", "library"),
        "examinations": ("exam", "question paper", "result"),
        "student_services": ("student", "grievance", "welfare", "nss", "ncc"),
        "committees": ("committee", "cell", "governing body", "council"),
        "research": ("research", "patent", "publication", "innovation", "mou"),
        "institution": ("about", "vision", "mission", "accreditation", "pace"),
    }
    for category, terms in category_aliases.items():
        if any(term in text for term in terms):
            return category
    return "general"


def detect_department(*values: str) -> str | None:
    text = " ".join(values).lower()
    for department, patterns in DEPARTMENT_PATTERNS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            return department
    return None


def content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def tokenize(text: str) -> list[str]:
    """Simple shared tokenizer for BM25 and keyword-aware scoring."""

    tokens = re.findall(r"[a-z0-9]+(?:[.+#-][a-z0-9]+)*", text.lower())
    return [
        TOKEN_NORMALIZATION.get(token, token)
        for token in tokens
        if token not in STOPWORDS
    ]


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))
