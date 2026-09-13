# Token-aware retrieval follow-up

## Outcome

Implemented and activated a separately evaluated index without changing Gemini,
the PACE branding, or UI layout. The original index is retained for rollback.

| Check | Original | Active candidate |
|---|---:|---:|
| Chunks | 3,227 | 5,835 |
| Inputs exceeding model's 512-token window | 952 | 0 |
| Maximum candidate embedding input | — | 448 tokens including metadata/special tokens |
| Curated retrieval checks | 17/17 | 17/17 |
| Automated tests | 78 at original audit | 89 passed in 31.22s |

The larger corpus reflects both smaller chunks and retained cross-document/page
provenance. No new web crawl occurred; the source refresh date remains September 8.
The test set covers branch/regulation overviews, detailed English/Chemistry/Math
syllabus evidence, placements, hostel, admissions, campus, course navigation, a
missing regulation and an unrelated question. Expected URL/page/terms were checked
against saved source records. Checks require evidence in prepared context, strict
PDF scope and preservation of existing exact-syllabus paths. This is a small,
curated regression set, not proof of broad answer accuracy or malicious-input safety.

## Changes

- `src/embedding_text.py`: one canonical representation shared by vector embedding
  and token counting; prevents metadata budget drift.
- `src/token_chunker.py`: counts the actual tokenizer output for complete inputs,
  caps at min(configured 448, model window), preserves whole lines/course rows when
  they fit, carries course/semester headings, and splits oversized lines without
  dropping their tail. Default overlap 48 tokens, bounded to whole lines; legacy
  word chunker remains available for historical comparison/tests.
- `src/chunker.py`: shared chunk metadata/provenance emission with overridable
  document splitting. `config.py`/`.env.example`: token budget/overlap controls.
- `src/embeddings.py`: fail before inference if any document input would truncate.
- `build_index.py`: new builds use token chunks; exact, case-sensitive content,
  provenance, metadata/model/schema fingerprint; refuses to overwrite rollback
  index once an active selection marker exists.
- `src/retriever.py`/`src/rag_pipeline.py`: exact syllabus navigation gathers parsed
  rows from all chunks on each selected page. Two-source limits no longer discard
  the rest of a page just because it was split. Detailed questions retain hybrid
  retrieval; combined overview rows are not fed into oversized embeddings.
- `src/index_selection.py`/`select_index.py`: tested local candidate gate,
  checksummed files and an atomic small selection pointer. Changed files since
  evaluation cannot be activated. Original files are never overwritten on selection.
- `src/runtime.py`/`src/ui.py`: selected snapshot consistency and checksum checks
  on load, backend/retrieval caches keyed by selection, library counts follow active
  snapshot. Existing requests retain their previous immutable pipeline.
- `tests/retrieval_cases.json` and `tests/evaluate_token_index.py`: reproducible
  isolated build/comparison, optional exact-input vector reuse, promotion gate and
  artifact hashes. No Gemini calls during evaluation.
- `tests/test_token_chunker.py`, `tests/test_index_selection.py`: input limits,
  text/row/provenance preservation, metadata rejection, embedding fail-fast,
  source-page overview coverage, snapshot corruption, gate, path containment,
  incomplete publication and non-destructive rollback tests.
- `.gitignore`, README, project notes and original audit updated for generated
  candidates and the new operational workflow.

## Evidence and validation

Active files: `data/candidates/token-448-20260912-v3`.
Detailed comparison: that directory's `evaluation.json`.
Selection manifest: `data/index/active.json`.

The initial candidate passed evidence checks but risked losing no-LLM syllabus
navigation because headings could be separated. The revised candidate preserves
headings and the evaluator checks fast-path regressions. A further page-aggregation
test ensures all parseable rows on the selected pages survive chunk splitting.

Candidate clean/chunk stage measured 86.072s. Its revised index build took 33.588s
by embedding only 149 changed unique inputs and reusing exact-input vectors from
the previously built local candidate. This is not a full rebuild speed claim;
the initial candidate required 4,316 new unique embeddings. No generation-model
download, embedding API, package install, credential edit or paid call was needed
for those builds. The intermediate candidate directories remain local and ignored.

Active vector file: 8,962,605 bytes; vector metadata: 8,971,095 bytes;
BM25 corpus: 28,359,272 bytes. More chunks require more disk/RAM and can increase
uncached search work. No general latency reduction is claimed.

Commands validated with bundled Python 3.11 and installed project dependencies:

```text
python -m pytest -q --tb=short
  89 passed in 31.22s
python -m compileall -q app.py ask.py build_index.py select_index.py config.py src tests
  passed
python -m pip check
  No broken requirements found
python -m tests.evaluate_token_index --output data/candidates/token-448-20260912-v3 --evaluate-only
  17/17 baseline and candidate; zero regressions; zero oversized inputs
python select_index.py --candidate data/candidates/token-448-20260912-v3
  activated; original files retained
python -m tests.manual_fix_check
  greeting, AIML R23, missing R99 and real Gemini placement answer passed
```

Live active-index results: AIML R23 direct answer 0.0169s, no Gemini call, source
pages 2/3 and the same four-semester partial overview. Placement answer: 20.4591s
cold retrieval, 4.4861s Gemini, 24.9458s pipeline total; 1,797 prompt tokens, 82 output,
1,879 total, STOP finish. These are observed runs, not guarantees or statistically
paired speed comparisons. The first semantic question still pays model-load cost.

New server: [PACE AI on localhost 8503](http://127.0.0.1:8503/).
HTTP `/_stcore/health` returned 200 `ok`. Automated UI tests passed; the UI design
was not modified. Older server processes may still hold older imported code;
use the new URL or restart them before relying on the new selection behavior.

## Operations and limits

Rollback: `python select_index.py --rollback`. This updates only the selection
pointer. It does not delete either index. New requests in the updated app use
the selected revision; restart after Python/configuration changes.

For another candidate, use a new directory with `tests.evaluate_token_index`,
then `select_index.py --candidate ...` only after its gate passes. Do not edit
selected index files. Checksums detect disk-file changes during fresh loading;
they are not an access-control mechanism against someone who can rewrite both
files and manifest. Local filesystem permissions still matter.

The evaluation reference remains the original baseline, not an automatically
updated best model. Broaden and version gold labels before tuning future releases.
Fresh crawling, conditional PDF updates, OCR, lowercase IT/ambiguous branch parsing,
further intent qualification, first-question warmup and bounded chat history remain
follow-ups. The user must rotate the key previously shared in chat; no key was
changed or exposed by this work.
