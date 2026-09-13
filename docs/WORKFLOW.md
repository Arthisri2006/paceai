# PACE AI — System Workflows & Operational Lifecycles

This guide documents the end-to-end operational lifecycles of PACE AI, from initial repository installation to offline knowledge indexing, query resolution across three distinct answering pathways, candidate activation, and non-destructive index rollback.

---

## 1. The 15-Stage System Lifecycle

The entire operational existence of PACE AI is divided into 15 discrete, reproducible stages:

```mermaid
flowchart TD
    subgraph Phase1["Phase 1: Environment & Setup"]
        S1["1. Initial Installation<br>(Python 3.11, .venv, pip install)"] --> S2["2. Environment Configuration<br>(.env.example -> .env, Gemini Key)"]
    end

    subgraph Phase2["Phase 2: Offline Knowledge Ingestion"]
        S2 --> S3["3. Building the Knowledge Base<br>(PaceCrawler: Webpages & PDFs)"]
        S3 --> S4["4. Token-Aware Chunking<br>(TokenDocumentChunker: 448 token limit)"]
        S4 --> S5["5. Embedding & FAISS Build<br>(BGE-small-en-v1.5, IndexFlatIP)"]
        S5 --> S6["6. BM25 Corpus Construction<br>(BM25Okapi inverted index)"]
    end

    subgraph Phase3["Phase 3: Candidate Validation & Activation"]
        S6 --> S7["7. Candidate Evaluation<br>(evaluate_token_index.py: 17 gold cases)"]
        S7 --> S8["8. Index Activation<br>(select_index.py --candidate -> active.json)"]
    end

    subgraph Phase4["Phase 4: Runtime Query Resolution"]
        S8 --> S9["9. Starting Streamlit UI<br>(streamlit run app.py / start.ps1)"]
        S9 --> S10["10. Student Asks Question<br>(Input validation: 1-1500 chars)"]
        S10 --> S11["11. Retrieving Evidence<br>(Cache -> Scope -> FAISS + BM25 -> Rerank)"]
        S11 --> S12["12. Calling Gemini<br>(Guarded SSE Stream via REST API)"]
        S12 --> S13["13. Displaying Citations<br>(Spotlight Source Cards with page links)"]
    end

    subgraph Phase5["Phase 5: Maintenance & Governance"]
        S13 -.-> S14["14. Rolling Back an Index<br>(select_index.py --rollback)"]
        S13 -.-> S15["15. Updating the System Safely<br>(Isolated candidate build without modifying active)"]
    end
```

### Stage Details

1. **Initial Installation**: Developer clones the repository, provisions a clean Python 3.11 virtual environment (`.venv`), and installs pinned dependencies from `requirements.txt`.
2. **Environment Configuration**: Copies `.env.example` to `.env`. Adds `GEMINI_API_KEY` while keeping `.env` excluded from version control.
3. **Building the Knowledge Base**: `PaceCrawler` executes a polite, bounded crawl of `https://pace.ac.in/`, writing `data/raw/crawl.json`. `PacePdfLoader` downloads linked academic PDFs into `data/raw/pdfs/` and extracts page text via PyMuPDF into `data/raw/pdf_pages.json`.
4. **Token-Aware Chunk Generation**: `TextCleaner` eliminates cross-document repetitive boilerplate. `TokenDocumentChunker` splits pages budgeted against the *complete embedding input* (metadata + content <= 448 tokens) without splitting individual course table rows or losing semester headings.
5. **Embedding & FAISS Generation**: `EmbeddingModel` encodes chunks into 384-dimensional dense vectors using `BAAI/bge-small-en-v1.5`. Vectors are L2-normalized and stored in a FAISS `IndexFlatIP` (`vectors.faiss`).
6. **BM25 Construction**: `BM25Search` tokenizes chunks with field boosts (title x4, URL x4, department x3) and persists the inverted index to `bm25_corpus.json`.
7. **Candidate Evaluation**: `tests/evaluate_token_index.py` executes 17 curated gold acceptance cases against the new index snapshot in `data/candidates/<candidate-name>/`. Verifies zero oversized chunks and zero regressions against baseline.
8. **Index Activation**: `select_index.py --candidate <path>` records the verified candidate path and SHA-256 digests in `data/index/active.json`.
9. **Starting Streamlit**: Launches the web assistant using `streamlit run app.py` or `.\start.ps1`, binding to `127.0.0.1`.
10. **Asking a Question**: Student enters a question via the chat input (capped at 1,500 characters).
11. **Retrieving Evidence**: RAG pipeline checks retrieval cache -> filters by academic branch/regulation scope -> queries FAISS and BM25 -> fuses scores -> reranks lexically -> enforces evidence thresholds.
12. **Calling Gemini**: If evidence is sufficient and no shortcut applies, streams the prompt to Gemini REST API over HTTPS SSE using `gemini-3.5-flash` with minimal reasoning.
13. **Displaying Citations**: Renders streaming answer in Streamlit. Validates `[S1]`, `[S2]` citation tags and displays official clickable PACE source cards with PDF page numbers.
14. **Rolling Back an Index**: If an issue is discovered in the active candidate, `python select_index.py --rollback` atomically restores the untouched baseline index without data loss.
15. **Updating the System Safely**: New web crawls and PDF updates are always built in isolated candidate folders (`data/candidates/`), thoroughly tested, and promoted only after passing all safety gates.

