# GLOSSARY — ask-this-book

Plain-language definitions for the vocabulary this repo runs on. Written for
both readers and agents. When a term's exact meaning matters, the
authoritative doc is named.

## Product

- **answer mode** — the app's default: the model answers from the shown
  passages in the quote-first shape (since the 2026-10-15 alignment it is
  served the same trained prompt as ask mode); its `[Ch. N]` tags become
  citations; quotes the passages cannot back are stripped
  (`answer.py: respond`).
- **ask mode** — the highlight path: the model must quote one sentence
  verbatim; a failed check is a refusal (`answer.py: ask`).
- **refusal** — exactly `Not in this book.` (`GOAL.md`). It means the book does
  not cover this, or covers the topic but not the person the claim is
  attributed to (`answer.names_absent_person`, checked before generation in
  both `ask` and `respond`); never "I didn't understand you".
- **citation** — `[Ch. N]` plus a quote that must appear verbatim in the named
  passage.
- **passage / chunk** — one indexed piece of the book; `chunk_id` like
  `ch06-011` is chapter 6, 11th chunk.
- **pin** — the historical chunk id recorded on capture forms and in
  `battery-pins.json`; a note, not the gate — the battery passes when the
  cited passage carries the question's terms
  (`artifacts/harnesses/fair_cite.py`).
- **canonicalization** — repairing a bare user phrase into a question
  ("watermark" -> "What is watermark?"); the app shows it as `Asked as: ...`.
- **Read as:** — the app's note when what it understood differs from what was
  typed (e.g. a typo repair).
- **comparison branch** — the `respond` path for compare/difference questions
  (`How does A compare to B?`, `What is the difference between A and B?`): it
  keeps both sides, retrieves a missing side, quotes the book's contrast
  sentence, and asks `COMPARE_SYSTEM` for a gloss naming both
  (`answer._comparison_body`).
- **contrast sentence** — a verbatim book sentence that names both sides and
  carries a contrast marker (`unlike`, `whereas`, `in contrast`, `difference`, ...);
  the preferred citation for a comparison (`answer._comparison_quote`).
- **half-covered comparison** — the book covers one side but not the other; the
  answer quotes the covered side and says the other is not mentioned, with no
  invented attributes (`answer._half_covered`).
- **heading glue** — a quote that starts with the chunk's chapter title or
  subtitle because a sentence splitter crossed a line break; rejected as a
  quote (`answer._starts_with_heading_line`, `_strip_leading_heading_lines`).
- **follow-up gloss template** — the deterministic
  `In <heading>, <entity> connects to this topic: ...` fallback. It now runs only
  when no coherent live gloss exists and never overwrites a live model answer
  (`answer._ensure_answer_gloss`).
- **retry** — the engine's one `[Ch. ` prefill retry for an uncited reply or
  a false refusal; kept only when a citation's quote appears verbatim in a
  passage, so a hit can replace a refusal with a cited answer. Every failure
  path keeps the original; in the streaming UI a discarded draft shows as a
  **reset** (`answer._retry_uncited`).
- **reader payload** (`GET /chunks`) — the book as the reader pane needs it:
  chunks in reading order, no vectors, the leading heading line stripped,
  figures as cards with their real pixel size (`retrieve.chunks_payload`).
- **streaming frames** (`stream=1` on `POST /ask`) — NDJSON lines: `token`
  (text as it is written), `reset` (a draft was discarded), `final` (the same
  body the non-stream path returns), `error`.
