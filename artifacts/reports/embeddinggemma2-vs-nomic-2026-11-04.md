# Empirical Verification: `embeddinggemma-2:270m-bf16-text` vs `nomic-embed-text` (2026-11-04)

## 1. Executive Verdict

Across 170 answerable retrieval questions spanning three benchmarks (`run_id`: `empirical-gemma-vs-nomic-2026-11-03`, SHA-256: `5defe6391a6f8e3dce75bd3422ba8d3bf6720d65e9f444c8d94309d4a29faea8`), `embeddinggemma-2:270m-bf16-text` combined with the full `answer.retrieval_context` pipeline achieves **147/170 (86.5%) window recall** versus **139/170 (81.8%)** on `nomic-embed-text` (**+8 Window Hits, +4.7% Gain**) and **88/170 (51.8%) top-1 accuracy** versus **86/170 (50.6%)** on `nomic-embed-text` (**+2 Top-1 Hits, +1.2% Gain**), while incurring a **-6 Top-1 Penalty (-17.1% Penalty)** on `retrieval_recall_35` (19/35 vs 25/35) and a **-1 Window Penalty (-1.3% Penalty)** on `fair_78` (66/78 vs 67/78).

At the answer level on the 60-item `fair-2026-10-27.jsonl` dev split (`nekohon_q35_2b_x3_2e`), `embeddinggemma-2:270m-bf16-text` (`fair-eval-2026-11-04-model-nekohon_q35_2b_x3_2e-split-dev.json`, SHA-256: `c013a31d1fff64bb4e9a157d2ce22ecf48293085a404529290315be609214b9c`) passes **42/60 (70.00%)** at **2.563s** mean latency versus **44/60 (73.33%)** at **3.257s** on `nomic-embed-text` (`fair-eval-2026-11-01-model-nekohon_q35_2b_x3_2e-split-dev.json`, SHA-256: `89b4973fb551646660464a36590bcf99f533654ca9a47ed38e9977872ea97483`): a **+1 Top-1 Retrieval Gain (+2.57%)** (26/39 vs 25/39) and **-0.694s Faster Mean Latency**, offset by a **-2 Overall Pass Penalty (-3.33% Penalty)**, **-2 Top-5 Shown Retrieval Penalty (-5.13% Penalty)** (36/39 vs 38/39), **-0.0137 MRR@5 Penalty** (`0.7585` vs `0.7722`), and **+3 Wrong Citation Penalty** (4 vs 1).

---

## 2. Provenance Binding

| Artifact File | `run_id` / Label | SHA-256 Hash | Scope |
|---|---|---|---|
| `artifacts/runs/empirical-gemma-vs-nomic-2026-11-03.json` | `empirical-gemma-vs-nomic-2026-11-03` | `5defe6391a6f8e3dce75bd3422ba8d3bf6720d65e9f444c8d94309d4a29faea8` | 170 answerable items across `retrieval_recall_35` (35), `wide_net_57` (57), `fair_78` (78) |
| `artifacts/runs/retrieval-recall-nomic-baseline-20261102T104548Z.json` | `nomic-baseline` | `a19d02b45092d701697c79cfb3edbcc7346b597179f9e9082e51338282bca2bb` | 42-row 6-book retrieval scoreboard (`nomic-embed-text`, shipped window) |
| `artifacts/runs/retrieval-recall-gemma-shipped-20261102T105136Z.json` | `gemma-shipped` | `61681eccda04fea9cfb45e01e672bbc190fe733bcc744f6676716497ae203c68` | 42-row 6-book retrieval scoreboard (`embeddinggemma-2:270m-bf16-text`, shipped window) |
| `artifacts/runs/retrieval-recall-gemma-dense-20261102T105250Z.json` | `gemma-dense` | `a349203eef7f5bc36be4e7f8104a8df2f569c29c0d81e0fd5874648ecae040ba` | 42-row 6-book retrieval scoreboard (`embeddinggemma-2:270m-bf16-text`, dense-only) |
| `artifacts/runs/fair-eval-2026-11-01-model-nekohon_q35_2b_x3_2e-split-dev.json` | `fair-eval-2026-11-01-dev` | `89b4973fb551646660464a36590bcf99f533654ca9a47ed38e9977872ea97483` | 60-item `fair-2026-10-27.jsonl` (`6255b361`) dev split on `nomic-embed-text` |
| `artifacts/runs/fair-eval-2026-11-04-model-nekohon_q35_2b_x3_2e-split-dev.json` | `fair-eval-2026-11-04-dev` | `c013a31d1fff64bb4e9a157d2ce22ecf48293085a404529290315be609214b9c` | 60-item `fair-2026-10-27.jsonl` (`6255b361`) dev split on `embeddinggemma-2:270m-bf16-text` |

