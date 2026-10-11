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
- Report measured results, not impressions: files changed, exact command, real
  output. If a test fails, say so with the actual failure.

## Current state (update this block when a phase lands)

- Done: Phase 0 (book at `books/fde.epub`), 0b (README corrected for this
  book), 1 (fixture + `server.py` + contract test — green), 2 (ingest).
- Phase 3 nomic smoke is done. `data/index.json` has 1065 chunk vectors and
  111 figure vectors, 768 dims. `python retrieve.py --smoke tests/fixtures/questions.json`
  printed 10/10 top-10 in 5.9 seconds on 2026-10-11. The list is in the README.
  Two hits were rank 7 and rank 8. Do not raise top-k.
- Next: Phase 3b bake-off. Same 10 questions, same frozen chunks, EmbeddingGemma 2
  in its own index file. Do not start Phase 4 until that table exists.
- Not started: 3b, 4, 5, 6, 7, 8.

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
  `qwen2.5:7b` is not pulled yet.
- MLX runtime installed 2026-10-11 from `ollama-windows-amd64-mlx.zip`,
  1403168802 bytes, extracted into the Ollama program folder. Zip deleted.
  `embeddinggemma-2:270m-bf16-text` (574 MB) is on disk. Smoke embed returned
  768 dims. Runner shows `mlx`, `100% GPU`. Do not pull `embeddinggemma` (v1)
  or the picture/audio tags. This book only needs the text tag.
- Do not delete `tests/__init__.py`: a user-site `tests` package shadows the
  directory without it (the file itself explains why).
- `books/` and `data/` are gitignored. On a fresh machine, re-run Phase 0: the
  original EPUB path is recorded in `books/SOURCE.txt`.