---

## 2. The Three Answer Pathways

To optimize responsiveness, eliminate unnecessary API costs, and prevent hallucinations on structured data, PACE AI routes student inquiries through three distinct pathways:

```mermaid
stateDiagram-v2
    [*] --> QuestionReceived: Student submits question
    QuestionReceived --> CheckGreeting: Validate input (1-1500 chars)

    state CheckGreeting {
        [*] --> ConversationalMatch
        ConversationalMatch --> Path1_Greeting: Matches "hi", "hello", "thanks", "help"
        ConversationalMatch --> CheckOverview: No match
    }

    state Path1_Greeting {
        [*] --> InstantReply: conversational_reply()
        InstantReply --> RenderResponse: Zero retrieval, Zero LLM
    }

    state CheckOverview {
        [*] --> QueryAnalysis: parse_academic_query()
        QueryAnalysis --> Path2_Overview: Single branch + regulation + syllabus overview
        QueryAnalysis --> Path3_HybridRAG: Complex question or specific topic
    }

    state Path2_Overview {
        [*] --> TableExtraction: course_structure_excerpt()
        TableExtraction --> DirectReply: Format subject rows + PDF card
        DirectReply --> RenderResponse: Zero LLM
    }

    state Path3_HybridRAG {
        [*] --> RetrievalStage: Cache check -> FAISS + BM25 -> Rerank
        RetrievalStage --> EvidenceGate: has_sufficient_evidence()
        
        EvidenceGate --> RefusalPath: Evidence < Thresholds
        RefusalPath --> NotFoundMessage: "I could not find this information..."
        NotFoundMessage --> RenderResponse: Zero LLM
        
        EvidenceGate --> LLMGeneration: Evidence >= Thresholds
        LLMGeneration --> StreamTokens: REST SSE to Gemini
        StreamTokens --> SentenceGuard: guarded_text()
        SentenceGuard --> CitationCheck: Validate [S1] labels
        CitationCheck --> RenderResponse: Generated answer + Source cards
    }

    RenderResponse --> [*]
```

### Deep Dive: When Gemini Is NOT Called

A critical design feature of PACE AI is that Gemini is invoked **only when necessary**. Specifically, Gemini is **never** called in the following scenarios:

