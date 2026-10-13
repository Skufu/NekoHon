# Setup on a Mac (testing guide)

The engine is Python standard library only — there is nothing to install for
the app itself. Two external pieces: Python 3 and Ollama with two models
(5.0 GB of downloads, once). Everything after that runs offline on localhost.

## 0. What you need

- A Mac (Apple Silicon or Intel), 16 GB RAM recommended — the answer model is
  4.7 GB on disk and similar in memory; an 8 GB machine will swap. Check
  yours: `sysctl -n hw.memsize` in bytes (17179869184 = 16 GB).
- Python 3.9 or newer: `python3 -V`. The Xcode Command Line Tools `python3`
  qualifies; for parity with the dev box use `brew install python@3.12`.
- The book (it is not in the repo — the EPUB is copyright). Get the file from
  Adrian or use your own copy of *Fundamentals of Data Engineering*
  (Reis & Housley, O'Reilly, ISBN13 9781098108250). It goes to
  `books/fde.epub`.

## 1. Get the repo and the book

The repo is private: ask to be added as a collaborator.

```sh
git clone git@github.com:nekolabs-studio/epub-local.git
cd epub-local
# put the EPUB at books/fde.epub
```

## 2. Install Ollama, natively (not Docker — see the last section)

```sh
brew install --cask ollama        # or download from https://ollama.com/download
ollama pull nomic-embed-text      # 274 MB
ollama pull qwen2.5:7b            # 4.7 GB
ollama list                       # both must appear
```

Native Ollama uses the Mac GPU (Metal). Warm answers take about a second;
the first answer after idle reloads the model (tens of seconds).

## 3. First check: the test suite (needs no book, no Ollama, no network)

```sh
python3 -m unittest discover -s tests
```

Green means the engine runs on this Python. This is the same suite the dev
box runs; if it fails on your Mac, stop and send the output.

## 4. Preflight, then build the local index

```sh
python3 preflight.py
```

The checker reads the engine's own paths and prints exactly what is missing
(Python version, the EPUB, the index, Ollama, the two models, and the vector
audit). It exits 0 when ready.

```sh
python3 ingest.py      # EPUB -> data/index.json + data/figures/ (no vectors)
python3 retrieve.py    # embed 1042 chunks + 111 figures (14.5 s measured on the dev box)
python3 preflight.py   # should now say ready
```

## 5. Run it

```sh
python3 server.py
```

Open <http://127.0.0.1:8000/> and ask "What is a watermark?" in mode `ask`.
You should get a checked quote with a `[Ch. 8]` tag, one gloss line, and the
Figure 8-8 image.

## 6. Test it (what "testing" means here)

Unit suite, from step 3: `python3 -m unittest discover -s tests`.

Machine checks without a browser:

```sh
curl -s http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/ask -H "Content-Type: application/json" \
  -d '{"book_id": "fde", "question": "What is a watermark?", "selection": null, "mode": "ask"}'
```

The HTTP battery — 18 asks in four lines: golden 10/10 answered, typo probes,
rare-word probes, and the France refusal staying exact. Needs Ollama plus a
fresh `server.py`:

```sh
python3 artifacts/step2-battery.py
```

The eval harness (optional) needs one more model — the LLM judge, separate
from the answer model:

```sh
ollama pull granite4.1:8b     # 5.3 GB, eval only
```

Port hygiene: exactly one server may listen on :8000. macOS check:
`lsof -nP -iTCP:8000 -sTCP:LISTEN`. (Two servers can share :8000 silently —
see `AGENTS.md`. The Windows equivalents `netstat | findstr` do not apply on
a Mac.)

## Why not Docker

- Ollama in a Linux container on macOS has **no GPU**: Metal is not available
  to containers. The 7B model falls back to CPU inference — several seconds
  per answer instead of about one, and much slower cold loads.
- The app itself gains nothing from a container: pure Python stdlib, no
  dependencies, no database, no services to isolate.
- Docker adds a VM, a 5 GB volume for the models, and port plumbing — more
  moving parts, which is the opposite of what two testers want.

If you still want it, the engine is unchanged and just talks to the container:

```sh
docker run -d --name ollama -p 127.0.0.1:11434:11434 -v ollama:/root/.ollama ollama/ollama
docker exec -it ollama ollama pull nomic-embed-text
docker exec -it ollama ollama pull qwen2.5:7b
```

Expect CPU-speed answers. Native Ollama is the supported path.

## Gotchas

- **8 GB RAM Macs**: `ANSWER_MODEL=llama3.2:3b python3 server.py` after
  `ollama pull llama3.2:3b` is the weak-machine fallback (2.0 GB); it may
  refuse more often — it is not the dev model.
- The index (`data/index.json`, ~10.5 MB) contains book text. It is
  gitignored and must stay out of git, even a private repo.
- Rebuilding: if the index ever looks wrong, re-run `python3 retrieve.py`;
  do not hand-edit vectors.
- First run of anything is the slowest (model load). The recorded latency on
  the dev box: warm asks 0.4-1.2 s, first ask after ~5 min idle ~25 s.
- Windows-only commands appear in `README.md` and `AGENTS.md` (for example
  `findstr`); the Mac equivalents are here.