- **reset / the hold** — the engine discards provisional drafts itself: tokens
  stream only for the generation whose text becomes the answer (the `[Ch. `
  retry, ask's main generation), so the pane shows one continuous stream; the
  `reset` frame still marks a discarded draft and usually arrives before
  anything was shown.
- **the lens** — select text in the reader → the ink pill at the selection; a
  typed question is an `ask`, an empty one runs `explain` on the passage
  (`web/components/Lens.tsx`).
- **margin card** — the anchored answer beside its passage, streaming, shown
  only when the margin fits (`web/components/MarginCard.tsx`).
- **citation jump** — clicking a `[Ch. N]` chip scrolls the book pane to the
  cited block and marks the quote (whitespace-insensitive search; the marked
  characters are the quote's own words).
- **the panes** — the frontend's two columns: the book (reader) and the ask
  box; the Next.js app under `web/` — `web/README.md`.
- **Highlight Intent Engine** (`intent.py`) — sub-millisecond offline classifier
  categorizing text selections into `CONCEPT_TERM`, `VAGUE_FRAGMENT`,
  `MULTI_SENTENCE_PASSAGE`, or `AUTHOR_QUESTION` to route intent and dynamically
  synthesize context-aware follow-up chips.
- **Passing-Mention Grounding** — detection mechanism in `intent.py` ensuring
  that when a technical term is only mentioned in passing within a selected
  block, the engine grounds definitions and follow-ups in the book's core
  expository passages rather than incidental fragments.
- **Bidirectional Quote-Gloss Alignment** — quote-gloss ranking in `answer.py`
  ensuring that cited excerpts and explanatory glosses align mutually with the
  question's entity and semantic focus, filtering incoherent drafts and
  normalizing casing.
- **Direct-DOM Margin Physics** — 60/120fps direct DOM manipulation using
  `requestAnimationFrame` for drag, 2D resize, and viewport clamping of reader
  margin cards, bypassing React state overhead during motion.
- **Live SVG Leader Line** — dynamic cubic-bezier connector rendered in SVG
  (`updateLeaderLineDOM`) visually tethering the reader highlight marker to its
  corresponding margin card in real time.
- **Figure Deduplication** — reader state mechanism that suppresses redundant
  figure attachments across consecutive turns in a conversation thread,
  offering collapsible toggles instead of repeating identical diagrams.
- **NekoHon (`猫本`)** — the local-first multi-book reading companion branding,
  pairing an interactive cloth-bound wooden bookcase with local Ollama
  distillation and marginalia reading.
- **Multi-Book Catalog** (`data/books.json`) — catalog metadata defining the
  active library (`fde`, `quantization`, `ddia`), mapping book identifiers to
  chapter counts, chunk counts, figure directories, and extracted cover art
  endpoints.
- **Bookplate Spread** — the `EX LIBRIS · NEKOHON` two-leaf cover modal, no
  longer in the current UI; no component renders it, and only its CSS remains
  (`web/app/ledger.css`).
- **Gzip Chunk Cache** (`CHUNKS_GZIP_CACHE`) — engine-level in-memory
  pre-compressed GZIP cache for `GET /chunks`, reducing HTTP payload size from
  1.14 MB down to 328 KB (71.7% network reduction).
- **Unit-Vector Dot Product** (`_uvec`) — pre-normalized 768-dimensional unit
  vector cache enabling dense cosine ranking via raw dot products without
  per-query Euclidean norm calculations, speeding up ranking from 51.69 ms to
  19.75 ms (2.6x).

## Models and training

- **teacher / student** — the big model that writes training answers vs the
  small model that ships. The current teacher is **Qwen3.8-27B**, captured on
  Colab, never served here. **`qwen2.5:7b` is the original teacher** and the
  fallback answerer — not the current one. **`nekohon_q35_2b` is the student.**
  Do not author evaluation questions with the 7B: it reuses the passage's own
  wording, so its questions measure copying rather than retrieval.
- **distillation** — here: the teacher writes answers and the student learns
  from those answers as *text* (not from the teacher's probability
  distribution, which is why the classic capacity-gap effects mostly don't
  apply).
- **capture** — running the frozen app prompts through the teacher to produce
  training answers. **Recapture** — doing that again for the existing training
  rows with a new teacher.
- **card / form** — a training card is one (question, expected answer) pair; a
  form is one way of asking (bare, shorthand, order flip, ...).
- **expect** — per capture row: `cited` (must answer with a citation) or
  `refusal`.
- **q4 / q8** — quantization levels of the shipped GGUF (~4-bit / 8-bit
  weights). q4 is the default; q8 was measured as a wash.
- **epoch / presentations** — one epoch = one pass over the training set;
  "presentations" = rows x epochs (the budget held at ~1968).
- **LoRA** — the small trainable adapter used to finetune; the app loads the
  merged GGUF.
- **nekohon_q35_2b_x3_2e** — 1.9B parameter Qwen3.5-2B distilled student model
  (1.31 GB Q4_K_M GGUF), x2f recipe on the 844-row corpus, stopped at 2 epochs
  (best validation), exported 2026-10-24; the desktop engine default.
- **nekohon_q35_2b** — the first Qwen3.5-2B run, 417-row x2f corpus, 5 epochs
  (1.31 GB Q4_K_M); sealed 25/30; kept as a candidate and revert.
- **nekohon_x3** (alias `smallbook_x3`) — 3.1B parameter Qwen2.5-based distilled
  student model (1.93 GB Q4_K_M GGUF), trained via Wide-LoRA (r=32, alpha=64) on
  an 844-row 7-layer corpus; the desktop default 2026-10-17 to 2026-10-24 and
  still the one-flag revert.
- **nekohon_x3_mobile** — 1.5B parameter edge companion student model (986 MB
  Q4_K_M GGUF), trained on the same 844-row distillation corpus; delivers 100%
  parity across all gates with 0.58s mean latency for low-resource environments.

## Testing

- **sealed suite** — the 30 exam items
  (`artifacts/datasets/sealed-2026-10-24.jsonl`), never trained on (0/27 gold
  chunks in training); a changed sha or a near-match fails
  `tests/test_eval_leakage.py`.
- **gate** — the pre-registered pass/fail rules for adopting a model: six
  suites totaling 175 items (battery ask 10, battery answer 10, hard bench 60,
  adrian 35, sealed 30, crossbook 30), with citations judged by their content
  (`artifacts/reports/test-fairness-2026-10-24.md`,
  `artifacts/harnesses/fair_cite.py`).
- **battery** — the scripted app checks: 18 asks in ask mode (10 golden, 3
  typos, 4 probes, plus France), 22 in answer mode with four coherence probes
  (`artifacts/harnesses/step2-battery.py`).
- **loop** — a generation that stops only at the token cap, or repeats a
  5-word phrase 3+ times (`repeat5`).
- **judge** — an LLM that grades softer qualities; cloud
  `muse-spark-1.3-contributor` by default, local `granite4.1:8b` with
  `JUDGE_BACKEND=ollama`. Deliberately not part of the adoption gate
  (`artifacts/harnesses/judge.py`).
- **owner probe / visible ten** — the user's own messy-query tests;
  exploratory, not gates.
- **contamination probe** — checks training rows against bench questions for
  near-twins.
- **adrian-eval.py** — 35 real-world multi-turn conversational evaluation scenarios
  spanning 97 HTTP turns across highlight refinements, live pill clicking, lazy
  queries, whole-book topic shifts, ungrounded false premises, and prompt injections
  (32/35 passed, 91.4% overall).
- **crossbook-evil-eval.py** — 30 cross-book adversarial multi-turn evaluation
  scenarios across 66 requests spanning `fde`, `quantization`, and `ddia`
  (24/30 baseline; 26/30 for `nekohon_q35_2b` in the fair run).
- **SIMPLIFY_RE fast-path** — regex-driven simplification route in `answer.py`
  synthesizing accessible grounded glosses directly from prior turn anchors in ~850 ms.
- **4-layer RAG scorecard** (`artifacts/harnesses/fair-eval.py`) — benchmark summary
  that separates overall pass/fail into four stages: retrieval hit rate in top-5
  `shown_passages`, generation pass rate when a gold passage is shown, refusal trap
  defense (pre-LLM guards vs model refusals), and latency/multi-call overhead.


## Repo

- **runtime trace** (`observe.py`, `artifacts/runs/traces.jsonl`) — one local JSON
  line recorded per HTTP request or `fair-eval` item, capturing query rewrites,
  pre-LLM guards, `shown_passages`, Ollama TTFT/tok/s/VRAM load time, and post-LLM
  quote repairs without altering the HTTP response shape (`OBSERVE=0` disables).
- **trace_inspect.py** (`artifacts/harnesses/trace_inspect.py`) — CLI reader for
  `traces.jsonl` and `fair-eval` runs (`--failures`, `--slow`, `--stage`, `--id`,
  `--compare`, `--reconstruct`, and `--json` for agents).
- **shown_passages** — the exact ranked list of passages placed into the model
  prompt after canonicalization, typo repair, RRF fusion, and phrase boosting;
  checked first when debugging whether search or generation caused a miss.
- **TTFT** (time to first token) — milliseconds from sending the prompt to Ollama
  until the first streamed token arrives (`llm.ttft_ms` in traces).

- **artifact** — anything under `artifacts/`: probes (scripts that run
  things), reports (the why + verdicts), evidence (raw run outputs). Index +
  rules: `artifacts/README.md`; rot check: `python artifacts/prune.py --plan`.
- **harness** — a reusable measuring tool (battery, sweeps, groundedness,
  judge, secret scan).
- **the contract** — the frozen `POST /ask` request/response shape; changing
  it needs an explicit yes.
- **engine-reset rule** — a running server serves the code and model it
  loaded at start; restart after any change and check `/api/ps`.
