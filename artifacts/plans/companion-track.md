# Companion track

Status: 2026-10-18. Live multi-turn companion in **NekoHon (`猫本`)**. Read this file first. Pointers, not copies.
Conversation map (history / thread / quote-check bounds): `conversation-map.md` — read before touching conversation.

`docs/GOAL.md` covers multi-turn synthesis: simpler words, the cited passage, the figure, and cross-book multi-volume navigation. Refusal stays exactly `Not in this book.`

## Live path

Each ask is processed via hybrid retrieval with chapter-neighborhood context:
- `retrieve.py` `search` ranks chunks with pre-normalized unit vectors (`_uvec`, 2.6x speedup).
- Inverted rare-word postings (`_POSTINGS_CACHE`, 45,000x speedup) and vocabulary mapping (`_SORTED_WMAP_CACHE`, 3.5x speedup) run in sub-millisecond CPU time.
- `answer.py` `ask` and `respond` send `SYSTEM` + `user_message` and check quotes against this turn's passages.
- In multi-turn follow-ups, `answer.py` biases passage candidate pools to the current chapter neighborhood, preventing out-of-context chapter jumps during follow-ups like `"Explain more simply"`.
- Simplification fast-path (`SIMPLIFY_RE`) synthesizes grounded simplifications in ~850 ms instead of full ~2,100 ms regeneration.

Default answer model tag is `nekohon_x3` (3B desktop) and `nekohon_x3_mobile` (1.5B mobile) via Ollama, with `smallbook_x3` alias. Engine keep-alive is configured to `24h` to prevent cold-start latency spikes.

## Completed Milestones

### 1. Multi-turn Follow-up Thread with Client-held History (Shipped)
- Browser holds up to 6 completed turns per `<MarginCard>`.
- Client transmits up to 2 completed turns as `history` on `POST /ask`.
- Server remains stateless; quote verification evaluates exclusively against passages retrieved for this turn.
- Chapter-neighborhood passage prioritization guarantees that pronoun follow-ups (`"what does it do?"`, `"how does that work?"`) and simplification cues (`"explain more simply"`) resolve within the active chapter.

### 2. Multi-Book Library Catalog (Shipped)
- Catalog of 3 technical volumes configured in `data/books.json`:
  1. *Fundamentals of Data Engineering* (`fde`): 1,042 chunks, 111 figures, 17 chapters.
  2. *Quantization and Fast Inference* (`quantization`): 473 chunks, 76 figures, 7 chapters.
  3. *Designing Data-Intensive Applications* (`ddia`): 1,307 chunks, 90 figures, 17 chapters.
  Total: 2,822 chunks and 277 figures across 41 chapters.
- Cross-publisher normalization:
  - Manning `div.figure-container` + `<h5>` captions + dot figure numbers (`Figure 1.1` -> `figure-1-1`).
  - O'Reilly heading-based non-teaching filter (151 alphabetical index chunks cleanly excluded).
  - 100% filesystem-driven figure resolution in `figures.py` (no hardcoded book IDs).

### 3. Student Distillation to nekohon_x3 (Shipped)
- 7-layer distillation pipeline (844 rows: 707 cited + 137 refusals) trained via Wide-LoRA (r=32, alpha=64) on A100.
- Shipped tags: `nekohon_x3` (3B) and `nekohon_x3_mobile` (1.5B).
- Verification: 60/60 on Hard Benchmark (100.0%, 0.71s mean latency), 24/24 on Highlight Golden, 22/22 on HTTP battery.

### 4. Adversarial Multi-Turn & Cross-Book Evaluation Suites (Shipped)
- `adrian-eval.py`: 35 real-world scenarios across 92 HTTP turns (32/35 passed, 91.4% overall; 100% on pill clicks, lazy queries, and ungrounded premises).
- `crossbook-evil-eval.py`: 30 adversarial cross-book scenarios across 66 HTTP requests over `fde`, `quantization`, and `ddia` (23/30 passed, 76.7%).
- `followup-evil-train-2026-10-17.jsonl`: 100-row adversarial training set for multi-turn robustness.

## Other plans

| What | File | Use it for |
| --- | --- | --- |
| Pane now | `pane-now.md` | Authoritative record of current reader, library start menu, and margin layout. |
| Conversation map | `conversation-map.md` | Read before any history/thread edit. What may change, what breaks the quote check, file map. |
| Packaging plan | `packaging-plan-2026-10-17.md` | Modelfile definitions and local offline packaging scripts. |
| Answer quality judge | `answer-quality-judge-plan-2026-10-15.md` | Rubric calibration and defect-labeled answer evaluation. |

## Measured vs Assumed

- **Measured (2026-10-18):** 385/385 unit tests green across 22 suites; 60/60 Hard Benchmark on `nekohon_x3`; 32/35 on `adrian-eval.py`; 23/30 on `crossbook-evil-eval.py`; R15 latency speedups (`_POSTINGS_CACHE` 45,000x, `_uvec` 2.6x, `_SORTED_WMAP_CACHE` 3.5x, GZIP 71.7% smaller); 0 leaks on `secret-scan.py`.
- **Assumed:** Long-term memory scaling beyond 6 turns in a single margin card; user preference between Shelf view and Grid view on initial library launch.
