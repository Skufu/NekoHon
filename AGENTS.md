# AGENTS.md — ask-this-book

Agent entry point for this repo. Read `GOAL.md` (the goal + constitution, the
stable layer), then this file, then `BUILD_PLAN.md` (the living build plan;
renamed from `README.md` during the `epub-local` repo prep — references below
to "the README" mean it) and the current phase brief in `artifacts/`. The
human-facing front page is `README.md` (overview, quickstart, tests; this file
stays the rules-and-state authority).

## What this is

An offline book companion. One EPUB ("Fundamentals of Data Engineering",
`book_id` = `fde`) is ingested into a JSON index, passages are retrieved with a
local embedder, and questions are answered from the retrieved passages in two
modes: `answer` (quote-first answers with `[Ch. N]` citations; the window
default; since the 2026-10-15 alignment it is served the same trained prompt
as `ask`) and `ask` (a checked quote plus a gloss). Cited figures still attach. All
inference is local Ollama on `127.0.0.1:11434`. No cloud APIs, no database
server.

## Where things live

- `GOAL.md` — goal + constitution (stable). `BUILD_PLAN.md` — living plan.
  `README.md` — human front page. `GLOSSARY.md` — the vocabulary in plain
  words (read it when a term is unclear).
- Engine (stdlib only): `server.py` (HTTP + the frozen `POST /ask`),
  `answer.py` (ask/answer modes, the `[Ch. ` retry), `retrieve.py` (index +
  search), `ingest.py` (EPUB -> index), `preprocess.py` (+ `vendor/`, the one
  allowed preprocessing dependency), `canonical.py`, `prompt.py` (model tags
  + system prompts), `fusion.py`, `keywords.py`, `readings.py`,
  `captions.py`, `figures.py`, `agentic.py` (prototype, not wired).
- Checks: `preflight.py` (readiness), `verify_index.py` (index hygiene),
  `tests/` (`python -m unittest discover -s tests`).
- `artifacts/` — everything dated and measured: `probes/` (scripts that run
  things), `reports/` (the why + verdicts), `evidence/` (raw run outputs),
  `harnesses/` (battery, sweeps, groundedness, judge, secret scan),
  `datasets/` (bench, sealed suite, training lists). Index + rules:
  `artifacts/README.md`; rot check: `python artifacts/prune.py --plan`.
- Gitignored, machine-local: `books/`, `data/` (index, finetune data, model
  artifacts), `artifacts/runs/` (server logs + start scripts).

## Goal vs plan (read `GOAL.md`)

`GOAL.md` holds the goal and the constitution — the only parts that rarely
change. `BUILD_PLAN.md` and the dated reports are tactics that expire. Two
rules follow:

- **Only `GOAL.md` can block work.** A rule in a dated doc never blocks a
  mean; it is a hypothesis, superseded by a new dated note. Lock the goal, not
  the method.
- **Every "stop and say" is a verification gate, not a permission gate.**
  Change the tactic, then re-run the gates (battery, pins, trial probes). Do
  not ask permission to replace a means; do not change one without re-running
  the gates.

**Constitution (short copy of `GOAL.md` — keep in sync):** local only (Ollama
on localhost; one eval-only cloud-judge exception) · stdlib only (one vendored
preprocessing exception) · grounded (quotes come from the book; repairs never
invent text) · refusal is exactly `Not in this book.` · measured, not asserted.
Only this list can block work.

## Hard rules (do not break)

- Python stdlib by default — the whole standard library is fair game, e.g.
  `zipfile`, `json`, `html.parser`, `xml.etree.ElementTree`, `urllib`,
  `http.server`, `pathlib`, `re`. One exception (user decision 2026-10-13):
  text preprocessing may use standard third-party tools — stemmers, stopword
  lists, normalization tables — vendored into the repo with their license
  (a `vendor/` copy beats a pip dependency; the app stays offline). Record a
  download's megabyte count before pulling. Everything else stays stdlib: no
  `requirements.txt`, no numpy. If a non-preprocessing task seems to need a
  package, the task is wrong — redesign it.
  `urllib` may talk only to this machine: Ollama at `127.0.0.1:11434`, and the
  engine itself. No other host — one exception, evaluation only (user
  direction 2026-10-13): the eval/judge artifacts may call a configured cloud
  judge when `JUDGE_BACKEND=openai` is set explicitly; the key comes from the
  environment or `JUDGE_API_KEY_FILE` and is never committed; the engine,
  server, and batteries never take this path.
- No pickle, no marshal, no shelve, no sqlite. Records are JSON. Reload with
  the stdlib `json` module. Pictures stay as files under `data/figures/`.
  Bake-off indexes are `data/index.<model>.json`. After the bake-off,
  `data/index.json` is the winner. Do not base64 images into the index.
- Downloads already approved (README Status, 2026-10-11): embedder pulls, and
  Windows runner setup. Everything else still needs an explicit megabyte
  number before the transfer. That includes the book, a Readest clone, an
  Ollama upgrade, and any vision model. Ollama v0.40.3 is already installed
  on this box (upgraded 2026-10-11). A further upgrade is not "runner setup."
- Only four routes: `POST /ask`, `GET /health`, `GET /figures/{id}`, `GET /`.
  No fifth route. `POST /ask` request/response shape is frozen (README
  "Contract"); `mode` is `ask`, `answer`, `explain`, or `quiz`. When
  `refused: true`, `answer` is exactly `Not in this book.` — that sentence,
  period included, and nothing else. In `answer` mode the model's first line
  must be that exact sentence for a refusal; in `ask` mode a line that starts
  that way and then keeps talking is not a refusal.
