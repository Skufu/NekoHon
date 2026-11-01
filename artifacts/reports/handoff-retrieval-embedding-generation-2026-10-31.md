# Handoff — Retrieval, Embedding Provenance, and Generation Improvements

Date: 2026-10-31 / 2026-11-01. For: the next session picking up cold.
Status: **Implementation landed, verified, and benchmarked across all three books (Round 1 + Round 2 continuation on 2026-11-01).** 109 of 109 targeted unit tests pass (`test_answer`, `test_agentic`, `test_generalization`, `test_query_understanding`; full discovery 1342 of 1347 pass, 5 environmental failures from optional missing `fitz`/`tokenizers`/`onnxruntime` and empty `data/figures/`), index verification clean (1153 of 1153 vectors), reader trace regression 12/12 pass, comparisons 20/20 pass, and wide-net v2 improved from 25/48 (2.43s) -> 31/48 (3.52s) -> **39/48 (2.81s)** (+14 items net gain over baseline, +8 over Round 1, 0 previously passing items lost; trade-offs: +0.38s mean latency penalty vs 2.43s baseline and first-line quote length expansion from median 209 to 869 chars).

Read this file top to bottom before modifying retrieval or answer logic. It documents exactly what changed, what was verified, what broke before, what passed after, and the remaining 9 failure modes.

---

## 1. Executive Summary & Verification Matrix

All runtime execution stays strictly local (Ollama `127.0.0.1:11434` with default model `nekohon_q35_2b_x3_2e`). Zero cloud runtime calls.

| Suite / Benchmark | Baseline | Round 1 | Round 2 (Current) | Net Delta | Provenance / Artifact |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Targeted Unit Tests** (`test_answer`, `test_agentic`, `test_generalization`, `test_query_understanding`) | 94 / 94 pass | 103 / 104 pass | **109 / 109 pass, 0 fail** | +15 tests pass | In-process, ran in 0.18s (full suite: 1342/1347 pass, 5 env red) |
| **Index Vector Hygiene** (`verify_index.py`) | 1153 clean | 1153 / 1153 clean | **1153 / 1153 clean, 0 fail** | Stamped provenance | `data/index.sqlite` (exit 0) |
| **Search Recall @1 (Wide Net)** | 25 / 42 at rank 1 | 28 / 42 at rank 1 | **28 / 42 at rank 1** (40/42 in top 5) | +3 rank-1 items | `retrieval-recall-before.json` (`0501c848851c`) vs `retrieval-recall-after.json` (`5450cad50975`) |
| **Search Recall @1 (Reader Traces)** | 5 / 9 at rank 1 | 7 / 9 at rank 1 | **7 / 9 at rank 1** (9/9 in top 5) | +2 rank-1, +1 top-5 | `retrieval-recall-before.json` vs `retrieval-recall-after.json` |
| **Reader Trace Regression** (`trace-regression.py`) | 4 / 12 pass, 8 fail | 12 / 12 pass | **12 / 12 pass, 0 fail** | +8 pass (100%) | `trace-regression-after-2026-10-31.json` (`6956ac6bb0e6`) |
| **Comparison Matrix** (`comparison-matrix.py`) | 9 / 20 -> 20 / 20 | 20 / 20 pass | **20 / 20 pass, 0 fail** | 100% pass | `compare-after-2026-10-29.json` (`dd39d4adaf7f`) |
| **Wide-Net v2 Evaluation** (`wide_net_eval.py`) | 25 / 48 pass (2.43s) | 31 / 48 pass (3.52s) | **39 / 48 pass, 9 fail (2.81s)** | **+14 items pass** (+0.38s latency penalty vs 2.43s; median quote 209 -> 869 chars penalty) | `wide-net-v2-2026-10-31.model-nekohon_q35_2b_x3_2e.json` (`c323f3cf408b`) -> `wn2-after-all-2026-10-31.json` (`c8204e1ff7ba`) -> `wn2-after-span-2026-11-01.json` (`a3161c000e2f`) |

---

## 2. What Changed

