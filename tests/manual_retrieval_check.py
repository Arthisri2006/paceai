"""Run production retrieval acceptance questions without invoking the LLM."""

from __future__ import annotations

from src.bm25_search import BM25Search
from src.embeddings import EmbeddingModel
from src.retriever import HybridRetriever
from src.rag_pipeline import has_sufficient_evidence
from src.vector_store import VectorStore
from config import settings
from src.utils import save_json


QUESTIONS = (
    "What courses are offered at PACE?",
    "What is the CSE R23 syllabus?",
    "What departments are available?",
    "What placement services are offered?",
    "What hostel facilities are available?",
    "Where can I find academic regulations?",
    "What is available under student services?",
    "What previous question papers are available?",
    "What information is available about admissions?",
    "What facilities are available on campus?",
    "Who won the FIFA World Cup in 2030?",
)


def main() -> None:
    retriever = HybridRetriever(
        VectorStore(EmbeddingModel()),
        BM25Search(),
    )
    report: list[dict] = []
    for question in QUESTIONS:
        response = retriever.search(question)
        eligible = [
            result
            for result in response["results"]
            if has_sufficient_evidence(result)
        ]
        print(f"\nQ: {question}")
        print(f"Retrieval seconds: {response['timing']['retrieval_seconds']}")
        print(f"Chunks allowed through evidence gate: {len(eligible)}")
        for result in response["results"][:3]:
            chunk = result["chunk"]
            print(
                f"{result['final_score']:.3f} | vector={result['vector_score']:.3f} "
                f"| lexical={result['reranker_score']:.3f} | {chunk['title']} "
                f"| page={chunk.get('page')} | {chunk['source_url']}"
            )
        report.append(
            {
                "question": question,
                "retrieval_seconds": response["timing"]["retrieval_seconds"],
                "eligible_count": len(eligible),
                "answerable": bool(eligible),
                "results": [
                    {
                        "final_score": round(result["final_score"], 4),
                        "vector_score": round(result["vector_score"], 4),
                        "lexical_score": round(result["reranker_score"], 4),
                        "title": result["chunk"]["title"],
                        "url": result["chunk"]["source_url"],
                        "page": result["chunk"].get("page"),
                    }
                    for result in response["results"][:3]
                ],
            }
        )
    save_json(settings.index_dir / "retrieval_acceptance.json", report)


if __name__ == "__main__":
    main()