- Phases are a plan, not a contract. If the plan looks wrong, say so — honest
  architect, not a yes-man. Then change it and re-run the gates (battery,
  pins). Reordering or skipping a phase to serve the goal is allowed; you owe
  the repo a re-run and a plan update, not a permission request (see "Goal vs
  plan").
- `rag-template/` is read-only reference. Never touch its `.venv`. Do not port
  numpy, pickle, BM25, rerankers, or agentic/multimodal code from it.
- Do not commit unless the human asks.
- Reset the engine with the model (user rule 2026-10-14): anytime the answer
  model changes — a new `ANSWER_MODEL` default, an env seam, a new Ollama tag
  — and after any `*.py` edit, restart `artifacts/runs/start-engine.bat`
  before measuring or serving, and check `/api/ps` to confirm the loaded
  model. A running server keeps the code and model it loaded at start
  (measured: a 14:46 server served `smallbook_x2`, uncapped and un-retried,
  through 22:13 while the tree said x2d).
- Improvements must generalize, not fit this book's test set — the system has
  to hold for other books later. No chunk ids, figure ids, chapter numbers,
  query strings, or book ids in the logic modules (`answer.py`, `canonical.py`,
  `captions.py`, `figures.py`, `keywords.py`, `preprocess.py`, `prompt.py`,
  `readings.py`, `retrieve.py`).
  Pins and ids belong in tests, the battery, and docstrings.
  `tests/test_generalization.py` enforces the literal part. Thresholds are the
  subtler half: a constant is fitted if its stated reason is which known test it
  keeps green (e.g. `RARE_DF = 8` justified by "keeps 'capital' out"), not if it
  falls out of a rule that survives a different book. Say so when you see one.
  Do not quietly tune a constant until a battery run passes.
- Report measured results, not impressions: files changed, exact command, real
  output. If a test fails, say so with the actual failure. An improvement that
  cannot be told apart from luck is not measured: report the before number, the
  after number, and what was held constant.
- Diagrams anywhere (chat, docs, artifacts) are **real mermaid diagrams**
  (they render) — never ASCII sketches. User decision 2026-10-13; the model
  example is `artifacts/reports/system-map-2026-10-13.md`.
- State over prose: inspect live code variables or data lines (e.g.
  `len(PERTURB_SWAPS)`) before quoting metrics from markdown reports. Treat
  documentation, ADRs, status files, and READMEs as unverified claims until the
  source code agrees.
- Verify disk state first: check `git status` or inspect target directories
  before proposing a build action, to avoid proposing work that has already
  shipped or files already built.
- Mechanism precision: distinguish between true n-gram repetition loops and
  boundary continuation length-stops, as their mitigations operate at
  completely different layers (refusal ratio vs `num_predict`).


## Artifacts policy (read before writing to artifacts/)

- Runs write to `artifacts/runs/` (gitignored). Promote a run into
  `artifacts/` only when a doc or commit names it, and add its row to the
  index (`artifacts/README.md`) — the index is the gate.
- Zones (migration landed 2026-10-14; only `prune.py` + `README.md` stay at
  `artifacts/` top level — never add new flat files): `harnesses/`
  (reusable runners), `probes/` (dated one-offs), `datasets/` (eval sets,
  question lists), `reports/` (dated .md findings),
  `evidence/<family>/` (dated outputs, one live twin), `runs/` + `scratch/`
  (gitignored scratch). Full table + path snippet: `artifacts/README.md`.
  History bullets below cite pre-migration flat names; resolve them through
  the index.
- New docs and benchmark outputs carry their date in the name:
  `family-YYYY-MM-DD[-label].ext`.
- One live twin per family: the latest run plus any run a doc names;
  superseding a run means deleting the old one in the same commit that
  supersedes it (numbers folded into the doc first).
- **Staleness gate:** a benchmark or doc dated two or more days ago is
  stale. Do not trust its numbers, do not build on it, do not tune code to
  match it. Re-run it, or ask the user first.
- Prune before docs commits: `python artifacts/prune.py --plan`.

## Current state (update this block when a phase lands)

- Done: Phase 0 (book at `books/fde.epub`), 0b (README corrected for this
  book), 1 (fixture + `server.py` + contract test — green), 2 (ingest).
- Phase 3 nomic smoke is done. `data/index.json` has 1065 chunk vectors and
  111 figure vectors, 768 dims. `python retrieve.py --smoke tests/fixtures/questions.json`
  printed 10/10 top-10 in 5.9 seconds on 2026-10-11. The list is in the README.
  Two hits were rank 7 and rank 8. Do not raise top-k.
- Phase 3b bake-off is done. Table is in the README. Nomic 10/10, Gemma 9/10.
  Gemma missed one figure question and did not win hit@10 by 2. Nomic stays.
  Gemma index: `data/index.embeddinggemma-2.json`. Do not delete it.
- Phase 4 quote check is green on three in-book questions and one refusal,
  2026-10-11, via `answer.ask` on the nomic index. Model: `qwen2.5:7b`,
  4.7 GB, Q4_K_M, pulled after a yes on 4683 MB. Quotes checked:
  CRUD (ch05-019), data ingestion (ch07-002), watermark (ch08-040).
  "What is the capital of France?" returned exactly `Not in this book.`
  The HTTP server was not the thing measured. explain and quiz returned
  the fixture until Phase 6.
- Phase 5 figure attach is in. A figure is added only when a kept passage names
  its number, and the file exists. Measured 2026-10-11: "What is a watermark?"
  returned figure-8-8, file fode_0808.png, 18913 bytes. CRUD returned no figure.
  Score does not attach a figure. The score floor is still unset.
- `GET /` serves `window/index.html`. `GET /figures/{id}` returns the image.
  The page had not been opened in a browser yet. The answer still must not describe pixels.
- Phase 6 explain and quiz are in. Explain treats the highlight as the question
  and still checks the quote. Quiz returns one question plus one key sentence
  from one chunk. The question must not contain the key. No score. No sparring.
  Live 2026-10-11: explain of the CRUD sentence quoted ch05-019. One quiz
  question did not contain its key. The page hides the key behind a button.
  That button had not been clicked in a browser yet.
- Phase 7 gate passed 2026-10-12. Wired machine: the Ethernet cable was
  unplugged for the run; the offline probe (`https://example.com`) returned
  `000`. With the link down, the same watermark ask over HTTP returned
  `refused: false` with the same cited answer as online (first line starts
  `[Ch. 8] "A watermark (Figure 8-8)`), citation `ch08-040`, figure
  `figure-8-8`. netstat: engine PID 26996, Ollama PID 18996, every line
  `127.0.0.1`, nothing foreign; same PIDs online and offline, no restarts.
  Raw log: `artifacts/phase7-offline.log`. This is the first end-to-end
  exercise of the HTTP path. Embeddings and answers are Ollama on localhost;
  models are nomic-embed-text and qwen2.5:7b; no cloud model API; base
  models, no training.
- Window first opened in a browser 2026-10-12: the ask path showed the quoted
  answer and the `figure-8-8` image with caption, live from the engine.
  explain and the quiz "Show the key" button were clicked the same day; both
  worked.
- explain and quiz verified over HTTP 2026-10-12, both `refused: false`, no key
  leak in the quiz question. Latency profile: warm asks ~0.8-1.6 s; the first
  ask after ~5 min idle pays a one-time ~25 s Ollama model load.
- All 10 golden questions run end-to-end over HTTP 2026-10-12: 8 answered with
  a chunk and quote, 2 refused (`Not in this book.`): the storage-cornerstone
  and transformations questions. Retrieval stayed 10/10; the refusals are the
  answer layer. Demo sheet: `artifacts/demo-questions.md`.
- Window shows citation chunk ids under the answer (2026-10-12); on refusals
  they are labeled "nearest misses".
- Post-v1 step 2 (typo tolerance) landed 2026-10-12, amended the same day:
  `spelling.py` repairs one question word when it is absent from the book.
  The prompt repair needs exactly one book word within difflib 0.85 in the
  top passage (CRU, ET). The retry repair uses the whole book's unique best
  and re-searches with the repaired question, kept only when the top score
  strictly improves (atermark: 0.573 -> 0.817, answers ch08-040). Search
  runs raw first, always. Battery 14 asks over HTTP, all pass
  (`artifacts/step2-battery.{log,json}`): golden 10/10 answered and 10/10
  against pins, typos PASS (CRU ch05-019, ET ch07-033, atermark ch08-040),
  France exact refusal; 37 unit tests green; warm asks 0.9-1.4 s.
- Post-v1 step 2 superseded 2026-10-12: `spelling.py` is deleted. It repaired
  the question twice — once for the prompt text, once for a re-search — and the
  reader was answered a question they never asked. `readings.py` keeps one
  reading: a word absent from the book swaps to its closest book word (whole
  book, difflib 0.85, unique best only); the reading is kept only when its best
  dense score strictly beats the literal one, which is a comparison, not a
  tuned cutoff; and the reading becomes the question the model answers. The
  answer states it
  as one line, `Read as: "..."`, so nothing is repaired silently.
  Measured 2026-10-12: atermark 0.573 -> 0.817 (ch08-040), CRU 0.675 -> 0.785
  (ch05-019), France 0.544 -> 0.530 dropped — the refusal is protected by the
  improvement gate, not by the similarity margin (france/franca sits 0.017
  under the cutoff, so the cutoff alone would not be trusted).
  Hints were tried first and failed: six shapes of note (plain, quoted,
  system-level rule, bracket on the question line) all returned exactly
  `Not in this book.` for "What does CRU stand for?" with five passages
  attached; the model needs the reading as the question. Typo probes
  re-measured in-process: CRU/ET/atermark PASS, golden 10/10, France exact,
  MAD ch04-020; 59 unit tests green. HTTP battery not rerun (stale :8000).
- Post-v1 step 3 (label refusal figures) landed 2026-10-12: the window marks
  nearest-miss figures on a refusal "nearby, not an answer"
  (`window/index.html`, `.nearby`); a real answer gets no such label.
- Rare-word boost landed 2026-10-12 (user-approved experiment, `keywords.py`):
  when the question carries a word with df <= 8, the best idf-overlap chunk
  replaces the last dense passage unless it is already present. No model, no
  download; postings build ~0.065 s per ask. Motivated by measurement: the
  flexibility chunk (ch04-012) ranked 51 of 1065 for "what does data
  engineers need to be pragmatic about"; dense search is weak at rare exact
  words ("pragmatic" df=6). Battery 15 asks over HTTP, all pass
  (`artifacts/step2-battery.{log,json}`); the probe answers ch04-012 with the
  flexibility sentence. Golden pins #5/#10 tightened to ch06-001 / ch02-025
  (the span fix made them answer). `retrieve.py` and the smoke path are
  untouched; `explain` inherits the boost through `ask`.
- Dense band added to the boost 2026-10-12, superseding the RARE_DF safety.
  The boost used to lean on `RARE_DF = 8` to keep "capital" (df=10) away from
  the France question — a constant fitted to this book's word counts. Now the
  promoted chunk must sit in the dense top `RANK_BAND` of the corpus, or
  nothing is injected; no rank map is no evidence and fails closed.
  `retrieve.rank_chunks` is the shared ranking and `dense_rank` exposes it.
  Measured: with the df gate forced open (RARE_DF=40) and the same rank map,
  the France candidate ch02-068 (dense rank 695) is rejected at band 0.10 and
  injected at band 1.00 — the band is the deciding gate, not the df. The
  France ask refuses exactly with RARE_DF at both 8 and 40. Positives keep
  working: pragmatic -> ch04-012 (rank 51), multicloud -> ch04-038 (rank 1),
  watermark -> ch08-040 + figure-8-8; golden 10/10, MAD -> ch04-020. Cost: the
  rank map adds one embed plus a full cosine pass (~0.11 s), paid only when the
  rare gate fires. `embedding` vectors and `data/index.json` untouched.
- RANK_BAND moved 0.10 -> 0.20, 2026-10-12, and the reason is worth keeping.
  The 0.10 band silently dropped the MAD case: the "mad" anchor is ch04-019 at
  dense rank 140 (13.1%), so boost stopped promoting it, the passage set the
  model received changed, and "MAD data landscape" began quoting "Even
  relatively successful technologies often fade into obscurity…" out of the
  right chunk instead of the (MAD) landscape sentence — measured three times,
  deterministic, and proven causal by putting ch04-019 back: with it the MAD
  sentence returns. The battery caught it (probes FAIL, chunk pin still
  ch04-020). 0.20 admits every measured legitimate anchor and still refuses
  France by more than 3x; the safe range is now 13.1% to 65%. Moving a constant
  is a judgment, not a fit, and the judge here is the band's purpose: it exists
  to exclude the tail, and 13.1% is not the tail. Do not move it again without
  a case outside that range. Battery rerun over HTTP 2026-10-12 on a fresh
  server (single listener, PID checked): golden 10/10 answered, typos PASS,
  probes PASS (MAD ch04-020), France exact refusal, battery PASS. 59 unit tests
  green. Warm asks 0.4-1.2 s.
- One text seam landed 2026-10-12 (`preprocess.py`): `tokens()`/`words()` are
  the only tokenizers, used by `postings`, `anchor_words`, `rare`, `boost`,
  and the readings, so the index side and the query side cannot fold
  differently. Before this, five call sites each ran their own `.lower()` over
  the same regex — one forgotten fold and the channels stop matching silently.
  `normalize()` is the dense-channel view: NFKC, then horizontal whitespace
  runs folded to one space, newlines kept because a chunk's first line is its
  heading. It is applied in `retrieve.format_input` on both sides, so the
  document and the query travel together — turning it on without rebuilding
  the index leaves the query view and the stored vectors in different spaces.
  `tests/test_preprocess.py` asserts that `postings()` keys equal `words()`
  over the same text, that four casings of one word all fire the rare gate, and
  that normalize is NFKC and idempotent. 66 unit tests.
- Normalized index built and switched in 2026-10-12 (`data/index.json`; the old
  build kept as `data/index.pre-normalize.json` for a reproducible compare).
  Re-embedding 1065 chunks + 111 figures took 14.5 s on local Ollama. Measured
  before the switch: NFKC changes 3 chunks of 1065 (ch02-046, ch08-090,
  ch11-014); their vectors move to cosine 0.9957-0.9978; 1062 of 1065 vectors
  are byte-identical to the pre-normalize build; the top-5 did not change on
  any of 17 probe questions and the largest top-5 score delta was 0.0. Real but
  inert on this book; switched for consistency (the query side normalizes) and
  for the next book, whose EPUB may carry ligatures, non-breaking spaces, or
  full-width characters. Battery rerun over HTTP on a fresh server: golden
  10/10, typos PASS, probes PASS, France exact, battery PASS. 68 unit tests.
- Chunk-boundary audit 2026-10-12, measured (the cause is in `ingest.py`): 373
  of 1013 chunks (37%) start mid-sentence and 43 (4%) end without `.`/`!`/`?`;
  sizes run 91 / 978 / 1333 / 1400 (min/median/p90/max). Two causes, both in
  `_section_chunks`: a paragraph longer than the cap is cut at
  `text.rfind(" ")` — a space, not a sentence end — and the overlap prepends
  `_tail(...)`, a word-count fragment of the previous chunk, so every
  overlapped chunk starts mid-sentence by construction. Word-count overlap does
  not fix this; it is one of the two causes. The fix is sentence-boundary
  packing with sentence-aligned overlap. Late chunking and ColBERT are
  vector-side retrieval tricks — they cannot change the chunk text that gets
  cited, and neither is available here (Ollama returns one vector per input;
  the hard rules forbid rerankers and numpy). Not started: re-chunking changes
  every chunk id, so it re-baselines the battery, the demo sheet, and every
  pin. Documented limit kept: digits are not tokens ("S3" reads as "s"),
  because widening it moves every df count and the rare gate rides on those.
- Sentence-boundary chunking written 2026-10-12 (`ingest.py`), built into
  `data/index.sentence.json` and NOT yet live — `data/index.json` is still the
  old build, on purpose. Boundaries measured before/after:
  mid-sentence starts 373 -> 0, chunk ends cut mid-sentence 25 -> 0, open ends
  43 -> 41 (the rest are list-intro colons and citation lists, not cuts), chunk
  count 1013 -> 990, sizes 91/978/1333/1400 -> 83/978/1333/1399. No fixture
  phrase was split across a boundary, and the retrieval smoke is 10/10 on both.
  What changed: `_pieces()` packs sentences to the cap instead of cutting at
  `rfind(" ")`, and the overlap is `_sentence_tail`, whole trailing sentences
  from the chunk body, instead of a word-count tail.
  Two bugs of mine, both found by the audit and fixed: `_sentence_tail`
  returned the whole previous chunk when the text has no sentence ends (a
  citation list), so chunks grew 1200 -> 5700 in a chain; and taking the tail
  from the chunk instead of the body repeated the heading inside the next
  chunk. A trailing sentence longer than the overlap limit now yields nothing.
  Re-derived battery pins (ch08-040 -> ch08-039 for watermark and atermark,
  ch02-018 -> ch02-019 batch versus streaming, ch02-025 -> ch02-027
  transformations, ch04-038 -> ch04-037 multicloud; ch05-019, ch07-002,
  ch05-020, ch06-001, ch02-005, ch03-013, ch07-033, ch04-012 and ch04-020
  unchanged) and SWITCHED IN the same day: `data/index.json` is now the
  sentence-chunked build, the previous one is kept as
  `data/index.pre-sentence.json`, the other intermediates are deleted.
  Battery rerun over HTTP on a fresh server with the new pins: golden 10/10
  answered and 10/10 against pins, typos PASS, probes PASS, France exact,
  battery PASS; warm asks 0.5-1.2 s. 77 unit tests at that point.
  Two quality deltas the battery could not see were found by reading the
  measured quotes rather than the pins, and both are fixed — see the
  answer-layer bullet above: the transformations quote no longer opens with the
  chunk's heading line, and the atermark answer attaches one figure, not three.
  `artifacts/demo-questions.md` was corrected the same day.
- Chunk metadata added 2026-10-12 (`ingest.py`): every chunk now carries `doc`
  (the EPUB file, e.g. `OEBPS/ch04.html`), `section` (the heading trail, e.g.
  "Chapter 6. Storage > Object Storage"), `anchor` (the heading's own id) and
  `figures` (the figure ids the chunk names, derived with the same rule the
  answer layer uses). The trail and ids are metadata only: joining them to the
  text would move every vector, so the rebuild reused the existing vectors and
  proved it — 1042 chunk ids and texts byte-identical to the build they
  replaced, all 111 figure captions identical, no vector recomputed, index
  +140 KB. Battery rerun with the SAME pins: golden 10/10, typos PASS, probes
  PASS, France exact, battery PASS. That is the payoff of metadata that never
  enters the text.
  `anchor` is empty for all 1042 chunks, and that is honest rather than broken:
  this EPUB's headings carry no id (0 of 59 in ch04). The nearest-preceding
  anchor was measured as a fallback and rejected — only 9 of 51 headings have
  one within 300 characters, and the ones they have are stray footnote markers
  (`#ch01fn42-marker`) and LibreOffice auto ids (`#idm45075143877808`). A wrong
  deep link is worse than none. The field stays wired for a book that does
  carry heading ids. Previous build kept as `data/index.pre-metadata.json`.
- Flake worth knowing, seen once 2026-10-12: one battery run refused the
  multicloud probe while citing ch04-037, the correct chunk. The same question
  answered correctly twice in-process and 5 of 5 in isolation over HTTP, and
  the immediate battery rerun passed. Under 17 sequential requests the local
  model is not bit-exact. Treat a single red probe line as suspect until it
  repeats, and re-run before believing it. 79 unit tests.
- Two answer-layer warts fixed 2026-10-12 (`answer.py`), both measured.
  (a) A quote that opens with the passage's heading line drops it. The
  transformations answer read "Key considerations for the transformation phase
  Logically, we treat..." and the insert-only answer read "Insert-Only The
  insert-only pattern retains...". The test is what follows the heading: a
  heading that ran on into its own sentence leaves a lower-case remainder, and
  one that was the sentence's subject leaves a bracket or lower case, so only a
  genuine new sentence in upper case gets the heading dropped — "Modularity
  (Figure 4-5) is..." and "Storage is the cornerstone..." keep their subject.
  The trim runs after the anchor-paragraph expansion, because that path
  replaces the quote and re-introduces the heading; the earlier placement
  silently did nothing, which the measurement caught and the unit tests did
  not.
  (b) A figure attaches only from a passage the answer cited, not from every
  kept passage. MAD 2 figures -> 1 (figure-4-1), storage 3 -> 1 (figure-6-1),
  atermark 3 -> 1 (figure-8-8); refusals keep the "nearby" labelling. Cost of
  the narrower rule: the modular-services answer now cites a neighbouring chunk
  that names no figure, so it shows none where it used to show figure-4-5.
  Battery PASS on all four lines after both.
- Gloss forcing tried and REVERTED 2026-10-12. The plan promises one line of
  gloss after the quote; measured, 15 of 17 answers skip it. A FORMAT_REMINDER
  asking for a line beginning "In plain words:" put a gloss into 10 of 10
  answers and broke the golden set to 6/10 — four refusals, because the model
  refuses rather than emit a format it cannot satisfy. Probes went red too.
  Reverted; battery back to PASS on all four lines. Three attempts to steer
  this model with instructions have now failed the same way (definition verbs,
  the CRU spelling note, the gloss); do not try a fourth without changing the
  model. `FORMAT_REMINDER` and `SYSTEM` are back to their committed text.
  83 unit tests.
- Quote-check tag-slip fix landed 2026-10-12: when the model writes the wrong
  `[Ch. N]` tag but the quoted sentence is verbatim in another attached
  passage, the check matches that passage; the answer's chapter is rebuilt
  from the hit. A quote in no attached passage still refuses (unit test).
  Measured motivation: "Data engineers need to be pragmatic about?" returned
  the right sentence tagged `[Ch. 1]` — the ch04 passage sits last of five;
  alone or first it tags `[Ch. 4]`. Battery 16 asks over HTTP, all pass
  (`artifacts/step2-battery.{log,json}`); both pragmatic phrasings pin
  ch04-012. 42 unit tests green.
- Figure-reference normalizer landed 2026-10-12 (`answer.py`, quote check):
  "(Figure N-N)" is folded out of both the quote and the passage before the
  match. The model drops the parenthetical when it copies and the book puts it
  mid-sentence, so the exact match failed and the span fix kept the longer
  remaining run. That is how "Where does storage sit in the data engineering
  lifecycle?" answered "and underlies its major stages—ingestion,
  transformation, and serving" while the model had actually written the whole
  sentence. Both sides are stripped: the watermark quote keeps "(Figure 8-8)"
  and still matches. Measured after: storage -> ch06-001 quotes "Storage is the
  cornerstone of the data engineering lifecycle and underlies its major
  stages—ingestion, transformation, and serving"; modular services -> ch04-069
  keeps "Modularity" as its subject. The quote contract is now "verbatim
  except figure references" — the one place the check is not literal, recorded
  here on purpose. Golden 10/10, France exact refusal, MAD ch04-020, quiz still
  refuses key leaks; 60 unit tests green.
- Multi-quote experiment (list questions) tried and REVERTED 2026-10-12: one
  `FORMAT_REMINDER` line asked for up to three sentences from a passage when
  the question asks for a list. It worked for the multicloud case (answer
  included the "dizzying array... diabolically complicated" sentence) but
  broke the battery: watermark and atermark returned bare refusals, the
  insert-only ask quoted a different chunk (ch08-110), and one pragmatic
  probe refused in the served run. Reverted; battery 17 asks all pass again.
  Reverted; battery 17 asks all pass again. The parser keeps multiple
  [Ch.] lines (unit test: two quotes from one passage both kept); the
  blocker was prompt steering, not the format.
- List-quote expansion landed 2026-10-12 (`answer.py`): when the question
  names a list word (advantages, disadvantages, reasons, types, steps, ...),
  the verified quote is expanded to the whole passage paragraph that held
  it. Paragraph text is passage text, so the quote check holds by
  construction; the model's prompt is untouched (the prompt-steering route
  stays dead). The multicloud case now answers the full disadvantages
  paragraph of ch04-038 (egress costs, complexity, "dizzying array...
  diabolically complicated"). Battery 18 asks over HTTP, all pass
  (`artifacts/step2-battery.{log,json}`); 83 unit tests green.
- Caption-seeded recall landed 2026-10-12 (`captions.py`, post-v1 retrieval):
  when a figure caption outscores the best chunk, the best-scoring chunk that
  names that figure is seeded first in the passage set (chosen by cosine, not
  position). It runs before the rare-word boost, so the two fill opposite ends.
  Fixes the class the boost missed: for "MAD data landscape" the boost injected
  ch04-019 last (position tie) so the model quoted the data-mesh passage even
  though figure-4-1's caption "Matt Turck's 2021 MAD data landscape" scores
  0.751 vs ch03-102 at 0.671, and ch04-020 (dense rank 35) holds the sentence.
  Now the ask quotes ch04-020 and attaches figure-4-1. Measured in-process via
  `answer.ask` on the nomic index: golden 10/10, France exact refusal, MAD probe
  ch04-020. 48 unit tests green. HTTP battery carries the MAD probe (ch04-020)
  but was not rerun same day (a stale :8000 server was live); evidence in
  `artifacts/mad-caption-probe.md`.
- Definition-first ordering tried and reverted 2026-10-12 (negative result).
  The prompt route and the code route both failed. A prompt rewrite naming the
  definition verbs (is, are, includes) made "monolith" quote ch03-057 but made
  "What is a watermark?" refuse — its definition reads "A watermark (Figure
  8-8) is a threshold", so the rigid verb list does not survive a parenthetical.
  A deterministic `definitions.py` that moved the defining passage to the front
  (bare-term questions only) reordered correctly but changed nothing: for
  "monolith" the model still skipped ch03-057 (rank 1) and quoted ch03-058's
  mid-sentence fragment instead — worse than the pros paragraph it quoted before.
  Baselines measured: watermark, CRUD, microservices were already definition
  quotes and were unaffected; only "monolith" changed, for the worse. Module and
  its 7 tests deleted; prompt.py and the golden set back at 10/10. Do not retry
  prompt-level definition forcing without a model change.
- The real cause of the fragment class: 373 of 1065 chunks (~35%) start
  mid-sentence. Measured 2026-10-12 with `retrieve.chunk_title` (body's first
  character lowercase): e.g. ch01-003 begins "and operate the organization's data
  infrastructure…", ch03-058 begins "of unknown consequences with other areas of
  the monolith." A model quoting such a chunk produces a passing but nonsensical
  fragment, which is how "monolith" answered ch03-058. Fixing this means
  re-chunking on sentence boundaries and re-embedding all 1065 chunks (Phase 2
  territory) — not approved.
- Span fix landed 2026-10-12: when the model edits a near-verbatim copy, keep
  the longest word-for-word run (difflib, floor 40 chars) instead of refusing.
  Measured via `answer.ask` on the nomic index: 12 asks answered, France
  refused exactly. The two old golden refusals now answer (storage ch06-001,
  transformations ch02-025). CRU answers ch05-019 with `"stands for create,
  read, update, and delete"`. 32 unit tests green. HTTP battery rerun
  2026-10-12 (`artifacts/step2-battery.{log,json}`): golden 10/10 answered,
  typos PASS, France PASS, battery PASS. Golden #5 and #10 now answer where
  they refused before (`ch06-001`, `ch02-025`).
- Watch out: two `server.py` processes can listen on :8000 at once
  (`allow_reuse_address`). A stale one silently served old code and made a
  battery run look like a regression. Check `netstat -ano | findstr :8000`
  for more than one LISTENING PID before trusting a battery run.
- RRF fusion landed 2026-10-12 as post-v1 retrieval work, user-approved:
  `fusion.py` replaces the boost's swap-last-slot. The lexical channel
  contributes its single strongest admissible candidate; reciprocal rank
  fusion (RRF_K=60) places it by both ranks. The dense band stays the
  admission gate and the trigger stays where the boost had it (a rare word).
  A head of five candidates was tried first and narrowed the same day: five
  candidates flooded out dense leaders and the MAD quote flipped back to the
  data-mesh passage (the battery caught it). Caption seeding now runs after
  fusion and keeps "present -> leave": moving a present naming chunk to the
  front broke the transformations golden (the battery caught that too).
  Measured after: pragmatic ch04-012 now leads its five (the boost put it
  last); MAD five is [ch04-020, ch04-019, ch03-099, ch02-037, ch11-018] and
  keeps ch04-019's presence, which the band record says is causal; HTTP
  battery 18 asks all pass on a fresh server (golden 10/10 answered, typos
  PASS, probes PASS, France exact; `artifacts/step2-battery.{log,json}`);
  91 unit tests. `keywords.py` is gate + anchors only now; `fusion.py` is in
  the generalization guard. Re-measured on the live 1042-chunk index: the
  pragmatic anchor sits at dense rank 76, the MAD anchor at 38, the France
  candidate at 649 (62.3%), refused by the band as before. Do not widen the
  trigger or the candidate count without a measured case and a battery run.
- Next: Phase 8, optional sequel. Phases 0-7 pass; v1 is done by the README's
  definition.
- Nomic is the v1 index, not a forever lock. Stop and say so before any of
  these, and do not do them quietly:
  - A different nomic quant. This index is from the F16 tag. Q4 or Q8 makes
    different numbers. Rebuild, rerun the 10 questions. Do not reuse this file.
  - An embedder finetune. New file, new bake-off. Do not overwrite
    `data/index.json` until it wins.
  - A smaller qwen. The library tag is already Q4_K_M, 4.7GB. A smaller one
    may fail the quote check more often.
  - A Gemma picture index. Separate file. It cannot mix with nomic numbers.
- Answer-model bake-off landed 2026-10-12 (`artifacts/answer-model-bakeoff-plan.md`,
  `answer-model-bakeoff-results.md`; evidence `artifacts/bakeoff-*`). Three pulled
  candidates ran the 18-ask battery under rules frozen before the runs:
  `qwen3:4b-instruct` (2,497 MB), `granite4.1:3b` (2,100 MB), `granite4.1:8b`
  (5,348 MB). Verdict: no swap — qwen2.5:7b stays the default; each candidate fails
  one hard gate (4b: MAD, wrong sentence in the right chunk, 3/3; both granites:
  multicloud quote stops three sentences early). All three fix the open gloss
  weakness (gloss on almost every answer vs 2/17). Seam: `ANSWER_MODEL=<tag> python
  server.py` runs any model through the same battery; the default stayed `qwen2.5:7b`
  until the 2026-10-13 swap below.
- Quote-to-paragraph expansion landed 2026-10-13 (`answer.py`): when the paragraph
  around a verified quote holds an anchor word (a question word rare in this book)
  and fits PARAGRAPH_CAP=1200, the paragraph replaces the quote. The old rule also
  required the quote to lack the anchor, which stopped granite's multicloud quote
  three sentences early; the intent call (a list answer carries the book's list)
  was made first and the test flip followed it, not the other way round. v2 battery
  on the expansion+RRF tree (frozen: fingerprints equal before and after all runs;
  evidence `artifacts/bakeoff-*-v2.*`): qwen2.5:7b 18/18 PASS; granite4.1:3b PASS,
  reproduced on a second run (one reviewed miss: the ETL full question quotes
  ch02-022, unresponsive); granite4.1:8b PASS; qwen3:4b-instruct FAIL (MAD wrong
  sentence unchanged; its CRU typo refused 4/4 — a no-citation refusal, so not this
  change; points at the retrieval side). granite4.1:3b is eligible for the small-PC
  slot per the bake-off plan. Swapped to `granite4.1:3b` 2026-10-13, then
  reverted the same day: granite answered "what is MAD data landscape" with the
  data-mesh passage (3/3 deterministic; retrieval was right, ch04-020 led the
  set) and granite4.1:8b refused the same phrasing, while qwen2.5:7b answers
  both phrasings (`artifacts/mad-phrasing-probe.md`, `mad-phrasing-postrevert.txt`).
  `prompt.py` default is back to `qwen2.5:7b`; granite4.1:3b stays on disk as
  the finetune candidate and the small-PC option. The choice is measured against
  this book's index: a new book, or a new index, triggers a fresh bake-off under
  the same frozen rules.
- Overnight QA ran 2026-10-13 (`artifacts/overnight-report.md`): a 303-question
  sweep in the user's styles (`qa-sweep.py`; question set from a subagent plus
  rare-word and heading asks), refusal classification with raw completions, and
  an audit of the coherence guard. Findings: (a) the coherence guard fixed the
  known cases but its 303-ask audit caught 19 misfires in 21 swaps — the word
  picker cannot tell a subject from vocabulary — so it was reverted the same
  night and stays out until refined; (b) ~14 sweep refusals are mechanical
  discards of correct model answers (9 short complete-sentence quotes killed by
  the 40-char floor, 3 tagless verbatim replies, 1 typographic-quote mismatch) —
  proposals in the report — all three shipped the following morning (see the
  refusal-acceptance bullet below); (c) the multicloud refusal flake
  recurred on every cold battery run (5 recorded, 4 today), always clearing on
  a warm rerun; (d) sweep design lesson: "what is <rare word>" asks are mostly
  junk — 58 of the 80 refusals were correct refusals of junk, so ask about
  topics. 91 tests green; battery green on the reverted tree.
- Refusal-acceptance fixes landed 2026-10-13 (all three from the overnight
  report, one commit each): (1) a complete short sentence may be the quote
  (`MIN_QUOTE_CHARS=20`, shape not length — "Everything fails, all the
  time."); (2) a tagless reply is verified like any prose and tagged from the
  matched passage (`_tagless_citation`); (3) typography folds in the quote
  check (curly quotes, interior commas — "data about data"). Retests via HTTP:
  "what is normalization", "crud stands for what", "types of metadata", "why
  should you plan for failure" all answer now
  (`artifacts/refusal-fixes-evidence.txt`); "hot warm cold data" stays refused
  (the model quotes only the heading), IOPS stays refused (retrieval never
  surfaces it). 97 tests green; battery PASS (`step2-battery-refusal-fixes.*`;
  one cold-run multicloud flake cleared on warm rerun as always). Commits
  eb598e1, 92e11ad, 85f4d80.
- Answer mode landed 2026-10-13 (`c9c570c`; user decision: the
  verbatim-quote core rule is gone): `respond()` generates freely from the
  retrieved passages, the model's `[Ch. N]` tags become citations matched
  back to the shown set (chapter first, word overlap decides, zero-overlap
  claims stay uncited), quotation marks the passages cannot back are
  stripped, and a refusal is the exact first line only. The quote check
  demotes from gate to meter (`artifacts/groundedness.py`: sentence 4-gram
  support). The mode's battery judge is grounded-in-retrieved (pin among the
  shown passages, citations only from shown ones): strict first-citation pin
  was 7/10 with three sibling-chunk citations (pins shown in all three),
  grounded judge 10/10 with the drift kept in the notes. Prompt A/B on 124
  authored asks: "stay close to the passages' wording" 127/482 sentences
  supported (26.3%, mean 0.312) vs the open wording 76/496 (15.3%, 0.231),
  and only the close wording refused iops/dark matter. Batteries PASS both
  modes; coherence probes PASS (MAD, data mesh, Codd -> the book's own
  "normal forms", endpoint); window select defaults to answer. 143 tests.
  Report: `artifacts/answer-mode-overnight.md`.
- Preprocessing stages 5-9 landed 2026-10-13 (`501a6db`, user lifted the
  stdlib restriction for this): `fold()` (NFKC + typographic repair), SMART
  stopwords (vendored), Snowball English Porter2 stemmer (vendored, BSD-3);
  `normalize()`/`words()`/`tokens()` byte-identical. First wiring measured:
  stopwords never anchor a paragraph (`keywords.anchor_words`); battery PASS
  on the wired tree. The stemmed-map wiring (incl. the rare gate) is
  proposed in `artifacts/stage9-preprocessing.md` section (d) with df
  evidence ("extract" family 14+4+5+9 -> 29, over RARE_DF=8, gates flip)
  and a required per-process cache before it ships.
- Answer-mode sweeps ran 2026-10-13 (303 asks each): refused 31 -> 33 -> 33;
  the guard-word column's junk fell 18 -> 8 -> 4 as stopwords and the
  vendored stemmer reached it. Refusal classes: junk rare-word and
  acknowledgment-name asks (correct refusals), iops (out of book), and
  "dark matter data" (bare phrasing refuses; "what is dark matter data"
  answers with ch11-025/026). One temperature-0 flake recorded ("adhering").
- Agentic retrieval prototype landed 2026-10-13 (`8d51e2c`): semantic/
  keyword/regex tools, `pick_next_tool()` decides from the attempts so far,
  not wired into the four routes. Live probe: 5 questions, 3.1 s total, 13
  decision calls; no measured win over the 0.5-1.2 s single-shot ask on
  these five, so wiring waits for a measured multi-hop failure set.
  `artifacts/agentic-design.md`.
- Cloud judge calibrated 2026-10-13: `muse-spark-1.3-contributor` on the
  OpenCode Go relay (`/responses` wire, reasoning effort minimal,
  `x-opencode-session` header auto-generated per process; key from
  `.judge-key`, gitignored). Replays over the same 24 items: granite
  reproduced its own verdicts exactly (68/105), agreement granite-vs-Muse
  86/105 on passage relevance (81.9%; granite over-inclusive in 16 of 19
  disagreements) and 1/1 on key facts; Muse's precision reading 55/105
  (0.524). The local judge stays the loop default; the cloud judge is the
  calibration reference. Files `eval-v1-ollama-granite4-1-8b.*`,
  `eval-v1-openai-muse-spark-1-3-contributor.*`, `judge-agreement-*.log`.
- Graded-scale A/B 2026-10-13 (`probe-judge-scale.py`, same 105 pairs): a
  0-3 relevance scale does not transfer across judges. Exact grade agreement
  granite-vs-Muse 42/105; within +/-1 95/105; every binary mapping of the
  grades ties or loses to the direct binary agreement (81.9%); each judge's
  own binary is best explained by a different mapping of its own grades
  (granite 3,2=relevant 98/105; Muse sits between mappings, 93 vs 87).
  Binary stays the headline metric; grades stay a within-judge dial, never a
  cross-model instrument. Files `judge-grade-*`, `judge-scale-*.log`.
- Not started: 8.
- Embedding hygiene guards landed 2026-10-13 (user-approved; `retrieve.py`,
  `verify_index.py`): `embed_index` refuses a response vector that is wrong
  width, non-finite, all-zero, or from a short batch, naming the chunk/figure
  before anything is stored; `rank_chunks` refuses an empty/non-finite query
  vector, a query contradicting `embedding_dims`, and a stored vector whose
  width drifted (chunk id named) — dim drift is a named error instead of every
  score silently 0.0. `verify_index.py` re-runs the audit read-only
  (non-finite / zero-norm / width drift / missing), exit 1 when dirty.
  Measured: pre-guard scan of `data/index.json` (10,528,929 bytes, sha256
  5478e5e9…) 1153/1153 vectors 768-wide, 0 non-finite, 0 zero-norm, 0 drift,
  norms 0.99999888-1.00000115 (`artifacts/embedding-audit-2026-10-13.txt`);
  post-guard `python verify_index.py` clean on the same file, dirty path exits
  1 naming the chunk; 157 tests green (was 143); live smoke 10/10 top-10 in
  2.8 s. No re-embed; index bytes untouched.
- Plain register wired 2026-10-13 (`answer.py`, `prompt.py`,
  `tests/test_plain_register.py`): an `answer` question carrying a plain-cue
  phrase (`SIMPLE_CUES`, generic English; no contract change) routes through
  `_plain_body` — the draft selects evidence sentences, each is rewritten
  one-in-one-out with `PARAPHRASE_SYSTEM` and keeps its source chunk's tag;
  citations keep the original book sentences as evidence; rewrites are capped
  at `PARAPHRASE_LIMIT` (5, a call budget); a draft refusal is the register's
  refusal; an all-empty rewrite set falls back to the draft. Faithful to the
  scorecard's measured assembly (`artifacts/eval-plain-v6`: 8/10 under the
  Muse release judge) with two deliberate strengthenings: empty rewrites fall
  back to the draft instead of a refusal, and citations come from the draft
  (book-backed by construction) instead of a re-parse. Wiring check live over
  HTTP: "explain data engineering in simple words" answers in the register
  (`artifacts/plain-http-check.json`), "What is the MAD data landscape?"
  stays ordinary (`artifacts/plain-http-control.json`); both batteries rerun
  on a fresh server (ask PASS after the known cold-start multicloud flake,
  preserved as `step2-battery-flaked.*`; answer PASS, coherence PASS); 188
  tests green. The known referent-drop failure ("...work on it." when the
  subject is never named) shows in the live check and stands as measured.
