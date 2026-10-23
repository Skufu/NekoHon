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
- **refusal** — exactly `Not in this book.` It means "the book does not cover
  this" — never "I didn't understand you" (`docs/GOAL.md`).
- **citation** — `[Ch. N]` plus a quote that must appear verbatim in the named
  passage.
- **passage / chunk** — one indexed piece of the book; `chunk_id` like
  `ch06-011` is chapter 6, 11th chunk.
- **pin** — the chunk id a question is expected to cite (used by the battery
  and by capture forms).
- **canonicalization** — repairing a bare user phrase into a question
  ("watermark" -> "What is watermark?"); the app shows it as `Asked as: ...`.
- **Read as:** — the app's note when what it understood differs from what was
  typed (e.g. a typo repair).
- **retry** — the engine's one `[Ch. ` prefill retry for an uncited
  answer-mode reply; kept only when a citation validates as verbatim text.
  Monotone: it can only add a citation, never change an answer. In the
  streaming UI its discarded draft shows as a **reset**.
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
- **Bookplate Spread** — the 3D `BookOpen` modal presentation displaying an
  `EX LIBRIS · NEKOHON` vintage bookplate, thumbnail cover art, and passage
  statistics on the left page with reading progress and action controls on the
  right.
- **Gzip Chunk Cache** (`CHUNKS_GZIP_CACHE`) — engine-level in-memory
  pre-compressed GZIP cache for `GET /chunks`, reducing HTTP payload size from
  1.14 MB down to 328 KB (71.7% network reduction).
- **Unit-Vector Dot Product** (`_uvec`) — pre-normalized 768-dimensional unit
  vector cache enabling dense cosine ranking via raw dot products without
  per-query Euclidean norm calculations, speeding up ranking from 51.69 ms to
  19.75 ms (2.6x).

## Models and training

- **teacher / student** — the big model that writes training answers vs the
  small model that ships.
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
- **nekohon_x3** (alias `smallbook_x3`) — 3.1B parameter Qwen2.5-based distilled
  student model (1.93 GB Q4_K_M GGUF), trained via Wide-LoRA (r=32, alpha=64) on
  an 844-row 7-layer corpus; delivers 100% on the 60-item Hard Benchmark and
  24/24 on golden highlights as the desktop engine default.
- **nekohon_x3_mobile** — 1.5B parameter edge companion student model (986 MB
  Q4_K_M GGUF), trained on the same 844-row distillation corpus; delivers 100%
  parity across all gates with 0.58s mean latency for low-resource environments.

## Testing

- **sealed suite** — the 21 exam items (`artifacts/datasets/sealed-forms.json`)
  never trained on; near-matches abort a build.
- **gate** — the pre-registered pass/fail rules for adopting a model; **gate
  item 2** is the sealed-suite bar vs the 7B.
- **battery** — the 21 scripted app checks with pins
  (`artifacts/harnesses/step2-battery.py`).
- **loop** — a generation that stops only at the token cap, or repeats a
  5-word phrase 3+ times (`repeat5`).
- **judge** — an LLM that grades softer qualities (local granite by default;
  the cloud muse model only when explicitly enabled). Deliberately not part of
  the adoption gate.
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
  (23/30 passed, 76.7% overall).
- **SIMPLIFY_RE fast-path** — regex-driven simplification route in `answer.py`
  synthesizing accessible grounded glosses directly from prior turn anchors in ~850 ms.


## Repo

- **artifact** — anything under `artifacts/`: probes (scripts that run
  things), reports (the why + verdicts), evidence (raw run outputs). Index +
  rules: `artifacts/README.md`; rot check: `python artifacts/prune.py --plan`.
- **harness** — a reusable measuring tool (battery, sweeps, groundedness,
  judge, secret scan).
- **the contract** — the frozen `POST /ask` request/response shape; changing
  it needs an explicit yes.
- **engine-reset rule** — a running server serves the code and model it
  loaded at start; restart after any change and check `/api/ps`.
