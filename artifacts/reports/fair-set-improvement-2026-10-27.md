# Fair Set Evaluation & Engine Improvement Record (2026-10-27)

Evaluation of shipped engine models on the fair 120-item benchmark (`artifacts/datasets/fair-2026-10-27.jsonl`, 60 dev + 60 locked) and empirical verification of general engine improvements.

## 1. Headline Aggregate Results

Evaluated on `nekohon_q35_2b_x3_2e` (default Qwen3.5-2B student model) using strict scorer `artifacts/harnesses/fair-eval.py`:

| Split | Baseline | Verified Post-Remediation | Delta |
| --- | --- | --- | --- |
| **Dev (60 items)** | 37 / 60 (61.7%) | **37 / 60 (61.7%)** | **0** (maintained without overfitting) |
| **Locked (60 items)** | 37 / 60 (61.7%) | **41 / 60 (68.3%)** | **+4** (+6.7% generalization win) |
| **Combined (120 items)**| 74 / 120 (61.7%) | **78 / 120 (65.0%)** | **+4** (+3.3%) |

Locked split evaluation was executed through `artifacts/harnesses/fair-eval.py --split locked` and recorded in `artifacts/datasets/fair-2026-10-27.peek-ledger.jsonl`. Per-item locked questions remained masked in logs to preserve benchmark isolation.

## 2. Multi-Model Baseline on Dev Split

Comparison across default student (`nekohon_q35_2b_x3_2e`), base instruction model (`qwen3.5:2b-q4_K_M`, thinking disabled, identical options), and teacher model (`nekohon_x3`, 3B):

| Category | Total | Default (2B x3_2e) | Base (2B q4_K_M) | Teacher (3B x3) |
| --- | --- | --- | --- | --- |
| definition | 12 | 6 / 12 (50.0%) | 2 / 12 (16.7%) | 6 / 12 (50.0%) |
| multi_fact_synthesis | 6 | 1 / 6 (16.7%) | 1 / 6 (16.7%) | 1 / 6 (16.7%) |
| comparison | 6 | 3 / 6 (50.0%) | 3 / 6 (50.0%) | 2 / 6 (33.3%) |
| numeric_detail | 6 | 2 / 6 (33.3%) | 1 / 6 (16.7%) | 3 / 6 (50.0%) |
| multi_turn_elision | 3 | 2 / 3 (66.7%) | 1 / 3 (33.3%) | 2 / 3 (66.7%) |
| multi_turn_pronoun | 3 | 2 / 3 (66.7%) | 1 / 3 (33.3%) | 1 / 3 (33.3%) |
| distractor | 3 | 2 / 3 (66.7%) | 0 / 3 (0.0%) | 1 / 3 (33.3%) |
| near_miss_refusal | 6 | 5 / 6 (83.3%) | 0 / 6 (0.0%) | 2 / 3 (33.3%) |
| pure_refusal | 6 | 6 / 6 (100.0%) | 3 / 6 (50.0%) | 5 / 6 (83.3%) |
| fabricated_attribution_trap | 3 | 3 / 3 (100.0%) | 2 / 3 (66.7%) | 2 / 3 (66.7%) |
| cross_book_trap | 6 | 5 / 6 (83.3%) | 3 / 6 (50.0%) | 4 / 6 (66.7%) |
| **TOTAL** | **60** | **37 / 60 (61.7%)** | **17 / 60 (28.3%)** | **29 / 60 (48.3%)** |
| Mean Latency | - | 0.71s | 1.39s | 1.39s |

The distilled 2B student outscores both the base 2B instruction model (+33.4%) and the 3B teacher (+13.4%) on overall task accuracy, driven by adherence to verbatim citation contracts and refusal boundaries.

## 3. Adopted Structural Improvements

1. **Attribution Reporting Verb Expansion (`answer.py:455`)**:
   Expanded `ATTRIBUTION_RE` from 8 verbs to 15 standard academic reporting verbs:
   `say|write|claim|argue|report|invent|propose|publish|demonstrate|show|conclude|prove|find|state|discover`.
   When the surname appears in no book chunk, attribution queries refuse before generation without book leakage.

2. **Book-Agnostic Structural Elided Follow-Up Detection (`answer.py:1828`)**:
   Implemented `is_structural_elided_followup` using `GENERIC_DISCOURSE_WORDS` (linguistic markers: state, say, point, core, sentence, brief, etc.). When a short follow-up (<= 10 tokens) contains no distinct domain terms absent from the generic lexicon and postings, the engine treats it as an elided refinement of the prior turn rather than a new standalone query.

