"""Live acceptance checks; Gemini questions incur normal provider usage."""

from config import settings
from src.runtime import load_pipeline
from src.utils import save_json


def main():
    pipeline = load_pipeline()
    report = []
    for question in (
        "Hi",
        "tell me the syllabus of aiml in r23 regulation",
        "What is the AIML R99 syllabus?",
        "What placement services are offered?",
    ):
        result = pipeline.ask(question)
        print("QUESTION:", question)
        print("ANSWER:", result["answer"])
        print("TIMING:", result["timing"])
        if question == "Hi":
            assert not result["sources"]
            assert result["timing"]["answer_mode"] == "conversation"
        elif "r23" in question:
            assert result["sources"]
            assert {s["title"] for s in result["sources"]} == {"AIML_R23"}
            assert "BOSS" not in result["answer"]
            assert "partial overview" in result["answer"]
        elif "R99" in question:
            assert not result["sources"]
            assert result["timing"]["answer_mode"] == "not_found"
        else:
            assert result["timing"]["answer_mode"] == "gemini"
            assert result["sources"]
        report.append({"question": question, "answer": result["answer"],
                       "sources": result["sources"], "timing": result["timing"]})
    save_json(settings.index_dir / "gemini_acceptance.json", report)


if __name__ == "__main__":
    main()
