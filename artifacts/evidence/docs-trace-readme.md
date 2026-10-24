# Docs trace — README.md and BUILD_PLAN.md
Checked 2026-10-25 against code, reports, datasets, and `ollama list`; no answer model was run.
Verdicts: STALE rows first within each file, then TRUE/UNVERIFIABLE. Evidence is file:line or the command run.

## README.md

| doc:line | claim (short) | verdict | evidence (path:line or command) | suggested wording |
| --- | --- | --- | --- | --- |
| README.md:148 | Model lineup is current | STALE | `artifacts/reports/r5-2026-10-25.md:17,43-46,74-76`; `ollama list` shows `nekohon_q35_2b_r5` | Add a "tried, not adopted" row: r5, 870 rows, hard-mt 10/12, sealed 27/30 (2026-10-25) |
| README.md:158 | `embeddinggemma-2:270m-bf16-text` is ~540 MB | STALE | `ollama list` reports 574 MB; `AGENTS.md:1387` | 574 MB |
| README.md:177 | `setup_models.py --install` registers `nekohon_x3` | STALE | `prompt.py:82` default is `nekohon_q35_2b_x3_2e`; `scripts/setup_models.py:78-93,533-543` | "register the default `nekohon_q35_2b_x3_2e` (plus the other listed models)" |
| README.md:227 | `/` serves the legacy `window/index.html` | STALE | `server.py:255-265` prefers `web/out/index.html`, which exists | "`web/out` when built, else the legacy window" |
| README.md:243-270 | The testing/quality-gate list is complete | STALE | `artifacts/datasets/hard-mt-2026-10-24.jsonl` (12 rows); `artifacts/reports/hard-mt-2026-10-24.md:31-37` | Add `python artifacts/harnesses/hard-mt-eval.py [model]` (12 items, 12/12 on x3_2e) |
| README.md:244 | 385 unit tests across 22 suites, ~1.5 s | STALE | `python -m unittest discover -s tests` -> "Ran 459 tests in 21.101s"; 39 `tests/test_*.py` | 459 tests across 39 test modules, ~21 s |
| README.md:245 | The unit suite is a quality gate | STALE | Same run -> `FAILED (failures=2)`; `tests/test_frontend_rules.py:78` (`web/app/study.css:111` raw box-shadow) | State the 2 frontend-rule failures, or fix the CSS and re-run |
| README.md:256 | End-to-end battery is 22 live queries | STALE | `artifacts/harnesses/step2-battery.py:194-200`; `battery-pins.json` golden 10 + typos 3 + probes 4 + France 1 | "18 queries in ask mode; 22 in answer mode (`BATTERY_MODE=answer`)" |
| README.md:263 | `adrian-eval.py nekohon_x3` | STALE | `artifacts/harnesses/adrian-eval.py:407-411` has no positional model; model comes from `ANSWER_MODEL` | `ANSWER_MODEL=nekohon_q35_2b_x3_2e python artifacts/harnesses/adrian-eval.py --direct` |
| README.md:266 | `crossbook-evil-eval.py nekohon_x3` | STALE | `artifacts/harnesses/crossbook-evil-eval.py:297-303` has no positional model | `ANSWER_MODEL=nekohon_q35_2b_x3_2e python artifacts/harnesses/crossbook-evil-eval.py` |
| README.md:152-156 | Default/date, four SHA-256 prefixes, disk sizes | TRUE | sha256 of `data/models/*/*.gguf` matches `1621bcb3…`, `5b2b573a…`, `92fb94df…`, `c3d8492f…`; sizes 1,312,164,768 / 1,929,902,656 / 986,048,192 bytes | — |
| README.md:148 | Default 844 rows/2 epochs; candidate 417 rows/5 epochs | TRUE | `artifacts/reports/finetune-round2-x3-2026-10-24.md:12-17`; `artifacts/reports/qwen35-swap-2026-10-24.md:94-98` | — |
| README.md:125-127 | Catalog: 1,042/473/1,307 chunks, 111/76/90 figures, 17/7/17 chapters | TRUE | `data/books.json` | — |
| README.md:26,120 | RRF K = 60 and a 20% dense band | TRUE | `fusion.py:53-57` (`RRF_K = 60`, `RANK_BAND = 0.20`) | — |
| README.md:190 | Re-embed takes ~14 s | TRUE | `artifacts/reports/reranking-bakeoff-2026-10-23.md:120` (fde 13.1 s) | — |
| README.md:235 | Hard bench has 10 adversarial items | TRUE | `artifacts/datasets/hard-bench-2026-10-17.jsonl`: 10 `adversarial_injection` | — |
| README.md:251 | Hard bench is 60 items | TRUE | Dataset has 60 rows; `artifacts/harnesses/hard-bench.py:457` | — |
| README.md:262 | Adrian: 35 scenarios, 97 turns, 91.4% | TRUE | Dataset sums 35/97; `artifacts/reports/nekohon-multibook-and-perf-2026-10-18.md:207-209` | — |
| README.md:265 | Crossbook: 30 scenarios, 66 requests, 76.7% | TRUE | Dataset sums 30/66; `artifacts/reports/nekohon-multibook-and-perf-2026-10-18.md:167-175,212-214` | — |
| README.md:278-282 | Offline proof: 000, ask works, localhost-only sockets | TRUE | `artifacts/evidence/phase7-offline/phase7-offline.log` | — |
| README.md:290 | `docs/ENGINEERING_AND_BENCHMARKS.md` exists | TRUE | File present, 32,491 bytes | — |
| README.md:302-303 | GPL-3.0 and vendored Snowball licence exist | TRUE | `LICENSE:1-2`; `vendor/snowballstemmer/COPYING` present | — |
| README.md:167 | Python 3.9+ | TRUE | `ast.parse(..., feature_version=(3,9))` passes for all root `*.py` | — |
| README.md:213 | Build once; `server.py` serves the reader at `/` | TRUE | `server.py:255-259`; `web/out/index.html` exists | — |
| README.md:225 | `/health` returns `ok` and `ollama` | TRUE | `server.py:246-253` (extra keys included) | — |
| README.md:128 | `mode: "import"` is accepted | TRUE | `server.py:84-92,404-410` (`EXTRA_MODES`) | — |
| README.md:293 | 0/1,042 mid-sentence starts; 983/1,042 terminal punctuation | UNVERIFIABLE | `docs/ENGINEERING_AND_BENCHMARKS.md:130-131` repeats it; no recomputation performed | Keep, or cite the script that derived it |

