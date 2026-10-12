# AGENTS.md — ask-this-book

Agent entry point for this repo. Read this file, then `README.md` (the full
locked build plan) and the current phase brief in `artifacts/`.

## What this is

An offline book companion. One EPUB ("Fundamentals of Data Engineering",
`book_id` = `fde`) is ingested into a JSON index, passages are retrieved with a
local embedder, and questions are answered with exact quotes plus the figures
those passages cite. All inference is local Ollama on `127.0.0.1:11434`.
No cloud APIs, no database server, no package installs.

## Hard rules (do not break)

- Python stdlib only — the whole standard library is fair game, e.g.
  `zipfile`, `json`, `html.parser`, `xml.etree.ElementTree`, `urllib`,
  `http.server`, `pathlib`, `re`. No pip installs, no `requirements.txt`, no
  numpy. If a task seems to need a package, the task is wrong — redesign it.
  `urllib` may talk only to this machine: Ollama at `127.0.0.1:11434`, and the
  engine itself. No other host.
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
  "Contract"). `refused: true` means `answer` is exactly `Not in this book.`
  That sentence, period included, and nothing else. A line that starts that
  way and then keeps talking is not a refusal.
- Chunking (Phase 2) and embedding (Phase 3) stay separate phases. Do not do
  a later phase's work inside an earlier phase. If the plan looks wrong, say
  so BEFORE changing anything — honest architect, not a yes-man. Do not reorder
  or skip a phase unless the human says yes. Silence is not a yes.
- `rag-template/` is read-only reference. Never touch its `.venv`. Do not port
  numpy, pickle, BM25, rerankers, or agentic/multimodal code from it.
- Do not commit unless the human asks.
- Improvements must generalize, not fit this book's test set — the system has
  to hold for other books later. No chunk ids, figure ids, chapter numbers,
  query strings, or book ids in the logic modules (`answer.py`, `captions.py`,
  `figures.py`, `keywords.py`, `prompt.py`, `retrieve.py`, `spelling.py`).
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
  promoted chunk must sit in the dense top `RANK_BAND` (0.10) of the corpus,
  or nothing is injected; no rank map is no evidence and fails closed.
  `retrieve.rank_chunks` is the shared ranking and `dense_rank` exposes it.
  Measured: with the df gate forced open (RARE_DF=40) and the same rank map,
  the France candidate ch02-068 (dense rank 695) is rejected at band 0.10 and
  injected at band 1.00 — the band is the deciding gate, not the df. The
  France ask refuses exactly with RARE_DF at both 8 and 40. Positives keep
  working: pragmatic -> ch04-012 (rank 51), multicloud -> ch04-038 (rank 1),
  watermark -> ch08-040 + figure-8-8; golden 10/10, MAD -> ch04-020. Every band
  between 4.8% and 65% decides those three the same way, so 10% is inside a
  wide margin, not at its edge. Cost: the rank map adds one embed plus a full
  cosine pass (~0.11 s), paid only when the rare gate fires. 57 unit tests
  green. Battery not rerun (stale :8000 server); `embedding` vectors and
  `data/index.json` untouched.
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
  (`artifacts/step2-battery.{log,json}`); 52 unit tests green.
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
- Not started: 8.

## Verify

- `python -m unittest tests.test_contract -v` (must stay green)
- Server: `python server.py` -> `GET http://127.0.0.1:8000/health`

## Machine facts (this Windows box)

- Use system `python` (3.12.5). The README's `env -u PYTHONPATH` wrapper is a
  macOS note; ignore it on Windows.
- Ollama: `C:\Users\ADRIAN\AppData\Local\Programs\Ollama\ollama.exe`, v0.40.3.
  Upgraded 2026-10-11 from v0.4.3. Installer was `OllamaSetup.exe`, 1578217944
  bytes, signed by Ollama Inc., silent install exit 0. Not on PATH. Start it
  with the full path + ` serve`. `ollama --version` with the server up prints
  `ollama version is 0.40.3`.
- On disk: `nomic-embed-text:latest` (274 MB, pulled 2026-10-11). Smoke embed
  returned 768 dims. `moistral:latest` (4.0 GB) is also on disk; do not use it.
  `qwen2.5:7b` (4.7 GB, Q4_K_M) is on disk; pulled 2026-10-11 after approval
  (see the Phase 4 bullet).
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