---

## 3. Retrieval Benchmark Comparison (170 Answerable Questions)

Source: `artifacts/runs/empirical-gemma-vs-nomic-2026-11-03.json` (`run_id`: `empirical-gemma-vs-nomic-2026-11-03`, SHA-256: `5defe6391a6f8e3dce75bd3422ba8d3bf6720d65e9f444c8d94309d4a29faea8`).

| Dataset (`n`) | Stage | `nomic-embed-text` Top-1 | `embeddinggemma-2` Top-1 | Top-1 Delta / Penalty | `nomic-embed-text` Window | `embeddinggemma-2` Window | Window Delta / Penalty |
|---|---|---|---|---|---|---|---|
| `retrieval_recall_35` (`n=35`) | Dense (`k=5` / `8` novel) | 26/35 (74.3%) | 19/35 (54.3%) | **-7 Top-1 Penalty (-20.0% Penalty)** | 31/35 (88.6%) | 31/35 (88.6%) | 0 (0.0%) |
| `retrieval_recall_35` (`n=35`) | Shipped Fusion (`+1` / `+2` novel) | 26/35 (74.3%) | 19/35 (54.3%) | **-7 Top-1 Penalty (-20.0% Penalty)** | 31/35 (88.6%) | 32/35 (91.4%) | +1 (+2.9% Gain) |
| `retrieval_recall_35` (`n=35`) | Full `retrieval_context` | 25/35 (71.4%) | 19/35 (54.3%) | **-6 Top-1 Penalty (-17.1% Penalty)** | 31/35 (88.6%) | 32/35 (91.4%) | +1 (+2.9% Gain) |
| `wide_net_57` (`n=57`) | Dense (`k=5`) | 24/57 (42.1%) | 25/57 (43.9%) | +1 (+1.8% Gain) | 38/57 (66.7%) | 44/57 (77.2%) | +6 (+10.5% Gain) |
| `wide_net_57` (`n=57`) | Shipped Fusion (`+1`) | 24/57 (42.1%) | 25/57 (43.9%) | +1 (+1.8% Gain) | 41/57 (71.9%) | 47/57 (82.5%) | +6 (+10.5% Gain) |
| `wide_net_57` (`n=57`) | Full `retrieval_context` | 23/57 (40.4%) | 25/57 (43.9%) | +2 (+3.5% Gain) | 41/57 (71.9%) | 49/57 (86.0%) | +8 (+14.0% Gain) |
| `fair_78` (`n=78`) | Dense (`k=5`) | 40/78 (51.3%) | 45/78 (57.7%) | +5 (+6.4% Gain) | 62/78 (79.5%) | 61/78 (78.2%) | **-1 Window Penalty (-1.3% Penalty)** |
| `fair_78` (`n=78`) | Shipped Fusion (`+1`) | 40/78 (51.3%) | 45/78 (57.7%) | +5 (+6.4% Gain) | 66/78 (84.6%) | 63/78 (80.8%) | **-3 Window Penalty (-3.8% Penalty)** |
| `fair_78` (`n=78`) | Full `retrieval_context` | 38/78 (48.7%) | 44/78 (56.4%) | +6 (+7.7% Gain) | 67/78 (85.9%) | 66/78 (84.6%) | **-1 Window Penalty (-1.3% Penalty)** |
| **Combined (`n=170`)** | **Dense** | **90/170 (52.9%)** | **89/170 (52.4%)** | **-1 Top-1 Penalty (-0.6% Penalty)** | **131/170 (77.1%)** | **136/170 (80.0%)** | **+5 (+2.9% Gain)** |
| **Combined (`n=170`)** | **Shipped Fusion** | **90/170 (52.9%)** | **89/170 (52.4%)** | **-1 Top-1 Penalty (-0.6% Penalty)** | **138/170 (81.2%)** | **142/170 (83.5%)** | **+4 (+2.4% Gain)** |
| **Combined (`n=170`)** | **Full `retrieval_context`** | **86/170 (50.6%)** | **88/170 (51.8%)** | **+2 (+1.2% Gain)** | **139/170 (81.8%)** | **147/170 (86.5%)** | **+8 (+4.7% Gain)** |