### A. Hybrid Search & RRF Fusion (`fusion.py`, `tests/test_fusion.py`)
- **Bug fixed**: In `fusion.fuse()`, an early check `if candidate["chunk_id"] in by_id: return passages` bailed out without re-ranking whenever the #1 BM25 lexical candidate was already somewhere in the dense top 5. That prevented strong lexical matches (e.g., specific acronyms or terminology) from being promoted to rank 1.
- **Fix**: Removed the early return; lexical rank 1 now receives its reciprocal rank score `1 / (RRF_K + 1)` and merges cleanly into the final ordered passages.
- **Result**: `wn2-fde-s1` ("how do object stores serve random reads?") moved from rank 3 to rank 1 (`ch06-042`), `wn2-fde-c1` ("NAS vs SAN") moved from rank 2 to rank 1 (`ch06-030`), `wn2-ddia-s3` ("tombstones") moved from rank 2 to rank 1 (`text00011-093`), and `fde-storage-position` moved from rank 3 to rank 1 (`ch06-001`).

### B. Chunk Anchors & Section Trails (`fts_index.py`, `retrieve.py`, `readings.py`, `tests/test_fts_runtime.py`)
- **FTS schema & scoring**: Added `section` column to `chunks_fts` with BM25 weights `bm25(chunks_fts, 2.0, 1.5, 1.0)` for (heading, section, text).
- **Metadata passthrough**: Preserved `"section"` and `"anchor"` keys on passage dicts across `retrieve.py`, `readings.py`, and `fusion.py`.
- **Content fingerprint**: `fts_index.py` stores a SHA-256 fingerprint of chunk text to verify FTS index freshness without requiring full rebuilds.

### C. Embedder Provenance & Input Verification (`retrieve.py`, `verify_index.py`, `tests/test_retrieve.py`, `tests/test_verify_index.py`)
- **Functions added**: `input_sha256(text)` and `embedder_provenance(model, dims)` in `retrieve.py`.
- **Index stamping**: `embed_index()` records `"embedding_input_sha256"` on every chunk record and stamps top-level `"embedder_provenance"` (`{"model": ..., "dims": ..., "count": ...}`).
- **Verification checks**: `verify_index.py` audits two new axes: `"stale_input"` (recomputed text hash vs stored hash) and `"provenance_drift"` (stored embedder config vs runtime embedder). Verified clean (0 stale, 0 drift across 1,153 vectors).

### D. Brittle Heuristics & Canonicalization Fixes (`canonical.py`, `tests/test_canonical.py`)
- **Misspelled auxiliary questions**: `canonical.py:345` had `if len(words) >= 3 and words[0] in AUX and ...: return f"What is {q}?"`. A misspelled query like `"waht is jdbc"` or `"waht is the absoloot maximum method"` has `words[0] == "waht"` and `words[1] in ("is", "are", "do")`, which was previously getting wrapped into `"What is waht is jdbc?"`. Added `words[1] in AUX` exclusion so the typo repair downstream in `readings.py` can see the original terms cleanly.

### E. Generation, Follow-up Advancement, and Comparisons (`answer.py`, `tests/test_comparison_regression.py`)
- **Comparison patterns**: Added `r"\b(?:difference|trade-?offs?)\s+between\s+(.+?)\s+and\s+(.+?)"` to `COMPARISON_PATTERNS` and `(?:prefer|choose|favor|recommend)s?\s+(.+?)\s+over\s+(.+?)"` to `COMPARE_RE`.
- **Subject extraction**: Stripped `SIMPLIFY_RE` from `_extract_subject_from_query` so `"what is a watermark in simple words"` extracts subject `"watermark"`, and removed `SIMPLIFY_RE.search` from `_is_generic_followup` so Turn 1 questions are recognized as substantive topic anchors.
- **Example advancement**:
  - In `_advance_followup_quote()`, if candidates in `pool` differ in relevance to the follow-up subject, pool is filtered by content words of `followup_question` (`_chunk_has_subj`).
  - Raised example marker weight for dedicated walkthrough chunks (`"example" in c_head.lower() or "walkthrough" in c_head.lower(): score += 35`).
  - Passed `resolved_question or question` to `_advance_followup_quote` so Turn 2 example follow-ups ("can you give examples?") retain the resolved subject (`"Regarding watermark: can you give examples?"`).