| Scenario | Trigger Condition | Code Handler | Action Taken | Why Gemini is Skipped |
| :--- | :--- | :--- | :--- | :--- |
| **Conversational Greeting** | Questions matching `"hi"`, `"hello"`, `"good morning"`, `"thanks"`, `"what can you do"` | `conversational_reply()` in [`src/answer_policy.py`](file:///C:/Users/Purna/OneDrive/Desktop/PACE%20AI/pace-ai-assistant/src/answer_policy.py) | Returns friendly institutional greeting immediately. | Avoids wasting API quota and 1-2 seconds of latency on trivial chit-chat. |
| **Course Catalogue Overview** | Broad query such as `"What courses are offered at PACE?"` | `_direct_answer()` in [`src/rag_pipeline.py`](file:///C:/Users/Purna/OneDrive/Desktop/PACE%20AI/pace-ai-assistant/src/rag_pipeline.py) | Directs student to official Courses Offered page URL. | Course catalogues are too extensive for 80-word LLM answers; direct link is authoritative. |
| **Syllabus Overview** | Unambiguous request for 1 branch & 1 regulation syllabus (e.g., `"tell me the syllabus of aiml in r23 regulation"`) | `_overview_pages()` + `course_structure_excerpt()` in [`src/retriever.py`](file:///C:/Users/Purna/OneDrive/Desktop/PACE%20AI/pace-ai-assistant/src/retriever.py) | Parses numbered course structure table rows directly from PDF text. | Regex-parsed tables are 100% accurate; LLMs tend to drop course codes or hallucinate electives. |
| **Insufficient Retrieval Evidence** | Best chunk scores < 0.35 final score, or vector < 0.58 and lexical < 0.25 | `has_sufficient_evidence()` in [`src/rag_pipeline.py`](file:///C:/Users/Purna/OneDrive/Desktop/PACE%20AI/pace-ai-assistant/src/rag_pipeline.py) | Yields `NOT_FOUND` refusal message (`"I could not find this information in the indexed PACE sources."`). | Enforces strict hallucination guard; if PACE documents lack evidence, the LLM must not guess. |
| **Out-of-Scope Regulations** | Queries asking for nonexistent regulations (e.g., `"AIML R99 syllabus"`) | `_academic_scope()` in [`src/retriever.py`](file:///C:/Users/Purna/OneDrive/Desktop/PACE%20AI/pace-ai-assistant/src/retriever.py) | Returns empty allowed set -> immediate refusal. | Prevents confusing outdated or futuristic regulations with current curricula. |

---

## 3. Grounded RAG Generation Flow (Path 3)

When a factual campus question passes the evidence gate, the complete generation cycle executes as follows:

```mermaid
sequenceDiagram
    participant P as RagPipeline
    participant G as GeminiLLM
    participant API as Google AI Studio REST
    participant V as guarded_text()
    participant UI as Streamlit UI

    P->>P: Format JSON Context (<900 words, [S1], [S2] tags)
    P->>G: stream_with_usage(prompt, telemetry)
    G->>API: POST https://generativelanguage.googleapis.com/...:streamGenerateContent?alt=sse
    Note over G,API: Header: x-goog-api-key: [KEY] (Never in URL)
    
    loop Server-Sent Events (SSE)
        API-->>G: data: {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}
        G-->>V: Yield raw text token
        V->>V: Buffer tokens into complete sentences
        V->>V: Check for phrase repetition (3x loop detection)
        V-->>P: Yield verified sentence / token
        P-->>UI: Event: {"type": "token", "text": "..."}
        UI-->>UI: Render markdown (throttled at max 10 FPS)
    end

    API-->>G: data: {"usageMetadata": {"promptTokenCount": 350, "candidatesTokenCount": 65}}
    API-->>G: data: [DONE]
    
    P->>P: Check citations: Regex \bS\d+\b in generated text
    alt Valid Citations (e.g., [S1], [S2])
        P-->>UI: Event: {"type": "complete", "sources": [...], "timing": {...}}
        UI-->>UI: Render official Spotlight Source Cards
    else Missing or Hallucinated Citation (e.g., [S9])
        P-->>UI: Event: {"type": "replace", "text": "I couldn't produce a reliable answer..."}
        UI-->>UI: Display quality fallback (Sources suppressed)
    end
```

---

## 4. Rollback & Update Lifecycle

PACE AI prevents index corruption and deployment outages using an immutable snapshot pointer model:

```mermaid
sequenceDiagram
    actor Admin as System Administrator
    participant SI as select_index.py
    participant IS as src/index_selection.py
    participant Active as data/index/active.json
    participant Cand as data/candidates/token-448-20260912-v3/
    participant Base as data/index/ (Baseline)
    participant App as Running Streamlit App

    Note over Admin,Cand: New Candidate Built & Evaluated
    Admin->>SI: python select_index.py --candidate data/candidates/token-448-20260912-v3
    SI->>IS: activate(candidate)
    IS->>Cand: Verify evaluation.json (passed gate, 0 oversized)
    IS->>Cand: Calculate SHA256 of vectors.faiss, bm25_corpus.json, status.json, records
    IS->>Cand: Compare against tested_sha256 in evaluation.json
    IS->>Active: Write new pointer & SHA-256 hashes
    Note over Active: active.json updated atomically
    
    App->>Active: Next query checks active.json selection
    App->>Cand: Verifies SHA-256 hashes and loads candidate

    opt Rollback Required (Regression or Issue Detected)
        Admin->>SI: python select_index.py --rollback
        SI->>IS: rollback()
        IS->>Active: Overwrite active.json with {"path": "."}
        Note over Active: Reverts immediately to baseline index
        App->>Base: Reloads untouched original index files
    end
```

By decoupling candidate creation from activation, PACE AI ensures that the running application is never left in an inconsistent or partially written state.
