# PACE AI — Permanent Project Notes

These requirements apply throughout the project.

## Product priorities

1. Build and verify the complete backend before polishing the UI.
2. Optimize for the shortest reliable answer time.
3. Never trade source accuracy or hallucination prevention for speed.
4. Never crawl or rebuild embeddings when the chat application starts.
5. Record retrieval, generation, and total latency in debug information.
6. The user selected Gemini and supplied its API key on 2026-09-08. The local
   `.env` now selects Gemini 3.5 Flash. Keep model selection independent of UI
   changes; do not introduce other paid services without permission.

## UI direction

- Use the 21st.dev **Spotlight Card** by Jahed as the visual reference:
  https://21st.dev/@jahed/components/spotlight-card
- Do not use the previously mentioned Snitch UI.
- Apply the spotlight/glow interaction to source cards and status panels where it
  remains accessible and does not slow down answers.
- Final UI details may be refined after the backend is complete.
- The user authorized UI implementation after being notified at the backend/UI
  boundary, then supplied `C:/Users/Purna/Downloads/download.jpg` as the PACE logo.
- Use the original crest, copied unchanged into `assets/pace-logo.jpg`; do not
  redraw or invent an institutional mark.
- The initial Streamlit UI uses charcoal/green surfaces, lime accents, Spotlight
  hover effects, source cards, and a responsive chat layout. Preserve response
  streaming and deferred backend loading when refining the design.
- On 2026-09-09 the user requested a Gemini-inspired redesign with the PACE crest
  and interactive hover effects. This supersedes the previous lime/card-heavy
  layout: use a centered welcome and inline composer, blue/cyan/green PACE accents,
  simpler sidebar, right-aligned user bubbles, and borderless assistant replies.
- Keep prompt and source-card hover lift/glow, keyboard focus outlines, touch
  layouts, and reduced-motion support. Preserve original logo and existing RAG.

## Credentials

- Retrieval and embeddings stay local; Gemini receives the current question and
  retrieved public PACE excerpts. Greetings and document overviews skip the API.
- Ask the user before adding any service that requires an API key.
- Never commit `.env` files, tokens, credentials, or private data.

## Answer quality regression checks — 2026-09-08

- Match syllabus branch and regulation against document identity before ranking;
  never mix AIML R21 into an AIML R23 answer.
- Broad syllabus requests use course-structure excerpts with explicit partial
  coverage wording, not arbitrary lab instructions presented as a whole syllabus.
- Greetings bypass backend loading, retrieval, and generation; show no sources.
- Buffer generated sentences to detect repetition and drop incomplete final
  sentences. Refusals and quality fallbacks do not show supporting-source cards.
- All 41 automated tests passed. Default Gemini reasoning produced an incomplete
  response in a browser check. Use minimal reasoning for the selected 3.5 Flash
  model to reserve the token budget for the short factual answer. Retest: 2.46
  seconds total, 0.09 seconds retrieval. Greeting: <1 ms in the pipeline.
- UI timing includes first-use backend initialization; pipeline-only timing is
  recorded separately. Actual UI/network latency varies; these are not guarantees.
  The first full browser answer after restart took 19.7 seconds including imports
  and local retrieval initialization, and returned a complete cited Gemini answer.
- Run `python -m tests.manual_fix_check` for the screenshot regressions plus a
  real Gemini question (normal API usage applies).

## Startup optimization — 2026-09-09

- Load Torch, Transformers, Sentence Transformers, and optional local-generation
  downloads only when those paths are used. Gemini construction and backend
  index loading must not import these libraries.
- A broad syllabus overview can bypass semantic inference only with one explicit
  branch, one regulation, one matching document, and parsed course-table rows.
  Detailed questions, ambiguous scope, and unparsed tables retain hybrid search.
- Fresh-process AIML R23 check: backend initialization 1.11 seconds, answer 0.19
  seconds, total 1.30 seconds. No heavy AI libraries loaded and no Gemini call.
  This optimization does not remove first-use model loading for semantic questions.
- 44 automated tests passed, including prohibited eager-import checks and tests
  that detailed questions cannot take the exact-syllabus shortcut.
- Live Gemini regression passed. The first semantic placement question took
  36.99 seconds (28.08 seconds cold retrieval, 8.91 seconds Gemini). Do not
  present the 1.30-second exact-document result as general Gemini latency.

## Audited improvements — 2026-09-12

### Subsequent token-aware implementation

- The user approved starting with token-aware chunking and retrieval tests.
- Active candidate: data/candidates/token-448-20260912-v3, selected atomically by
  data/index/active.json. 5835 chunks, max 448 full-input tokens, zero over512.
- Original 3227-chunk index files remain for rollback via select_index.py --rollback.
- 17/17 curated evidence checks passed before and after; 89 automated tests passed.
  This demonstrates no regression on the measured set, not universal accuracy gain.
- Preserve complete course rows and semester/course-structure headings. Exact
  syllabus navigation merges parsed rows per page across split chunks, retaining
  the original four-semester partial overview without Gemini or embeddings.
- Model/config edits still require restart. Index selections now key backend and
  retrieval caches; checksums verified when loading. Never mutate selected files.
- Live placement generation succeeded: 1797 prompt tokens, 82 output tokens,
  4.486s Gemini; total24.946s included cold embedding load. Do not claim lower
  general latency from this change. AIML R23 direct pipeline answer:0.0169s.
- New development server runs on localhost8503. Full detail: TOKEN_CHUNKING_REPORT.md.

- Continue prioritizing answer correctness and response latency; distinguish
  first-use embedding load, warm retrieval, Gemini generation, and UI total.
- Keep Gemini + local BGE + FAISS/BM25; no new framework or generation model.
- Query cache: 128 exact, case-sensitive queries / 300 seconds per loaded index;
  retrieval only, never answer text. Restart after rebuilding or config changes.
- Download redirects must remain on official PACE hosts and standard ports; close
  responses and bound PDF bytes. Preserve source URL and page when deduplicating.
- Context labels and rendered sources share URL/page identity. Invalid or missing
  generated labels cause a transparent fallback; this is not entailment checking.
- Gemini usage telemetry contains counts and finish reason only; no key or thoughts.
- 78 tests passed; live Gemini placement request succeeded (14.83 seconds pipeline,
  including 12.26 seconds cold retrieval and 2.58 seconds Gemini). Warm-cache
  retrieval/context timings are sub-millisecond on the four-query benchmark,
  not total generated-answer latency. Detailed evidence: OPTIMIZATION_REPORT.md.
- 952/3227 embedding inputs exceed the model's 512-token window. Evaluate
  token-aware chunks before changing the live index. Source-preserving ingestion
  dry run yielded 3721 chunks; production index remains unchanged at 3227.
- Never reproduce the key previously shared in chat. Recommend user-led rotation.
