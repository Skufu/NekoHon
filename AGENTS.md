# AGENTS.md — ask-this-book

Agent entry point for this repo. Read this file, then `README.md` (the full
locked build plan) and the current phase brief in `artifacts/`. On a new machine, start with
`HANDOFF.md`.

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
- Report measured results, not impressions: files changed, exact command, real
  output. If a test fails, say so with the actual failure.

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
  That button was not clicked in a browser.
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
  answer and the `figure-8-8` image with caption, live from the engine. The
  explain mode and the quiz "Show the key" button are not yet exercised in a
  browser.
- explain and quiz verified over HTTP 2026-10-12, both `refused: false`, no key
  leak in the quiz question. Latency profile: warm asks ~0.8-1.6 s; the first
  ask after ~5 min idle pays a one-time ~25 s Ollama model load.
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
