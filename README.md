# NekoHon (`猫本`) — Local-First Book Reading Companion

An offline reading companion for EPUBs. Load a book, ask questions about it,
and get answers with citations to the passage used and the figure it points
at. Everything runs on your machine: retrieval, intent, and generation use
Ollama on localhost, with no cloud APIs, no database, and zero telemetry.

Built for ordinary laptops. The default model is about 2 GB and the engine
uses only Python's standard library.

## What you can do

- Highlight any passage and ask for a gloss or a follow-up.
- Ask a question across the whole book and get an answer with a `[Ch. N]`
  citation that jumps to the source paragraph.
- Browse a multi-book wooden-shelf library, switch volumes instantly, and
  import a new EPUB by drag and drop.
- See the figure the cited passage references, zoomable, without leaving the
  reader.
- Get a polite refusal when the answer is not in the book.

## Quickstart

Prerequisites: Python 3.9+, Node.js 22+, and Ollama on `127.0.0.1:11434`.

```sh
ollama pull nomic-embed-text
python scripts/setup_models.py --install
python ingest.py
python retrieve.py
python server.py            # engine on :8000
cd web
npm install
npm run dev                # reader on :3100
```

Open http://localhost:3100.

## Under the hood

Architecture, retrieval pipeline, model lineup and sizes, the HTTP contract,
testing gates, and offline proof live in
[docs/ENGINEERING_AND_BENCHMARKS.md](docs/ENGINEERING_AND_BENCHMARKS.md).

## License

GPL-3.0. See [LICENSE](LICENSE).