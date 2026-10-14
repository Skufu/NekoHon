# Planning context — ask-this-book (handoff 2026-10-12)

For an external planner: read this top to bottom; it is self-contained. Deeper
detail lives in the repo files listed at the end.
Repo: https://github.com/Skufu/ask-this-book (branch main).
What is asked of the planner: a concrete plan for whichever open items you
pick, respecting the hard constraints, with the validation battery as the
acceptance bar.

## The product (v1, done)

Offline book companion for one EPUB ("Fundamentals of Data Engineering",
book_id `fde`). Ask a question -> exact quoted sentence from the book with a
`[Ch. N]` tag + one-line gloss; a figure attaches when a kept passage names
it. Highlighted text can be explained; quiz returns one question plus its key
sentence. Nothing leaves the machine — proven with the network cable
unplugged (README Phase 7).

## Architecture (all local, stdlib Python + one HTML file)

    question -> nomic-embed-text (Ollama on 127.0.0.1:11434)
             -> cosine over data/index.json (1,065 chunks + 111 figures, 768 dims)
             -> top-5 passages -> qwen2.5:7b (Ollama) writes [Ch. N] "quote" + gloss
             -> code verifies the quote is a substring of a retrieved passage
                (else refusal) -> window renders answer + figures

- Engine `server.py`: four routes only — `POST /ask`, `GET /health`,
  `GET /figures/{id}`, `GET /`.
- Contract: `refused: true` means `answer` is exactly `Not in this book.`
  Anything unchecked is a refusal.
- Modules: `prompt.py` (single system prompt), `answer.py` (generation +
  quote check), `retrieve.py` (embed + cosine), `figures.py` (attach rule),
  `window/index.html` (the v1 window; shows citation chunk ids).

## Hard constraints (do not violate)

- Python stdlib only. No pip, no numpy, no database, no cloud API. `urllib`
  talks only to localhost.
- No new routes; contract shapes frozen (README "Contract").
- Model, quant, and prompt changes are stop-and-say items and must re-pass
  the full validation battery.
- Downloads need an explicit MB approval before transfer.

## Measured state (2026-10-12)

- Latency: warm ask ~0.8-1.6 s; first ask after ~5 min idle ~25 s (Ollama
  unloads idle models).
- 24 unit tests green. Window verified in a browser: ask, explain, quiz.
- The 10 golden questions (`tests/fixtures/questions.json`) end-to-end over
  HTTP: 8 answered, 2 refused (#5 storage-cornerstone, #10 transformations).
  Retrieval is 10/10; the refusals are the answer layer.
- Typos: `What does CRU stand for?` and `...extracted in ET?` keep the right
  chunk at retrieval rank 1 (scores 0.785->0.675 and 0.750->0.711) but the
  answer layer refuses. A prompt-line fix was tried in two wordings: both
  failed, one caused a regression (golden #6), and it was reverted.
- Refusals can carry nearest-miss figures (the storage question shows two).
  The France test (`What is the capital of France?`) must always return
  exactly `Not in this book.`
- Phase 8 (Readest, parked): readest/readest is ~322 MB, AGPL-3.0. The
  machine lacks `cargo`/`rustc`/`cargo tauri` and `pnpm` (Node 22, npm 11,
  VS 2022 present). The plan says: if `cargo tauri` is missing, stop.

## Open items (post-v1 backlog)

1. Typo tolerance — the answer layer refuses when the question's term is a
   typo of a passage term ("CRU" vs "CRUD"); retrieval is fine; prompt-line
   approaches are measured-dead. Candidate: normalize the question against
   the book's vocabulary (stdlib `difflib`?) before embedding and prompting.
   Known risk: false corrections of legitimate words. Needs design + the
   battery.
2. Figures on refusals — show, but label "nearby, not an answer" (window).
3. Caption quoting — the README's Figure honesty allows quoting a caption;
   the pipeline currently feeds only passages. Must not claim to read
   charts.
4. `keep_alive` — set Ollama `keep_alive` in the requests to remove the
   ~25 s cold load; costs ~5 GB VRAM held.
5. Phase 8 (Readest Tauri shell) — parked; needs toolchain installs + MB
   approvals; engine stays a separate process; AGPL stays on the fork.

## Validation battery (acceptance bar for every change)

- `python -m unittest discover -s tests -t .` — 24 tests green.
- The 10 golden questions end-to-end: no regression vs 8/10 (same chunks
  where possible).
- Quote checks: returned quotes are substrings of retrieved passages
  (CRUD ch05-019, ingestion ch07-002, watermark ch08-040).
- `What is the capital of France?` -> exactly `Not in this book.`
- The two typo cases above.

## Read more (in the repo)

- `README.md` — the locked plan: Contract, phases 0-8, risks.
- `AGENTS.md` — current state, machine facts, post-v1 backlog.
- `artifacts/demo-questions.md` — measured demo answers.
- `artifacts/phase7-offline.log` — the offline-proof run.