- **Quote boundary hygiene**:
  - Gated heading replacement in `parse_answered` on `sync_first_tag` so colon lead-in sentences still reach `_expand_list`.
  - Expanded `_whole_paragraph` for backward-referring naming sentences ("This is called...") and 1-sentence topic introductions.
  - Required contrast markers or strict retry in `_comparison_body` so the model explicitly contrasts both sides rather than emitting a generic one-sided definition.
  - Added `_retry_uncited` fallback in `_plain_body` when the initial draft has empty citations.

---

## 3. Detailed Benchmark Results

### A. Trace Regression (`trace-regression.py`)
Evidence: `artifacts/runs/trace-regression-after-2026-10-31.json` (SHA-256 `6956ac6bb0e6`).
All 12 real reader conversations passed (up from 4 of 12):
1. `fde-early-2000s-repeat`: PASS (3 turns, 12.33s, cited `ch01-010`)
2. `fde-watermark-examples`: PASS (2 turns, 7.49s, cited `ch08-039`)
3. `qz-quantization-plain`: PASS (1 turn, 6.19s, cited `chapter-1-003`)
4. `qz-quantization-examples`: PASS (2 turns, 9.92s, cited `chapter-2-006`)
5. `ag-fsm-examples`: PASS (1 turn, 2.50s, cited `ch01-013`)
6. `ag-fsm-examples-followup`: PASS (2 turns, 8.34s, cited `ch01-013`)
7. `fde-storage-position`: PASS (1 turn, 3.01s, cited `ch06-001`)
8. `fde-multicloud-disadvantages`: PASS (1 turn, 2.36s, cited `ch04-037`)
9. `fde-insert-only-utility`: PASS (1 turn, 2.42s, cited `ch08-107`)
10. `fde-refuse-sourdough`: PASS (1 turn, 3.07s, refused out-of-book control)
11. `fde-refuse-france`: PASS (1 turn, 3.16s, refused out-of-book control)
12. `ag-refuse-single-node`: PASS (1 turn, 1.93s, refused out-of-book comparison control)

### B. Wide-Net v2 Evaluation (`wide_net_eval.py`)
Baseline: `artifacts/runs/wide-net-eval-v2-2026-10-31/evidence/wide-net-v2-2026-10-31.model-nekohon_q35_2b_x3_2e.json` (SHA-256 `c323f3cf408b`).
Round 1: `artifacts/runs/wn2-after-all-2026-10-31.json` (SHA-256 `c8204e1ff7ba`).
Round 2 (Current): `artifacts/runs/wn2-after-span-2026-11-01.json` (SHA-256 `a3161c000e2f`).

| Category | Baseline Pass | Round 1 Pass | Round 2 Pass | Notes |
| :--- | :--- | :--- | :--- | :--- |
| `short_bare` | 7 / 12 | 9 / 12 | **10 / 12** | Gained `wn2-fde-s1`, `wn2-ddia-s3` (R1), `wn2-ddia-s4` (R2) |
| `noisy` | 3 / 8 | 3 / 8 | **5 / 8** | Gained `wn2-quant-n1` and `wn2-ddia-n2` (R2) |
| `definition` | 4 / 8 | 4 / 8 | **7 / 8** | Gained `wn2-fde-d1`, `wn2-fde-d2`, `wn2-fde-d3` (R2) |
| `comparison` | 2 / 6 | 6 / 6 | **6 / 6** | 100% pass (+4 items in R1) |
| `multi_turn` | 3 / 8 | 3 / 8 | **5 / 8** | Gained `wn2-fde-m1` and `wn2-ddia-m3` (R2) |
| `refusal` | 6 / 6 | 6 / 6 | **6 / 6** | 100% pass on negative controls |
| **TOTAL** | **25 / 48 (52.1%)** | **31 / 48 (64.6%)** | **39 / 48 (81.2%)** | **+14 items net vs baseline (+8 vs R1, 0 lost)** |
| Mean latency | 2.43s | 3.52s | **2.81s** | **-0.71s faster than R1** (+0.38s latency penalty vs 2.43s baseline) |
| First-line quote length | 209 chars median (288 mean) | 209 chars median | **869 chars median (804 mean)** | **+660 chars median quote length penalty** (cap-600 arm `61b9382126b6` is 563 median / 38 of 48) |