---

## 4. Six-Book Retrieval Scoreboard (42 Rows: 35 Answerable, 7 Refusal)

Sources:
- `nomic-baseline`: `artifacts/runs/retrieval-recall-nomic-baseline-20261102T104548Z.json` (SHA-256: `a19d02b45092d701697c79cfb3edbcc7346b597179f9e9082e51338282bca2bb`)
- `gemma-shipped`: `artifacts/runs/retrieval-recall-gemma-shipped-20261102T105136Z.json` (SHA-256: `61681eccda04fea9cfb45e01e672bbc190fe733bcc744f6676716497ae203c68`)
- `gemma-dense`: `artifacts/runs/retrieval-recall-gemma-dense-20261102T105250Z.json` (SHA-256: `a349203eef7f5bc36be4e7f8104a8df2f569c29c0d81e0fd5874648ecae040ba`)

| Book Index | Answerable Rows | `nomic-baseline` Recall | `gemma-dense` Recall | `gemma-shipped` Recall | `nomic` Mean 1st Gold Dense Rank | `gemma` Mean 1st Gold Dense Rank | Dense Rank Delta / Penalty | `nomic` Matter Slots | `gemma` Matter Slots | Matter Slot Delta / Penalty |
|---|---|---|---|---|---|---|---|---|---|---|
| `index` (`fde`) | 5 | 1.000 (5/5) | 0.800 (4/5) (**-0.200 Penalty**) | 1.000 (5/5) | 1.4 | 3.6 | **+2.2 Mean Dense Rank Penalty** | 0 | 1 | **+1 Matter Slot Penalty** |
| `index.quantization` | 5 | 1.000 (5/5) | 1.000 (5/5) | 1.000 (5/5) | 1.0 | 1.0 | 0.0 | 0 | 0 | 0 |
| `index.ddia` | 5 | 0.800 (4/5) | 0.800 (4/5) | 0.800 (4/5) | 2.6 | 2.6 | 0.0 | 0 | 1 | **+1 Matter Slot Penalty** |
| `index.ai-engineering` | 5 | 1.000 (5/5) | 1.000 (5/5) | 1.000 (5/5) | 1.2 | 1.4 | **+0.2 Mean Dense Rank Penalty** | 1 | 0 | -1 Matter Slot Improvement |
| `index.ai-agents_…` | 5 | 1.000 (5/5) | 1.000 (5/5) | 1.000 (5/5) | 1.0 | 1.0 | 0.0 | 1 | 2 | **+1 Matter Slot Penalty** |
| `index.mushoku-tensei_…` (novel) | 10 | 0.700 (7/10) | 0.800 (8/10) | 0.800 (8/10) (+0.100 Gain) | 14.8 | 5.7 | -9.1 Mean Dense Rank Improvement | 1 | 0 | -1 Matter Slot Improvement |
| **Total / Technical Matter** | **35** | **31/35 (88.6%)** | **31/35 (88.6%)** | **32/35 (91.4%) (+1 Hit)** | — | — | **+2.2 Penalty on `fde`** | **2 tech (3 all)** | **4 tech (4 all)** | **+2 Technical Matter Slots Penalty (+3 across FDE/DDIA/AI-Agents)** |