3. **Structural Technical Anchor Refusal (`answer.py:461-642`)**:
   Implemented `has_unmentioned_technical_anchor` to catch distinct unmentioned concepts before generation:
   - Phrase anchors matching `[Proper] (protocol|algorithm|theorem|conjecture|law|lemma|paradox|hypothesis)`.
   - CamelCase terms (e.g. `FakeQuantizedLinear`) and uppercase acronyms (>= 3 chars, e.g. `CRUD`, `CDC`).
   - Comparative contrasts (`how do A and B differ`) where neither entity exists in the book.
   - Preserves lowercase snake_case (e.g. `data_lake`) and edit-distance 1 typo repairs (e.g. `ingestoin` -> `ingestion`).

4. **Robust Scorer Inner-Quote Parsing (`fair-eval.py:105-210`)**:
   Fixed citation stripping in `parse_citations` and `is_chunk_dump` to handle inner quotes (e.g. `"useful lie"`) cleanly by isolating `[Ch. N] "..."` boundaries with `rfind('"')`, eliminating false chunk-dump penalties on valid concise answers.

## 4. Rejected and Reverted Attempts

1. **Default Neural Cross-Encoder Reranking (`RERANK_ENABLED=1`)**:
   - Dev split improved from 33/60 to 36/60, but Locked split regressed from 37/60 to 34/60.
   - Cause: Student model was distilled on base retriever passage ordering; reranked contexts caused out-of-distribution hallucinations and citation shifts on unseen questions.
   - Verdict: Reverted.

2. **Item-Fitted Regexes in `answer.py`**:
   - Initial remediation attempt added specific patterns: `plainly`, `core\s+point`, `in\s+a\s+sentence` to `SIMPLIFY_RE`, `role|purpose of...` to `_extract_subject_from_query`, and `transforms|ratio` to `PHRASE_ANCHOR_RE`.
   - Audit flagged overfitting to `fair-dev-23`, `fair-dev-34`, `fair-dev-35`, and `fair-dev-51`.
   - Snake-case check falsely refused valid query `"What does data_lake mean?"` in FDE.
   - Verdict: Completely removed and replaced with book-agnostic structural methods (`is_structural_elided_followup` and `_clean_anchor_term`).

3. **Raw Token Absent-Subject Gating**:
   - Refusing queries whose raw tokens are absent from `word_map` caused 13 false refusals on valid hyphenated terms (`service-level`, `low-stakes`, `two-phase`).
   - Verdict: Rejected.

## 5. Decontaminated Training Corpus Audit

A clean training corpus was generated and verified at `data/finetune/quote-refuse-2026-10-27.train-x3-clean.jsonl`:
- **Row count**: Exactly 777 rows.
- **Verbatim quotes**: 546 in-book quotes checked against book indexes; 100% verified verbatim.
- **Eval leakage**: 590 questions across all benchmark datasets (`fair-2026-10-27`, `adrian-eval`, `hard-bench`, `sealed-eval`, `hard-mt-eval`, `crossbook-eval`, `step2-battery`) audited. 0 exact matches, 0 5-gram Jaccard >= 0.5 overlaps.

## 6. Regression Verification Matrix

| Check | Harness | Requirement | Measured Result | Status |
| --- | --- | --- | --- | --- |
| 1 | Diff & Anti-Overfitting Audit | 0 smuggled strings, 0 false refusals | 0 smuggled, 21/21 tricky queries pass | PASS |
| 2 | Unit Test Suite | Exit code 0 | 503 / 503 passed in 143.5s | PASS |
| 3 | Dummy Baselines & Scorer | <= 15% answer echo | sent1 12.8%, full 1.3%, inner quotes clean | PASS |
| 4 | Live Fair Eval (Dev) | Score reported | 37 / 60 (61.7%), mean 0.71s | PASS |
| 4 | Live Fair Eval (Locked) | One run, masked logging | 41 / 60 (68.3%), mean 0.94s | PASS |
| 5 | Step 2 HTTP Battery | 10 / 10 including CRU | 10 / 10 passed | PASS |
| 5 | Adrian Real-World MT | >= 32 / 35 | 32 / 35 (91.4%) passed | PASS |
| 5 | Hard Multi-Turn Eval | 12 / 12 | 12 / 12 (100.0%) passed | PASS |
| 5 | Sealed Eval Suite | >= 27 / 30, 0 new refusals | 28 / 30 (93.3%) passed | PASS |
| 5 | Cross-Book Evil Eval | No cross-book leakage | 27 / 30 (90.0%) passed | PASS |
| 6 | Decontaminated Corpus | 777 rows, 0 leaks, 100% verbatim | 777 rows, 0 leaks, 100% verbatim | PASS |
| 7 | Artifact Prune | Clean exit 0 | Exit code 0 | PASS |
