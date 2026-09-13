"""Extract explicit academic constraints without confusing prose with identifiers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit


BRANCH_PATTERNS = {
    "AIML": r"\b(?:aiml|ai\s+(?:and\s+)?ml|artificial intelligence\s+(?:and\s+)?machine learning)\b",
    "AIDS": r"\b(?:aids|ai\s+(?:and\s+)?ds|artificial intelligence\s+(?:and\s+)?data science)\b",
    "CSE_IOT": r"\bcse\s+(?:iot|internet of things)\b",
    "ECE_VLSI": r"\bece\s+vlsi\b",
    "CSIT": r"\b(?:csit|computer science\s+(?:and\s+)?information technology)\b",
    "CSE": r"\b(?:cse|computer science\s+(?:and\s+)?engineering)\b",
    "ECE": r"\b(?:ece|electronics\s+(?:and\s+)?communication engineering)\b",
    "EEE": r"\b(?:eee|electrical\s+(?:and\s+)?electronics engineering)\b",
    "CIVIL": r"\bcivil(?: engineering)?\b",
    "MECH": r"\b(?:mech|mechanical(?: engineering)?)\b",
    "IT": r"\b(?:it|information technology)\b",
    "IOT": r"\biot\b",
}


def normalized(text: str) -> str:
    text = re.sub(r"\br\s*[-_ ]?\s*(\d{2})\b", r"r\1", text.lower())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def is_course_overview(question: str) -> bool:
    """Unknown qualifiers (fees, branch, year, etc.) require actual retrieval."""
    words = set(normalized(question).split())
    boilerplate = set("what which courses course are is offered offer available at in pace please tell me show list all the programs programmes does have can you about give of institute technology and sciences".split())
    return bool(words & {"course", "courses"} and words & {"offered", "offer", "available"}
                and not words - boilerplate)


def branch_ids(text: str) -> frozenset[str]:
    # Longer specializations consume their spans before generic CSE/ECE/IT.
    remaining = normalized(text)
    found = set()
    for name, pattern in BRANCH_PATTERNS.items():
        if re.search(pattern, remaining):
            found.add(name)
            remaining = re.sub(pattern, " ", remaining)
    return frozenset(found)


def regulation_ids(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"\br\d{2}\b", normalized(text)))


@dataclass(frozen=True)
class AcademicQuery:
    branches: frozenset[str]
    regulations: frozenset[str]
    syllabus: bool
    overview: bool

    @property
    def scoped(self) -> bool:
        return bool(self.branches or self.regulations)


def parse_academic_query(question: str) -> AcademicQuery:
    text = normalized(question)
    # "it" is also an English pronoun; require uppercase IT or full branch name
    # in questions (metadata titles are interpreted separately).
    branches = branch_ids(question)
    if "IT" in branches and not (re.search(r"\bIT\b", question) or "information technology" in question.lower()):
        branches = branches - {"IT"}
    regulations = regulation_ids(question)
    syllabus = bool(re.search(r"\b(?:syllabus|syllabi|curriculum|subjects)\b|course structure", text))
    residual = text
    for pattern in BRANCH_PATTERNS.values():
        residual = re.sub(pattern, " ", residual)
    residual = re.sub(r"\br\d{2}\b", " ", residual)
    # Unknown content words deliberately keep detailed questions on retrieval.
    boilerplate = set("tell me the syllabus syllabi curriculum subjects of in under regulation regulations please show give provide find get what is are can you could would want need about for at pace my available official full complete all list overview download link where i see know course structure b tech btech and".split())
    overview = syllabus and not (set(residual.split()) - boilerplate)
    return AcademicQuery(frozenset(branches), regulations, syllabus, overview)


def document_identity(chunk: dict) -> tuple[frozenset[str], frozenset[str], bool]:
    # Never infer branch or regulation from body text: syllabi mention other
    # branches and historic regulations inside otherwise unrelated documents.
    filename = unquote(urlsplit(chunk["source_url"]).path.rsplit("/", 1)[-1])
    identity = f'{chunk.get("title", "")} {filename}'
    text = normalized(identity)
    syllabus = (
        "regulations" not in text.split()
        and "feedback" not in text.split()
        and ("syllabus" in chunk["source_url"].lower() or "syllabus" in text
             or bool(chunk.get("document_type") == "pdf" and branch_ids(identity) and regulation_ids(identity)))
    )
    return branch_ids(identity), regulation_ids(identity), syllabus


def matches_document(query: AcademicQuery, chunk: dict) -> bool:
    branches, regulations, syllabus = document_identity(chunk)
    return ((not query.syllabus or syllabus)
            and (not query.branches or bool(query.branches & branches))
            and (not query.regulations or bool(query.regulations & regulations)))


def course_structure_excerpt(text: str) -> list[tuple[str, list[str]]]:
    """Read numbered PACE course-table rows; skip ambiguous wrapped rows."""
    sections = []
    heading = None
    courses: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if re.search(r"\bYear\b.*\bSemester\b", line, re.I):
            if heading and courses:
                sections.append((heading, courses))
            heading, courses = line, []
            continue
        match = re.match(r"^\d+\s+P\d{2}[A-Z]+\d+\s+(.+?)\s+(?:\d+(?:\.\d+)?|-)\s+(?:\d+(?:\.\d+)?|-)\s+(?:\d+(?:\.\d+)?|-)\s+(?:\d+(?:\.\d+)?|-)$", line)
        if heading and match:
            title = match.group(1).strip()
            if title not in courses:
                courses.append(title)
    if heading and courses:
        sections.append((heading, courses))
    return sections