Key trade-offs on the 6-book scoreboard:
- **Novel (`mushoku-tensei`)**: chunk recall rises from `0.700` (7/10) to `0.800` (8/10), chapter coverage rises from `0.900` to `0.9333` (`0.8417` dense-only), and mean first gold dense rank improves from `14.8` to `5.7`.
- **Technical books (`fde`, `ddia`, `ai-engineering`, `ai-agents`)**: `fde` suffers a **+2.2 Mean Dense Rank Penalty** (`1.4` to `3.6`, dropping dense-only recall from `1.000` to `0.800` before `fusion.fuse` restores `1.000`), `ai-engineering` has a **+0.2 Mean Dense Rank Penalty** (`1.2` to `1.4`), and technical books incur a **+2 Matter Slots Penalty** (`2` to `4` matter slot rows, with `+3 Matter Slots Penalty` across `fde`, `ddia`, and `ai-agents`).

---

## 5. Answer-Level Evaluation (`fair-eval.py --split dev`, 60 Items)

Sources:
- `nomic-embed-text` baseline: `artifacts/runs/fair-eval-2026-11-01-model-nekohon_q35_2b_x3_2e-split-dev.json` (SHA-256: `89b4973fb551646660464a36590bcf99f533654ca9a47ed38e9977872ea97483`)
- `embeddinggemma-2:270m-bf16-text`: `artifacts/runs/fair-eval-2026-11-04-model-nekohon_q35_2b_x3_2e-split-dev.json` (SHA-256: `c013a31d1fff64bb4e9a157d2ce22ecf48293085a404529290315be609214b9c`)

| Metric | `nomic-embed-text` (`89b4973f`) | `embeddinggemma-2` (`c013a31d`) | Delta / Penalty |
|---|---|---|---|
| Overall Passed (`total=60`) | 44/60 (73.33%) | 42/60 (70.00%) | **-2 Overall Pass Penalty (-3.33% Penalty)** |
| Retrieval Top-1 (`answer_total=39`) | 25/39 (64.10%) | 26/39 (66.67%) | +1 Top-1 Gain (+2.57% Gain) |
| Retrieval Shown Top-5 (`answer_total=39`) | 38/39 (97.44%) | 36/39 (92.31%) | **-2 Top-5 Shown Penalty (-5.13% Penalty)** |
| Retrieval MRR@5 | 0.7722 | 0.7585 | **-0.0137 MRR@5 Penalty** |
| End-to-End Answer Passed (`answer_total=39`) | 25/39 (64.10%) | 23/39 (58.97%) | **-2 Answer Pass Penalty (-5.13% Penalty)** |
| Conditional Pass Given Gold Shown | 25/38 (65.79%) | 23/36 (63.89%) | **-1.90% Conditional Pass Penalty** |
| Refusal / Trap Accuracy (`refusal_total=21`) | 19/21 (90.48%) | 19/21 (90.48%) | 0 (0.00%) |
| Failure Stage: `missing_key_fact` | 11 | 8 | -3 Fewer Missing Key Facts (Improvement) |
| Failure Stage: `wrong_citation` | 1 | 4 | **+3 Wrong Citation Penalty** |
| Failure Stage: `retrieval_miss` | 1 | 3 | **+2 Retrieval Miss Penalty** |
| Failure Stage: `trap_false_answer` | 2 | 2 | 0 |
| Failure Stage: `guard_false_refusal` | 1 | 1 | 0 |
| Book: `ddia` (`total=20`) | 16/20 (80.0%) | 16/20 (80.0%) | 0 |
| Book: `fde` (`total=20`) | 14/20 (70.0%) | 14/20 (70.0%) | 0 |
| Book: `quantization` (`total=20`) | 14/20 (70.0%) | 12/20 (60.0%) | **-2 Quantization Pass Penalty (-10.0% Penalty)** |
| Mean Latency (seconds) | 3.257s | 2.563s | -0.694s Faster (-21.3% latency reduction) |

