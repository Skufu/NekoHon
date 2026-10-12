# Handoff — continuing on another machine (2026-10-12)

v1 is done and proven: phases 0-7 pass (see the Phase 7 note in `README.md`;
raw evidence in `artifacts/phase7-offline.*`). Everything below is about
getting the same setup running on a second machine.

## What git carries, and what it does not

- In git: all code, tests, `window/`, docs, `artifacts/`.
- NOT in git (gitignored): `books/` (the EPUB) and `data/` (`index.json` and
  the extracted figures). A fresh clone answers `POST /ask` with
  `500 {"error": "missing index"}` until `data/` exists.

## First steps on the new machine

1. Install Ollama; make sure it serves on `127.0.0.1:11434`. (Installer is a
   ~1.6 GB download; the project download rule wants an explicit MB yes.)
2. Models (pulls = downloads; same rule):
   - `nomic-embed-text` (~274 MB) — needed for search.
   - `qwen2.5:7b` (~4.7 GB, Q4_K_M) — needed for answers.
3. Get the book data in place — pick one:
   - Copy `data/` (and `books/`) from the first machine: nothing to rebuild,
     the index is the measured one.
   - Or rebuild from the EPUB: copy the EPUB to `books/fde.epub` (its
     filename is in the first machine's `books/SOURCE.txt`), then
     `python ingest.py` and `python retrieve.py` (Ollama must be up), then
     `python retrieve.py --smoke tests/fixtures/questions.json` (expect 10/10).

## Run and verify

    python server.py
    curl -s http://127.0.0.1:8000/health     # {"ok": true, "ollama": true}
    curl -s -X POST http://127.0.0.1:8000/ask -H 'Content-Type: application/json' -d '{"book_id": "fde", "question": "What is a watermark?", "selection": null, "mode": "ask"}'
    # expect: [Ch. 8] "A watermark (Figure 8-8)..." , ch08-040, figure-8-8
    python -m unittest discover -s tests -t .   # 24 tests, must stay green

First ask after ~5 min idle pays ~25 s (model load); warm asks are ~1 s.
The machine facts in `AGENTS.md` describe the first box; do not copy them
blindly. Model swaps and prompt changes are stop-and-say items (AGENTS.md).