## BUILD_PLAN.md

| doc:line | claim (short) | verdict | evidence (path:line or command) | suggested wording |
| --- | --- | --- | --- | --- |
| BUILD_PLAN.md:125 | "All edge cases ... are resolved" | STALE | `artifacts/reports/hard-mt-2026-10-24.md:68-70` and `finetune-round2-x3-2026-10-24.md:47-49`: sealed 27/30, hard bench 59/60, adrian 32/35 | "Hard-mt 12/12; sealed 27/30, hard bench 59/60, adrian 32/35" |
| BUILD_PLAN.md:127 | Two drafts live under `~/.hermes/cache/scratch/` | STALE | `Path('~/.hermes/cache/scratch').exists()` is False | Remove, or point to a live archive |
| BUILD_PLAN.md:169 | `llama3.2:3b` is on disk; README fallback | STALE | `ollama list` has no such tag; no GGUF under the repo; README never mentions llama | Drop the row |
| BUILD_PLAN.md:170 | `deepseek-r1:7b` is on disk | STALE | `ollama list` has no such tag; `AGENTS.md:148` says "Mac only so far" | "not on this box; Mac only" |
| BUILD_PLAN.md:209 | `models/` holds the x3 and x3_mobile Modelfiles | STALE | `models/` has 8 dirs incl. `nekohon_q35_2b*`, `nekohon_q35_2b_r3/r4_1e/r5` | List all eight committed Modelfile dirs |
| BUILD_PLAN.md:212 | 385 tests across 22 suites | STALE | `python -m unittest discover -s tests` -> 459 tests, 21.101 s, 2 failures; 39 test modules | 459 tests across 39 modules; add `test_followup_subject.py`, `test_fabricated_attribution.py`, `test_hard_mt_leakage.py` |
| BUILD_PLAN.md:220 | Harnesses are hard-bench and step2-battery | STALE | `artifacts/harnesses/hard-mt-eval.py` exists and is used by the 2026-10-25 report | Add `hard-mt-eval.py` (12-item multi-turn bench) |
| BUILD_PLAN.md:258 | `mode` is ask, answer, explain, quiz | STALE | `server.py:84-92` (`MODES` plus `EXTRA_MODES = ("import",)`); README:128 | "ask, answer, explain, quiz, plus import" |
| BUILD_PLAN.md:287 | The only routes are `/ask`, `/figures`, `/health`, `/` | STALE | `server.py:317` serves `GET /chunks`; README:224 documents it | Add `GET /chunks` |
| BUILD_PLAN.md:425 | Nomic smoke index was 1,065 chunks | STALE | `data/books.json` fde = 1,042; `artifacts/reports/query-canonicalization-2026-10-13.md:127-131` says "live index is 1042 (not 1065)" | "1,065 at the time (later corrected to 1,042)" |
| BUILD_PLAN.md:585 | "Next: x2d" | STALE | `BUILD_PLAN.md:576-577` says x2d was succeeded by x3 on 2026-10-17; q35 adopted 2026-10-24 (`prompt.py:82`); r5 rejected 2026-10-25 | Replace with x2d -> x3 -> q35 -> x3_2e (2026-10-24); r5 rejected |
| BUILD_PLAN.md:604 | `reports/x2e-verdict-2026-10-15.md` | STALE | No root `reports/`; file is `artifacts/reports/x2e-verdict-2026-10-15.md` (same for lines 592, 596, 613) | Prefix with `artifacts/reports/` |
| BUILD_PLAN.md:18 | Gemma tried 2026-10-23 and reverted, hard bench 60/60 -> 53/60 | TRUE | `artifacts/reports/reranking-bakeoff-2026-10-23.md:112-114` | — |
| BUILD_PLAN.md:163 | x3_2e: 59/60 hard bench, 32/35 adrian, 27/30 sealed | TRUE | `artifacts/reports/finetune-round2-x3-2026-10-24.md:47-49` | — |
| BUILD_PLAN.md:164 | q35 417-row: sealed 25/30, adrian 31/35 | TRUE | `artifacts/reports/finetune-round2-x3-2026-10-24.md:49`; `qwen35-swap-2026-10-24.md:220-221` | — |
| BUILD_PLAN.md:564-566 | 2,822 passages, 277 figures, 41 chapters | TRUE | `data/books.json` (sum of three books) | — |
| BUILD_PLAN.md:570-575 | R15 cache numbers, keep_alive, 99.5% DOM | TRUE | `artifacts/reports/nekohon-multibook-and-perf-2026-10-18.md:119-129` | — |
| BUILD_PLAN.md:172 | Named models are registered on this Windows runner | TRUE | `ollama list`: x3, x3_mobile, qwen2.5:7b, nomic, granite4.1:8b, embeddinggemma | — |
| BUILD_PLAN.md:183 | Ollama v0.40.3 | TRUE | `artifacts/reports/qwen35-swap-2026-10-24.md:13`; `AGENTS.md:1351` | — |
| BUILD_PLAN.md:553,558 | x3 and mobile GGUF SHA-256 prefixes | TRUE | sha256 files = `92fb94df741b2117…` and `c3d8492fe73114a…`; report `x3-architecture-and-distillation-2026-10-17.md:154-155` | — |
| BUILD_PLAN.md:635 | v1 passed 2026-10-12 | TRUE | `artifacts/evidence/phase7-offline/phase7-offline.log` (000, cited ask, localhost sockets) | — |

Checked 48 claims: 27 in README.md, 21 in BUILD_PLAN.md. 22 STALE, 25 TRUE, 1 UNVERIFIABLE.