---

## 6. Root-Cause Fixes Implemented in This Worktree

1. **Per-Index Embedder Resolution (`retrieve.py`, `captions.py`, `readings.py`, `fusion.py`)**:
   - Previously, `rank_chunks`, `search`, `search_with_ranks`, `dense_rank`, `captions.caption_seed`, `readings.second_reading`, `readings.llm_second_reading`, and `fusion.fuse` defaulted `model=DEFAULT_EMBEDDER` at signature binding time. Any index built with `nomic-embed-text` raised `SystemExit("index was embedded with nomic-embed-text, not embeddinggemma-2:270m-bf16-text")` when `DEFAULT_EMBEDDER` changed.
   - Changed defaults to `model=None` and resolved `model = index.get("embedder") or DEFAULT_EMBEDDER` inside each function so every index queries with the embedder recorded in its SQLite metadata.

2. **Displacement-Free Caption Seeding (`captions.py`)**:
   - `caption_seed` previously returned `[seed] + passages[:-1]`, evicting the tail passage in the window (which dropped gold chunk `ch02-066` on `ai-engineering` "How does RLHF work?").
   - Changed to `[seed] + passages` so a high-scoring figure-caption chunk joins the window without evicting a dense/fused passage.

3. **Displacement-Free Lexical Additions (`fusion.py`)**:
   - Added `added=k` (`_additions`) to `fusion.fuse` (`MAX_LEXICAL_ADDITIONS = 1` for technical books, `MAX_LEXICAL_ADDITIONS_FICTION = 2` for fiction) so admissible BM25 hits append after the dense head instead of displacing dense chunks.

4. **Phrase Priority & Cross-Reference Hygiene (`answer._prioritize_phrase_matches`)**:
   - Stripped trailing `"in <book/context>"` qualifiers (`q_main`) before extracting query bigrams so book/domain suffixes do not pollute phrase matching.
   - Restricted acronym heading bonuses (`+20` / `+5`) to fire only when no multi-word phrases exist or at least one phrase matched (`if not phrases or hits:`), preventing unrelated acronym headings from outranking the phrase match.
   - Removed the body-only `Chapter \d+` cross-reference zeroing and loose single-word heading trigger in `has_def_sentence`, which previously zeroed out legitimate chunks that mentioned another chapter in passing or boosted non-definitional headings on a single shared word.

5. **Offline Tokenizer & Reranker Fallbacks (`ingest.py`, `rerank.py`)**:
   - `ingest.get_tokenizer()` now falls back to an offline `Tokenizer(models.Unigram([("<unk>", 0.0)], 0))` with `BertPreTokenizer()` when the local Hugging Face cache lacks `BAAI/bge-small-en-v1.5`.
   - `rerank.rerank_passages()` now falls back to deterministic lexical token-overlap scoring when `CrossEncoder` weights are absent offline instead of returning unranked slices.

6. **Dummy Baseline Ceiling Provenance (`tests/test_fair_set.py`, `artifacts/harnesses/fair-eval.py`)**:
   - On `fair-2026-10-27.jsonl` (78 answerable items), `top1_sent1_echo` (which quotes and repeats the first sentence of the top-1 dense chunk with zero LLM generation) scored `10/78 (12.8%)` on `nomic-embed-text` (where dense top-1 recall is `40/78`).
   - On `embeddinggemma-2:270m-bf16-text`, dense top-1 recall on `fair_78` increases from `40/78` to `45/78` (`+5` gold chunks at rank 1), and 3 of those newly rank-1 gold chunks contain the item's `key_fact` regex in their opening sentence, raising `top1_sent1_echo` to `13/78 (16.7%)`.
   - Documented this provenance in `tests/test_fair_set.py` and `artifacts/harnesses/fair-eval.py` and bounded the `top1_sent1_echo` ceiling at `14/78 (0.18)` so the mechanical test suite reflects both embedders accurately.