- Wired path measured under Muse 2026-10-13, three draws (`eval-plain-wired-*`,
  replay `eval-plain-wired-replay-*`): pass 6/10 and 7/10 vs the probe's 8/10
  — the 8 above was one draw. Diffed per question: 5/10 stable pass, 1/10
  stable fail (batch/streaming; the rewriter loses meaning), 4/10 flippers;
  the wiring is not implicated (identical shown passages, `same_shown` true
  for all 10; rewrites differ draw-to-draw at temperature 0 and one identical
  answer text got different verdicts). Frozen-prompt probe
  (`artifacts/judge-stability.py`): three consecutive Muse calls on one
  borderline item returned supported, supported, unsupported — the release
  judge is nondeterministic despite `temperature: 0`. Consequence:
  single-draw scorecards carry +/-1-2 borderline questions of noise; repeat
  draws before claiming a one-question A/B win. Objective gates stable and
  green (answered 10/10, fake quotes 0, unmatched tags 0, FK 6.9-7.4, cited
  share 0.40-0.44). Night report: `plain-register-night-2026-10-13.md`.
- Judge flip-rate map 2026-10-13 (`judge-stability.py --all`, 30 Muse calls,
  `judge-stability-all-wired.txt`): on the wired texts, 9/10 questions judge
  stably (6 stable-supported, 3 stable-unsupported, 1 borderline ~50%: data
  ingestion). This refines the bullet above: the cross-run swing is mostly
  *which text the rewriter draws*, not judge flips — and the judge stably
  catches concrete rewriter errors: CRUD's rewrite says "read, write, delete,
  update" (create dropped, write substituted; 0/3 in both wired draws),
  insert-only's wired text adds an "improved Lambda architecture" line (0/3),
  batch/streaming keeps the "in m." truncation. Proposed, not done: a local
  one-in-one-out check on lists/acronyms/terms to gate rewrites without the
  cloud judge.
