# Operations

How to install, run, check and measure this repo. Commands were executed on
2026-11-01 (macOS arm64, `python3` 3.13.5, Ollama 0.40.x on `127.0.0.1:11434`);
the output quoted is that day's real output.

## Prerequisites

- `python3` ≥ 3.9 (3.13.5 here). The engine is standard-library plus the
  packages in `requirements.txt`.
- `node` ≥ 22.5 and npm, only for `web/`.
- Ollama on `127.0.0.1:11434` with `nomic-embed-text` pulled and the answer
  model imported.

```sh
python3 -m pip install -r requirements.txt
ollama pull nomic-embed-text
python3 scripts/setup_models.py --status          # what is on disk, SHA-checked
python3 scripts/setup_models.py --install --model nekohon_q35_2b_x3_2e
```

`setup_models.py` downloads the GGUF from Hugging Face, verifies its SHA-256,
writes `data/models/<tag>/` and imports it into Ollama. `--model all` installs
every registered tag; `--package-release` writes a release manifest; `--warmup`
only loads models into memory.

## Build an index for a book

```sh
# EPUB or PDF in, SQLite + figure files out
python3 ingest.py --epub books/fde.epub --book-id fde

# embeddings (skips anything whose stored input hash already matches)
python3 retrieve.py --book-id fde
```

`ingest.py` writes `data/index.<book_id>.sqlite` (or `data/index.sqlite` for
`fde`), the figure files under `data/figures/<book_id>/`, and the catalog entry
in `data/books.json`. It **deletes existing figure files** in the target
directory first.

`retrieve.py` embeds with `nomic-embed-text` (768 dims) and saves. It is
idempotent by content hash, so re-running it after an ingest costs only new
chunks.

The same import is available over HTTP (`mode: "import"`) and from the web UI
(drag and drop).

## Run

```sh
python3 scripts/launch.py --open        # Ollama check, port hygiene, server, warmup
python3 scripts/launch.py --dry-run     # what it would do
python3 server.py                       # or just the engine
PORT=8001 python3 server.py             # --port wins over $PORT
```

Engine on `http://127.0.0.1:8000`. Reader in development:

```sh
cd web && npm install && npm run dev    # http://localhost:3100
```

Production build: `cd web && npm run build` → `web/out/`, which `server.py`
serves at `/`. One URL, one process.

A running server keeps the code and model it loaded at start. **Restart it after
any `*.py` edit or `ANSWER_MODEL` change**; `GET /health` reports the warm-up
result and `answer_model`, and `ollama ps` shows what is resident.

## Check

| Command | Proves | Expected |
|---|---|---|
| `python3 preflight.py` | ready to serve: python, book, index, ollama, models, vectors, storage | exit 0, `ready: python server.py` |
| `python3 verify_index.py` | vectors: NaN/zero-norm/dim drift/stale input/provenance | exit 0, `clean` |
| `python3 store.py --check data/index.sqlite` | SQLite `quick_check`, schema version, FTS row counts | `<path>: clean` |
| `python3 -m unittest discover -s tests` | the whole suite | see below |
| `python3 artifacts/harnesses/secret-scan.py` | git history and tracked tree for secrets | exit 1 on any hit |
| `python3 artifacts/prune.py --plan` | artifact hygiene plan (walks `artifacts/`, slow) | advisory, always exit 0 |

Suite state on 2026-11-01: **1,367 tests, 1 failure**
(`test_server_multibook.ServerMultiBookTest.test_figures_cover_mime_types`,
`404 != 200`). The cause is environmental: `data/figures/` holds no figure
files, so `GET /figures/cover` has nothing to serve. Re-run `ingest.py` for the
affected books to re-extract them.

## Look at what the engine did

```sh
python3 observe.py --last 5            # summary of recent traces
python3 observe.py --failures          # refusals, guard blocks, anomalies
python3 observe.py --slow 2000         # requests over 2 s
python3 observe.py --id <trace_id>     # one request in full
python3 observe.py --diff <a> <b>      # two requests side by side
python3 observe.py --json --last 20    # machine-readable, for agents
```