---

## 4. Round 2 Continuation Additions (2026-11-01) & Remaining 9 Failures

### Round 2 Changes Landed (`answer.py`, `agentic.py`, `comparison-matrix.py`)
1. **Concept-span quote expansion (`_concept_span` in `answer.py`, wired into `parse_completion` and `parse_answered`)**:
   - Scores paragraphs of the cited passage by query + gloss concept stems, spans from first to last paragraph reaching the passage median (and adjacent paragraphs reaching half the median) within `PARAGRAPH_CAP = 1200`, verified verbatim by `_quote_in_passage`.
   - Vetoes: strips chunk heading by exact match, never widens a quote announcing a list or followed by an ordinal/bullet marker (preserving Turn 2 follow-up advancement in `test_multiturn_followup_citation_advancement`), never widens a follow-up whose chunk already holds the prior turn's quote, and skips comparisons.
   - Fixed embedded-quote truncation in `parse_completion` (`wn2-quant-n1`) and forwarded `anchors` + `question` + `prior_quote` in `_retry_uncited` (`wn2-fde-d3`).
2. **Order-preserving phrase promotion (`_prioritize_phrase_matches` in `answer.py`)**:
   - Body-only single-phrase cross-references no longer demote the dense leader; promotion requires a heading match or two distinct query phrases (`wn2-fde-d2` now keeps `ch08-042` at rank 1).
3. **Hit contract & checker hygiene (`agentic.py`, `comparison-matrix.py`)**:
   - `agentic._as_hit` includes `section` and `anchor` (matching `retrieve.search` and fixing `tests/test_agentic.py`).
   - `comparison-matrix.heading_lines_for` reads `chunk["heading"]` and `chunk["section"]` rather than treating the first body paragraph (`lines[1]`) as a heading line.

### Remaining Open Failures in Wide-Net v2 (9 items)
1. **Wrong shown passage cited by the model (8 items — gold chunk is in `shown_passages`, but the model cited a different shown chunk whose text lacks the key fact)**:
   - `wn2-fde-n1` ("how big shoud baches be")
   - `wn2-fde-n3` ("waht is jdbc")
   - `wn2-fde-m2` ("What is reverse ETL used for?")
   - `wn2-fde-m3` ("What about stream processing?")
   - `wn2-ddia-s1` ("fencing tokens")
   - `wn2-ddia-d2` ("What is total order broadcast?")
   - `wn2-ddia-m2` ("Why can't we just pick a fixed timeout?")
   - `wn2-ddia-n3` ("colum compression")
2. **True retrieval miss (1 item — gold chunk absent from top-5 `shown_passages`)**:
   - `wn2-quant-s3` ("KV cache quantization": gold `chapter-7-009` at dense rank 8, BM25 rank 11).

## 5. Next Steps for Continuation

1. **Citation-chunk selection for the 8 wrong-chunk items**:
   - Evaluate local cross-encoder reranking (`RERANK_ENABLED=1` with `onnxruntime` installed) or model-side fine-tuning data so the model cites the gold passage already present in `shown_passages`.
2. **Sentence-level quote cap that preserves the answering sentence**:
   - Replace the naive prefix cut (`QUOTE_CAP = 600` in `artifacts/runs/wn2-cap600-2026-11-01.json`, SHA-256 `61b9382126b6`, which scored 38/48 at 563 median chars by cutting `wn2-ddia-s2` before its answering sentence) with a sentence-window selector around the highest-scoring concept sentence so quotes drop below 600 chars while keeping 39/48.
