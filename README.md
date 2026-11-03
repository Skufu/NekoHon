# NekoHon (猫本) — a local book companion that shows its receipts

Read an EPUB, ask it something, get an answer built from the book's own
sentences — with a `[Ch. N]` citation you can jump to and the figure the
passage names. Retrieval, ranking and generation all run on your machine:
in-process or through Ollama on `127.0.0.1:11434`. No cloud calls, no
telemetry, nothing to sign up for.

The default answerer is a 1.3 GB Qwen3.5-2B fine-tune; the whole stack fits on
an ordinary laptop.

## What it does

- **Ask across the book.** Five passages are retrieved, the model answers from
  them, and every quote is checked against the passages: a body that names no
  passage becomes `Not in this book.` rather than an invented answer.
- **Highlight and gloss.** Select a sentence and get its meaning in place,
  with the sentence quoted and cited.
- **Compare two ideas.** "How does an agent compare to an LLM?" keeps both
  sides, quotes the book's own contrast sentence, or says plainly when the book
  covers only one side.
- **See the figure.** When the cited passage names a figure, the picture is
  attached and zoomable in the reader.
- **Follow up.** "Explain that simpler", "and the second one?" resolve against
  the previous turn without losing the passage.
- **Keep a shelf.** Five volumes, instant switching, and drag-and-drop EPUB
  import that ingests, embeds and catalogues a new book in one step.
- **Refuse honestly.** `Not in this book.` is exactly that sentence, and it
  means the book does not cover the thing — never "I did not understand".

## Quickstart

You need Python 3.9+, Node 22.5+ (for the UI), and Ollama running locally.

```sh
python3 -m pip install -r requirements.txt
ollama pull nomic-embed-text
python3 scripts/setup_models.py --install --model nekohon_q35_2b_x3_2e

python3 ingest.py            # books/fde.epub -> data/index.sqlite + figures
python3 retrieve.py          # embed the index (skips what is already embedded)

python3 scripts/launch.py --open        # engine on :8000, opens the reader
# or: python3 server.py                 # engine only
cd web && npm install && npm run dev    # reader on :3100, against :8000
```

`python3 preflight.py` tells you whether anything is missing before you start.

## Stack

| Layer | What it uses |
|---|---|
| Storage | SQLite, one database per book, with FTS5 (`porter unicode61` + trigram) |
| Retrieval | `nomic-embed-text` (768-d) vectors scored with `numpy` SIMD dot products, RRF-fused with lexical BM25 |
| Generation | local Ollama chat model, temperature 0 for technical books and a warmer sampler for fiction, `[Ch. N]` citations checked against the shown passages, answer length aimable in words, `mode: teach` for a plain explanation with a labelled example |
| Figures | extracted at ingest into `data/figures/`, served by the engine |
| UI | Next.js 16 static export, one zustand store, design tokens in `web/app/tokens.css` |
| Traces | one JSON line per request in `artifacts/runs/traces.jsonl` |

## Docs

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the pipeline end to end, guards, citation
  gate, trace schema, HTTP surface.
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — install, run, check, measure,
  troubleshoot.
- [`GLOSSARY.md`](GLOSSARY.md) — the vocabulary in plain words.
- [`artifacts/README.md`](artifacts/README.md) — every measurement and where it
  lives.

## Model

Published weights only — no book text, index, figures or training data:
[`Skufu1/nekohon-q35-2b`](https://huggingface.co/Skufu1/nekohon-q35-2b)
(Qwen3.5-2B fine-tune, Q4_K_M, 1.31 GB, sha256 `1621bcb3…`).
`scripts/setup_models.py` downloads it, verifies the checksum and imports it
into Ollama.

## License

GPL-3.0. See [LICENSE](LICENSE).