`observe.py` delegates to `artifacts/harnesses/trace_inspect.py`. Traces land in
`artifacts/runs/traces.jsonl`; `OBSERVE=0` turns them off and `OBSERVE_LOG=<path>`
moves them.

Dry-run retrieval without a model call:

```sh
python3 observe.py --dry-run "how do watermarks work" --book fde --json
```

That is the right way to debug bad answers — it runs the same canonicalisation,
guards, fusion and window selection the server does. Calling
`retrieve.search` directly does not.

## Measure

Eval harnesses live in `artifacts/harnesses/`. Most run in-process against
Ollama and never need the server; the ones that say "live" need `:8000`.

| Harness | Measures | Command |
|---|---|---|
| `fair-eval.py` | the fair set, dev/locked splits, per-stage attribution | `python3 artifacts/harnesses/fair-eval.py --split dev` |
| `sealed-eval.py` | 60-item sealed suite | `python3 artifacts/harnesses/sealed-eval.py` |
| `hard-mt-eval.py` | 12 hard multi-turn items | `python3 artifacts/harnesses/hard-mt-eval.py` |
| `hard-bench.py` | 60-item self-certifying bench | `python3 artifacts/harnesses/hard-bench.py` |
| `comparison-matrix.py` | comparison answers before/after | `python3 artifacts/harnesses/comparison-matrix.py --label after` |
| `trace-regression.py` | 14 multi-turn trace regressions | `python3 artifacts/harnesses/trace-regression.py` |
| `step2-battery.py` | the commit-gate battery (live) | `python3 artifacts/harnesses/step2-battery.py` |
| `groundedness.py` | 4-gram support meter | `python3 artifacts/harnesses/groundedness.py --label answer` |
| `judge-stability.py` | how often the judge flips a verdict | `python3 artifacts/harnesses/judge-stability.py --file <run.json> --n 3` |

`ls artifacts/harnesses/*.py` is the full inventory (28 CLIs, 5 libraries).
Every harness writes JSON evidence under `artifacts/evidence/` or
`artifacts/runs/`; promoted evidence belongs in `artifacts/` only when a doc
names it (see `artifacts/README.md`).

Iterate on `--split dev`. The sealed and fair `locked` splits are hold-outs;
`trace_inspect.py` hides their text unless `--allow-locked-text` is passed, and
peeking invalidates the number.

## Models

| Tag | Role | Size |
|---|---|---|
| `nekohon_q35_2b_x3_2e` | default answerer | 1.31 GB |
| `nekohon_q35_2b_x3` | previous Qwen3.5 run | 1.31 GB |
| `nekohon_x3` | previous desktop answerer (revert) | 1.93 GB |
| `nekohon_x3_mobile` | edge/companion variant | 986 MB |
| `nomic-embed-text` | embeddings, 768 dims | 274 MB |

Swap the answerer without editing code:

```sh
ANSWER_MODEL=nekohon_q35_2b_x3_2e python3 server.py
ANSWER_MODEL=nekohon_x3 python3 server.py
```

then restart the server (it holds the model it warmed at start). Model files
under `data/models/` are gitignored; `models/` holds the committed Modelfiles.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| answers stop changing after an edit | server holds old code/model | restart `server.py` |
| `address already in use` | a second engine | `scripts/launch.py` kills only `server.py` on the port; otherwise stop the old one |
| `/figures/...` 404s, answers attach no figure | figure files missing under `data/figures/` | re-run `ingest.py` for the book |
| first ask takes ~25 s | cold model load | `OLLAMA_KEEP_ALIVE=10m` is already the default; pin with `-1` if RAM allows |
| `missing index` on `/chunks` | book not ingested | `python3 ingest.py --epub books/<book>.epub --book-id <book>` |
| eval numbers cannot be reproduced | stale evidence | re-run the harness; docs older than two days are stale by house rule |
