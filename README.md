# NekoHon (`猫本`) — Local-First Book Reading Companion

An offline reading companion for EPUBs. Load a book, ask questions about it,
and get answers with citations to the passage used and the figure it points
at. Everything runs on your machine: retrieval, intent, and generation run
locally (in-process or via Ollama on localhost), with no cloud APIs and zero
telemetry.

Built for ordinary laptops. The default answer model is about 1.3 GB and the
engine runs on a fast, lightweight local stack (SQLite FTS5, `numpy` SIMD vector
search, and optional local reranking).

## What you can do

- Highlight any passage and ask for a gloss or a follow-up.
- Ask how two ideas compare (`How does an AI agent compare to an LLM?`) and get
  a two-sided answer with the book's own contrast sentence, or a clear boundary
  when the book covers only one side.
- Ask a question across the whole book and get an answer with a `[Ch. N]`
  citation that jumps to the source paragraph.
- Browse a multi-book wooden-shelf library, switch volumes instantly, and
  import a new EPUB by drag and drop.
- See the figure the cited passage references, zoomable, without leaving the
  reader.
- Get a polite refusal when the answer is not in the book.

## Quickstart

Prerequisites: Python 3.9+, Node.js 22+, and Ollama on `127.0.0.1:11434` (or in-process local runtime).

```sh
pip install -r requirements.txt
ollama pull nomic-embed-text
python scripts/setup_models.py --install --model nekohon_q35_2b_x3_2e
python ingest.py
python retrieve.py
python server.py            # engine on :8000
cd web
npm install
npm run dev                # reader on :3100
```

Open http://localhost:3100.

## Model

The shipped answer model is hosted on Hugging Face:
[`Skufu1/nekohon-q35-2b`](https://huggingface.co/Skufu1/nekohon-q35-2b)
— Qwen3.5-2B fine-tune, Q4_K_M, 1.31 GB, sha256 `1621bcb3…`. The setup script
downloads it, verifies the checksum, and imports it into Ollama.

Only weights and a Modelfile are published there. No book text, index,
figures, or training data is included.

## Under the hood

Architecture, retrieval pipeline, model lineup and sizes, the HTTP contract,
local per-request JSONL tracing (`observe.py`, `artifacts/harnesses/trace_inspect.py`),
testing gates, and offline proof live in
[docs/ENGINEERING_AND_BENCHMARKS.md](docs/ENGINEERING_AND_BENCHMARKS.md).

Comparison questions take a separate two-sided path (`_comparison_body` in
`answer.py`, `COMPARE_SYSTEM` in `prompt.py`); the measured before/after is in
[artifacts/reports/comparison-answers-2026-10-29.md](artifacts/reports/comparison-answers-2026-10-29.md).

## License

GPL-3.0. See [LICENSE](LICENSE).