- Plain-register edge probes 2026-10-13 (live HTTP, 20 raw responses
  `plain-edge-*`, findings `plain-edge-findings.md`, contract checker
  `plain-edge-check.py` exit 0): all 10 cues route plain; explain/quiz
  unchanged; figures only from cited passages; cue is a substring test ("not
  in simple words" routes plain — minor). Two refusal-class failures, both
  the pre-existing answer-mode seam, not the wiring: cue + out-of-book
  answers confidently from a junk passage (`refused:false`, 2/2), and the
  no-cue control prints a preamble before "Not in this book."
  (`refused:false` per the frozen first-line rule). Open decision for the
  user: refusal guardrail, or keep free generation model-driven.
- Agentic multi-hop hunt 2026-10-13 (`multihop-report.md`, agent run,
  read-only): 10 two-evidence questions. Full-set surfaced: single-shot 6/10,
  loop 7/10 any-position — but the loop's first five merged passages match
  single-shot exactly (extras at merge positions 9 and 6). 26 decision calls,
  all `semantic`; keyword/regex never picked though hand queries reach every
  missed chunk at rank 1-5 — decision policy, not tool reach. Verdict: no
  wiring; the next test, if pursued, is a forced tool-diversity policy.
- Forced-keyword follow-up 2026-10-13 (`multihop-forced-keyword.*`): after one
  semantic step, the next step was forced to keyword; the model's own query
  reached a missed chunk at rank 2 once (MDM), rank 10 once (PII), half once
  (streaming: one target rank 2, the other absent), and missed both once (CDC).
  2 of 4 queries echoed the question verbatim, which keyword search dilutes —
  the bottleneck is query shape, not tool choice. Still no wiring; a next
  iteration would be a keyword-query-shaped decision prompt.
- Fragment fix 2026-10-13, after the user's live report ("By scientists,
  analysts, and others." / "About moving, changing, and handling data."):
  citation quotes could be mid-sentence copied runs, and the rewriter
  faithfully kept the fragment shape. Two view-level changes in `answer.py`
  (chunk text untouched): `_evidence_quote` expands a copied span to the
  whole passage sentence that holds it (the run stays the fallback), and
  `_sentences` splits footnote glue ("Maxime Beauchemin4" + next capital) so
  an attribution cannot run into the next sentence. A third pre-existing bug
  the battery rerun surfaced: a two-chapter tag ("[Ch. 2, Ch. 7]") carried a
  second "Ch." inside the sentence-split mask and the claim was dropped —
  the endpoint answer lost all citations; the mask now clears periods.
  Measured: Muse draws 9/10 and 8/10 post-fix (6, 7 pre-fix), zero fragment
  openers in all 20 answers, CRUD now rewrites correct ("create, read,
  update, delete"; the create->write error is gone), the batch/streaming
  "in m." truncation gone. Residual: insert-only's Lambda line, one loose
  ingestion paraphrase, one fk-13.7 draw (naming the book's terms). Live
  HTTP check on the user's exact questions: subjects preserved. Both
  batteries PASS; 193 tests green. Files `plain-fix-check-*.json`,
  `eval-plain-quotealign*`.
- Quote-choice fix 2026-10-13, after the user's live report (two plain lines,
  both Ch. 1, the same idea twice): the citation quote could come from the
  sentence holding the longest copied run even when another sentence
  overlapped the claim far more, so the plain register rewrote the wrong
  sentence — the draft paraphrased ch01-005's definition, but the stray run
  "by data scientists, analysts, and other" (41 chars, generic) handed the
  quote to the enumeration sentence. `_evidence_quote` now picks the quote
  sentence by claim overlap, the rule `_best_passage` already uses for the
  passage; a copied run breaks ties and stays the fallback when no sentence
  can hold it; `_whole_sentence` folded away. Measured on the exact
  question, one draft, same passages (`probe-quote-fix`): quote overlap
  0.25 -> 0.50 (the definition sentence), first plain line "Data engineers
  get data, store it, and prepare it for others." -> the definition's
  rewrite, max pairwise line similarity 0.94 -> 0.87, four other scorecard
  questions byte-identical. Regression test added; 194 tests green. No Muse
  draw (single-draw scorecards carry +/-1-2 borderline questions; one quote
  moved). Residual: the ch04 rewrite still drops its payload ("...forget
  the main goal"), and plain lines 2 and 4 still restate each other —
  rewriter-side and draft-side levers, both open. Files
  `probe-quote-fix*`, `probe-plain-diagnose*`, `probe-quote-choice.log`.
- MAD ask ceiling probed 2026-10-13 (user live report: "MAD data landscape"
  quotes the Ch. 4 pointer sentence "…that we introduced in Chapter 1";
  "looks like first person … who even is Matt Turck"). Reproduced exactly.
  Four measured negatives, no engine change: +ch01-018 in the pool (Figure
  1-3's paragraph) changes nothing and one draw lost the gloss; the
  figure-4-1 caption as a passage is never quoted, and caption-first
  refused one phrasing; a narrow gloss-content steer ("never write 'The
  passage'") left the meta-gloss in place and refused two battery pins
  (transformations, multicloud) 2/2 draws each, control 2/2 pass both — the
  steer family is now 0/4, do not retry a prompt shape without a model
  change. The book's text names MAD once (the pointer); the Ch. 1 treatment
  is figure-1-3; "who is Matt Turck" is not in the book. Summary
  `artifacts/mad-ask-ceiling.md`; probes `probe-mad-{quote,seed,caption}.*`,
  `probe-gloss-steer*`.
- Query-phrasing sensitivity probed 2026-10-13 (user report: one "?" changed
  "What is nonrelational database" from the ch05-032 definition to ch05-034's
  "NoSQL remains vague" sentence at the same pool order — model-side, not
  retrieval). Battery sweep, trailing "?.!" stripped, 23 questions x 2
  (`probe-query-normalize`): quotes changed 4/23; pin flips 2/23 in opposite
  directions (transformations loses its pin, nonrelational gains); multicloud
  flaked both ways (known flake; control passed 2/2 minutes earlier). Blanket
  normalization is consistency, not correctness — not landed. EPUB link
  graph verified (`probe-epub-links`): the MAD sentence carries internal
  xrefs (ch01#data_engineering_described, the figure anchor); index chunks
  keep no links. A one-hop link channel is a backlog-probe candidate; its
  A one-hop link channel is a backlog-probe candidate; its
  MAD targets were already tested and ignored. Summary
  `artifacts/query-normalization.md`.
- Bare-phrase canonicalization landed 2026-10-13 (`canonical.py`,
  `answer.py`, `tests/test_canonical.py`): `canonical_query` prefixes a
  structurally bare phrase ("mAD DaTa" -> "What is mAD DaTa?") before
  retrieval and prompt; `ask`/`respond` take a `canonical` flag, `explain`
  is gated off (its highlight is a book sentence); non-refused answers show
  `Asked as:` (readings precedent). Guards: no "?", no wh-word, first token
  not auxiliary or opener/list marker ("explain …", "types of …"), no
  pronoun anywhere. 210 tests green (16 new: trigger table, byte-identical
  pass-through, the seam — search, fuse, caption_seed and the prompt see
  one string — refusal exactness, explain gate, anchor equivalence; one
  audit pass strengthened two fixtures: the anchor map carries in-bound df
  and the explain test asserts its highlight is trigger-eligible).
  Fixture rerun vs `-stage0`: bare MAD ask follows the question-form
  behavior; answer-mode bare MAD drops 3 figures to 1; mesh/watermark/
  ingestion lead and figures stable (ingestion tails stay draw noise).
  Retest: zero regressions, one intended delta — answer-mode "dark matter
  data" bare refusal becomes a book-backed answer; France refuses both.
  Both batteries PASS over HTTP on a fresh server (ask PASS; answer golden
  10/10, typos, probes, coherence). Window check 2026-10-13 (user):
  `Asked as:` line and the clean bare-MAD answer confirmed live; the
  watermark ask unchanged. Residual: MAD ask wh-form refusal flake (did not
  recur); answer-mode filler variants still diverge (Stage 2/3). Plan
  `artifacts/query-canonicalization-2026-10-13.md`.
- Finetune prep 2026-10-13 (`artifacts/build-finetune-data-2026-10-13.py`,
  summary `artifacts/finetune-data-prep-2026-10-13.md`): the 7B teacher is
  distilled through the shipped seam into
  `data/finetune/quote-refuse-2026-10-13.{train,bench}.jsonl` (gitignored):
  191 questions -> 239 rows (gold 80 / silver 76 / refusal 29, plus 54
  refusal over-sampling copies x3); the teacher skimped the gloss line in
  ~80% of answers, so 126 glosses are synthesized with `PARAPHRASE_SYSTEM`.
  Split: train 194 / bench 45 (bench = eval and class-variant rows plus
  sweep twins of bench topics, guarded by pattern). Refusal mining v2 kept
  27 of 28; 1 answered from a passing mention and was rejected. 6 rejects
  logged; independent verifier PASS, 0 failures. Colab recipe ready:
  `artifacts/finetune-colab-recipe-2026-10-13.md` +
  `finetune-colab-2026-10-13.ipynb` (A100 or L4, Unsloth LoRA, upload only
  the train file). Next: run it, import the GGUF, run the bench against the
  recorded 7B numbers.
- Finetune v1 checkpoint 2026-10-13 (`smallbook:latest`, Qwen2.5-3B Q4_K_M,
  1.93 GB): the pipeline works end to end (Colab -> GGUF -> Ollama ->
  engine) and the exact refusal sentence is learned, but the model never
  stops (one call: 174,181 chars in 354 s, quote after quote) and picks
  wrong quotes ("What is a watermark?" -> ch06 disks; MAD falsely refused).
  Diagnosis: v1 trained on the whole text; notebook v2 trains on responses
  only, 120 steps, with a stop-check cell before export. Second candidate
  run queued (Qwen3-4B-Instruct-2507 first). Bench
  `probe-small-ask-2026-10-13.py` is reusable but not runnable until
  stopping works. v1 stays in Ollama as a baseline.
- Finetune v2/v3 checkpoints 2026-10-13 (`smallbook` Qwen2.5-3B v2, 1.9 GB;
  `smallbook_q3` Qwen3-4B-2507, 2.5 GB; trained in one L4 session): the
  responses-only fix worked — stopping clean, format holds, bench 19/21
  pins each (7B: 21/21; misses are adjacent chunks). **Refusals lost on
  both** (France cites a CIO passage): 13 refusal cards vs 113 answer cards
  teach "always quote something". Dataset regenerated same evening: reworked
  mining pool, 27 refusal questions x3 (train 194 = 113 answer / 81 refusal),
  `probe-finetune-verify-2026-10-13.py` PASS 0 failures; notebook unchanged,
  only the train file. v1 preserved as `smallbook-v1`.
- Finetune x3 import + loop finding 2026-10-13 night: both checkpoints
  imported hash-first (`smallbook` gguf `435ed1f8…`; the x1-era weights
  kept as `smallbook-old`). **Refusals fixed on both** (France + iops
  exact). But the 3B checkpoint loops on some answers (source-systems
  question 1-4/10 draws at temps 0.1-0.3 and with penalties; CRUD 4/5 at
  temp 0; the 21-pin battery crashed mid-run each pass) — sampler fixes
  rejected, app seam stays temperature 0 — and the Qwen3-4B variant
  over-refuses (bench 2/21 pins), parked. Fix = ratio retrain: datasets x2
  (167 rows) and x1 (140) built + verified; notebook v4 trains both in one
  session. Evidence: `artifacts/finetune-loop-eval-2026-10-13.md`.
- Finetune x2 wins + app trial 2026-10-14: the x2 checkpoint (167 rows) is
  the first small model with refusals AND clean generation — refusals 2/2
  exact, battery 18-19/21 across the three recorded passes (a fourth file
  is field-identical to the third; deduped 2026-10-14), 0 loops in 168 capped
  draws
  across all 21 questions; x1 loops (insert-only 10/10, deterministic).
  App default flipped to `smallbook_x2` (prompt.ANSWER_MODEL; revert =
  `ANSWER_MODEL=qwen2.5:7b` env, no edit); builder teacher pinned to
  qwen2.5:7b. Known warts: false refusals on unmemorized forms (Codd, CRU
  lowercase, DE Lifecycle, Location, ddr4-vs-ddr5 order flip; the 7B
  answers all — `artifacts/x2-trial-2026-10-14.md`). Contamination audit: 0
  exact duplicates, 4 near-twins of bench questions in train (ingestion,
  enterprise-architecture, pragmatic x2, codd) — gate now runs per build
  (`artifacts/probe-contamination-2026-10-14.py`). Next session: x2c + the
  seed control.
- Finetune pre-run hardening landed 2026-10-14, before any x2c training
  (review: `artifacts/reports/finetune-expert-review-2026-10-14.md`): the
  builder's class-(a) swaps corrected — crud/raid now teach the lowercase
  wh-forms (the measured wart surface), six unmeasured casing swaps
  reverted, pii/oltp stay case-mix probes; 24 swaps, counts held
  (167 = 113 + 54). Dataset rebuilt and re-verified PASS
  (`data/finetune/quote-refuse-2026-10-13.train-x2c.jsonl`, sha256
  `27a84899…`; bench byte-identical `174afd18…`); contamination 0 exact /
  11 near pairs (the CRUD battery golden and the CRU typo are now assisted
  twins, reported separately). Notebook v6 adds the mask/EOS spot-check,
  token histogram, hard stop-check on an answer + a refusal row, GGUF/zip
  hashes, LoRA adapter save, and a run-log JSON. `answer.py` sends
  `num_predict: 512` (a loop becomes a truncated answer, not a 120 s
  timeout). Gate amended pre-run — equal-draws 7B baseline, seed-control
  read-out, q8 persist/vanish rule, assisted-item list
  (`artifacts/reports/x2-trial-2026-10-14.md`).
- x2c session closed 2026-10-14: **not adopted** — gate 2 failed both quants
  vs the 7B on the sealed suite; `smallbook_x2` stays the default. Recorded:
  the user warts (Location, DE Lifecycle, ddr4-flip) are answered; loops
  0/210; Codd fixed data-attributably; q4→q8 quant effect large (battery
  18→19, fragment 0/40→20/40). Seed control diverged — single-run
  comparisons are run-variance-bound. Non-adopted models deleted after the
  record; LoRAs kept (`data/models/*_lora.zip`). Verdict:
  `artifacts/reports/x2-trial-2026-10-14.md`. Next: `x2d`.
- Second-book portability probe 2026-10-14 (`reports/second-book-2026-10-14.md`):
  a second EPUB ("Quantization and Fast Inference", 506 chunks / 0 figures,
  `data/index.quantbook.json`, `books/quantbook.epub` local only) ran through the
  unchanged engine. x2 refused zero of 10 in-book questions (the FDE wart class
  did not reproduce) and refused all 3 controls exactly — but citations did not
  transfer: 2 of 11 non-control answers carried `[Ch.` tags (both correct).
  Chapter strings ingested as `chapter-4`, not `4`; same-day one-change retest:
  `_chapter_number` now keeps only the number (`chapter-4` -> `4`; chunk ids
  unchanged), index rebuilt — citations transfer: x2 9/11 tagged (was 2/11),
  in_book 3 PASS / 7 PARTIAL; x2d 8/11 tagged, 5 PASS / 5 PARTIAL (ste and
  zeropoint PARTIALs partly the pre-drafted gold sets, known-wrong there);
  controls still 3/3 exact on both, zero refusals; every tag verbatim. 223
  tests green (4 new). The 7B answered "capital of France" with a fabricated
  `[Ch. 4]` pin (chapter-4-022 holds that string as a calibration example) —
  teacher only. Visible targets only; n=1. Evidence: `evidence/probe-second-book/`.
- Retry safety net landed 2026-10-14 (`answer.py`; the x2d verdict's option c):
  `ollama_generate` gained a `prefill` param (a trailing assistant turn makes
  Ollama continue; probed first), and `_retry_uncited` retries an uncited
  answer-mode reply once with `[Ch. `, kept only when a citation validates as
  verbatim passage text (parse_answered first, parse_completion second — a
  tag-first reply can only validate through the ask parser). The trigger is
  uncited + passages, not the review's anchors gate: anchors miss 7 of 16
  suite items (measured). Suite at 10 draws: x2d 21/160 -> 111/160 (bare
  0->41/50, trailing 1->30/30, fragment 10->20/40, order 10->20/40, 0 loops);
  x2 60/160 -> 111/160 but with 20 loops; both still short of pre-retry gate
  item 2 (x2d: bare/order; x2: order/trailing). The visible-ten uncited three
  (Location, DE Lifecycle, ddr4-flip) are NOT rescued; the second book is
  rescued 2/10 (x2) and 1/10 (x2d). 219 tests green (4 new). Decision tables:
  `artifacts/reports/retry-safety-net-2026-10-14.md`; **user decision
  2026-10-14: adopt `smallbook_x2d` anyway** (battery/loops/pins weigh the
  swap; the pre-registered item-2 gap stays recorded), `prompt.ANSWER_MODEL`
  default flipped, revert seam unchanged. Bar refresh under the retry
  2026-10-14: the 7B is unchanged at 140/160 (bare 50/50, order 40/40;
  controls 10/20 — its violin leak pre-dates the retry), so item 2 stands;
  x2d's deficit (29 draws) = `how do` (10) + bare `Time Series` (9) + the
  column/row order pair (20), minus its `what about` gain (10) — all four
  teachable items sit on `datasets/training-list-2026-10-14.md`.
- Teacher upgrade in flight 2026-10-15 (build-time only; shipped models stay
  stock GGUF): the next student distills from a Qwen3.8-27B-class teacher
  captured on Colab. Kit: `probes/gen-new-forms-v2-2026-10-15.py` ->
  `data/finetune/new-forms-v2-2026-10-15.json` (187 forms: deficit cards max
  3 gold-pinned each, 30 bare topics, 16 order flips, 32 causal rows, 20
  fragments, 65 refusals) -> `probes/build-teacher-capture-2026-10-15.py` ->
  **515-row capture file** (328 re-captures + 187 new; 396 cited / 119
  refusal; gitignored). Notebook v3
  (`reports/teacher-capture-colab-2026-10-15.ipynb`): Qwen3.8-27B
  UD-Q4_K_XL default (~16 GB; HF filename verified 2026-10-15; Saluki 2-bit
  fallback), `-c 16384 --parallel 4 --cache-reuse 256`, behavioral pre-gate
  (9 probe items + 5 capture rows; hard stops on thinking leaks / empties /
  cap-hits; ceilings printed, not gated), 4-worker capture at max 250 tokens,
  resume by row id, Drive copy. External review (sent as
  `reports/coach-handoff-2026-10-15.md`) answered measured in
  `reports/coach-review-response-2026-10-15.md`: recapture prefixes 274
  `[Ch.` + 54 refusal; both column/row directions retrieve the same chunks;
  7B `what about` = uncited prose, student pass is retry-rescued; x2d Turn-1
  21/160 vs retry-rescued 90/160 (7B 140/160, 0 rescued). Probe gained the
  additive `repeat5` loop metric; the finetune notebook derives epochs from
  the row count (hold ~1968 presentations, checkpoints in-session). Owner
  decision 2026-10-15 (half-covered comparisons): `ddr4 vs ddr5` answers the
  covered side with a boundary gloss ("the book does not mention DDR4") —
  the 3 ddr4 capture rows carry the rule in their note. Same-day live test
  (the user's HTML run) caught the current model inventing a DDR4 figure —
  `1000 ns` is the book's "roughly 1,000 times faster than SSD" garbled;
  `DDR4` occurs 0 times in the book. Live-session Colab quirks 2026-10-15
  (baked into the notebook): 8080 is occupied in the Colab VM (serve on
  8000); the CUDA plugin silently runs on CPU unless `/usr/lib64-nvidia`
  (`libcuda.so.1`) is on `LD_LIBRARY_PATH` — measured 1.9 tok/s and GPU RAM
  0.0/40 GB on an idle A100 before the fix, `dlopen OK` after. Capture
  complete 2026-10-15 (two sessions; the first new-form pass exposed a
  two-seam mode split — runbook §7 — and was re-run through the ask seam).
  Build done: **x2e train set = 475 rows (395 cited + 81 refusal at 17.1%)**,
  sha `55a291bc…`; report `reports/x2e-build-2026-10-15.md`; gate
  pre-registered in `reports/x2e-plan-2026-10-15.md`; training notebook
  patched to v8 (EXPECTED 475, export `smallbook_x2e`, epochs derive to 4).
  Trained (A100, ~1 h, loss 0.84 -> 0.035, stop-checks sane) and gated
  2026-10-15: the gate exposed an engine bug — answer mode served a prompt the
  student was never trained on; fixed (`answer.respond`/`_retry_uncited` now
  send `SYSTEM` + `user_message`). Under the fix the shipped x2d is
  **160/160** on the sealed suite (was 111), x2e 150/160, the 7B 160/160,
  0 loops; **x2e not adopted** (ask-mode battery 7/10 < 8; false refusals on
  two visible-ten items) — x2d stays the default; x2e + LoRA + run log stay
  on disk as evidence. Full numbers + backlog:
  `reports/x2e-verdict-2026-10-15.md`. Full runbook:
  `reports/colab-capture-session-2026-10-15.md`.

## Verify

- `python -m unittest discover -s tests` (must stay green)
- Setup readiness: `python preflight.py` (read-only; Python version, book,
  index, Ollama, models, vector audit; exit 0 when ready to serve)
- Index hygiene: `python verify_index.py` (read-only; exits 1 on dirty vectors)
- Server: `python server.py` -> `GET http://127.0.0.1:8000/health`. A server
  serves the code and model it loaded at start — restart
  `artifacts/runs/start-engine.bat` after any `*.py` or `ANSWER_MODEL` change,
  and check `/api/ps` to see which model is actually loaded (a 14:46 server
  kept serving `smallbook_x2` with no cap/retry until restarted 22:26,
  measured 2026-10-14).
- Bake-off: `ANSWER_MODEL=<tag> python server.py`, then `python artifacts/harnesses/step2-battery.py`. Default is `smallbook_x2d` (the 2026-10-14 x2d adoption; `ANSWER_MODEL=qwen2.5:7b` or `=smallbook_x2` reverts — see the retry bullet); keep exactly one listener on :8000.
- Answer mode: `BATTERY_MODE=answer python artifacts/harnesses/step2-battery.py`; sweeps `SWEEP_MODE=answer python artifacts/harnesses/qa-sweep.py <label>`; groundedness `python artifacts/harnesses/groundedness.py --battery --label <name>` or `--label <name>` over `datasets/qa-questions-overnight.json` (in-process, no server needed).
- Agentic prototype (not wired): `python artifacts/probes/probe-agentic.py` (live Ollama, 5 asks).
- Plain register: `python -m unittest tests.test_plain_register`; scorecard draws (cloud judge) `JUDGE_BACKEND=openai JUDGE_WIRE=responses JUDGE_MODEL=muse-spark-1.3-contributor JUDGE_BASE_URL=https://opencode.ai/zen/go/v1 JUDGE_API_KEY_FILE=.judge-key python artifacts/harnesses/eval-plain.py --variants wired --label wired` (replay with a new label); judge flip probe `python artifacts/harnesses/judge-stability.py --file evidence/eval-plain/eval-plain-v6-openai-muse-spark-1-3-contributor.json --match <question substring> --n 3`; live route check: `answer` mode with "explain data engineering in simple words".
- Canonicalization: `python -m unittest tests.test_canonical`; live check:
  a bare phrase in answer mode ("watermark") answers in question form and the
  answer ends with `Asked as: "What is watermark?"`; mutation check
  `python artifacts/probes/probe-test-mutations-2026-10-13.py` (5 breaks, 0 survivors).
- Judge backends: default `ollama:granite4.1:8b`; cloud replay, e.g. `JUDGE_BACKEND=openai JUDGE_WIRE=responses JUDGE_MODEL=muse-spark-1.3-contributor JUDGE_BASE_URL=https://opencode.ai/zen/go/v1 JUDGE_API_KEY_FILE=.judge-key python artifacts/harnesses/eval.py --judge-only --label v1`, then `python artifacts/harnesses/judge-agreement.py eval-v1-ollama-granite4-1-8b eval-v1-openai-muse-spark-1-3-contributor`. `.judge-key` is gitignored; the engine never uses it.
- Secret scan: `python artifacts/harnesses/secret-scan.py` (git history + tracked tree; masked output; exit 1 on any hit). Clean 2026-10-13: this repo 516 blobs, 0 hits; `rag-template` 170 blobs, 0 hits.
- Artifacts: index + rules `artifacts/README.md`; prune planner `python artifacts/prune.py --plan`.

## Machine facts (this Windows box)

- Use system `python` (3.12.5). The README's `env -u PYTHONPATH` wrapper is a
  macOS note; ignore it on Windows.
- Ollama: `C:\Users\ADRIAN\AppData\Local\Programs\Ollama\ollama.exe`, v0.40.3.
  Upgraded 2026-10-11 from v0.4.3. Installer was `OllamaSetup.exe`, 1578217944
  bytes, signed by Ollama Inc., silent install exit 0. Not on PATH. Start it
  with the full path + ` serve`. `ollama --version` with the server up prints
  `ollama version is 0.40.3`.
- On disk: `nomic-embed-text:latest` (274 MB, pulled 2026-10-11). Smoke embed
  returned 768 dims. `smallbook_x2d:latest` (1.9 GB, digest `d0bfa88f6b63`) is the finetuned
  answerer and app default since 2026-10-14; `smallbook_x2:latest` (1.9 GB,
  `ba79d37a6067`) and `smallbook_x2d_q8:latest` (3.3 GB, `a8d4b390`) stay on
  disk; `qwen2.5:7b` (4.7 GB, Q4_K_M) is
  the teacher, on disk since 2026-10-11 after approval (see the Phase 4 bullet). Bake-off pulls 2026-10-12 (9,945 MB approved):
  `qwen3:4b-instruct` (2,497 MB), `granite4.1:3b` (2,100 MB), `granite4.1:8b`
  (5,348 MB).
- MLX runtime installed 2026-10-11 from `ollama-windows-amd64-mlx.zip`,
  1403168802 bytes, extracted into the Ollama program folder. Zip deleted.
  `embeddinggemma-2:270m-bf16-text` (574 MB) is on disk. Smoke embed returned
  768 dims. Runner shows `mlx`, `100% GPU`. Do not pull `embeddinggemma` (v1)
  or the picture/audio tags. This book only needs the text tag.
- `agent-browser` (browser-automation skill) does not start on this box as of
  2026-10-12: its daemon fails to bind a TCP socket (os error 10013, Windows
  excluded port ranges). Use a real browser for window checks.
- Do not delete `tests/__init__.py`: a user-site `tests` package shadows the
  directory without it (the file itself explains why).
- `books/` and `data/` are gitignored. On a fresh machine, re-run Phase 0: the
  original EPUB path is recorded in `books/SOURCE.txt`.

## Post-v1 backlog (not approved; confirm before starting)

- Caption quoting: README Figure honesty allows quoting the caption; the
  pipeline currently feeds only passages.
- `keep_alive` in the Ollama requests: removes the ~25 s cold-load; warm asks
  are ~1 s (measured). Cost: ~5 GB VRAM held.
- Frontend + citation navigation (direction recorded 2026-10-13, not
  approved): the app gets its own reader; `[Ch. N]` becomes a link that
  jumps to the passage and highlights it. External-reader hand-off dropped;
  Readest/ReadAny are pattern references; foliate-js is the candidate
  engine. Plan, locator strategy, and the open renderer decision:
  `artifacts/reports/frontend-navigation-plan.md`. Needs explicit yes: new
  read/static routes and citation fields (contract), plus the foliate-js
  vendoring download (megabyte approval per BUILD_PLAN).
- Conversational companion (direction recorded 2026-10-15, not approved):
  the user wants the companion to eventually hold a conversation, so
  degenerate input (bare fragments like `how do`) becomes a *conversational*
  turn (a clarifying question or follow-up) instead of the binary
  answer-or-refuse. Parked; not this build. If taken up it needs a third
  response type (clarify), conversation state and a new/extended API contract
  (`POST /ask` is frozen), multi-turn training and eval data, and a re-think
  of the sealed suite's fragment class (which currently requires fragments
  ANSWERED). Until then the refusal sentence keeps one meaning: the book does
  not cover the thing — never "I did not understand you" (rule recorded
  2026-10-15 with this direction).
