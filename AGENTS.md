# AGENTS.md — ask-this-book

Agent entry point. Every statement below was checked against the code on
2026-11-01. When this file and the code disagree, the code is right: fix this
file, not the code, unless the behaviour is wrong.

## What this is

An offline multi-volume book companion. Five books are ingested, one SQLite
database each; a question is answered from five retrieved passages by a local
Ollama model; every answer carries a `[Ch. N]` citation and the figures the
passage names. Engine: Python + stdlib SQLite on `127.0.0.1:8000`. UI: a
Next.js static export that the engine serves in production.

At runtime nothing leaves the machine. The one exception is the evaluation
judge (`artifacts/harnesses/judge.py`), which may call a cloud model when a
harness asks it to; the engine, the server and the batteries never do.

Read in this order: this file → `docs/ARCHITECTURE.md` → `docs/OPERATIONS.md`.

## Map

| Path | Role |
|---|---|
| `server.py` | HTTP routes, `stream=1` NDJSON, EPUB import, static serving |
| `answer.py` | `ask` / `respond` / `explain` / `quiz`, guards, citation gate. Largest module |
| `retrieve.py` | index load/save, embeddings, dense ranking, caches |
| `store.py` | SQLite schema, atomic writes, integrity check |
| `fts_index.py` | FTS5 BM25 scoring, persisted/in-memory connection |
| `fusion.py` | RRF fusion of the dense and lexical legs |
| `keywords.py` | postings, rare-term detection (`RARE_DF`) |
| `canonical.py` | bare phrase → question ("watermark" → "What is watermark?") |
| `preprocess.py` | NFKC fold, tokenising, stemming |
| `intent.py` | intent analysis, follow-up pills |
| `readings.py` | second reading of a misread question (typo repair) |
| `acronyms.py` | short head term ("what is ai") asked with the book's own spelling |
| `captions.py` | figure-caption seeding |
| `figures.py` | figure cards, figure file lookup |
| `prompt.py` | system prompts, `ANSWER_MODEL`, `OLLAMA_KEEP_ALIVE` |
| `observe.py` | per-request JSONL trace |
| `ingest.py` | EPUB/PDF → chunks, figures, SQLite |
| `preflight.py`, `verify_index.py` | readiness, index audit |
| `web/` | Next.js UI (own README) |
| `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md` | pipeline and how to run/measure it |
| `docs/adr/` | decisions that are hard to reverse — read before changing one |
| `GLOSSARY.md` | the project's vocabulary; a term is settled there or it is not settled |
| `artifacts/` | dated measurements, zone rules in `artifacts/README.md` |
| `tests/` | 63 test modules, `python3 -m unittest discover -s tests` |
| `scripts/` | `launch.py`, `setup_models.py`, `show-passages.py` |

`GOAL.md` and `BUILD_PLAN.md` no longer exist; they were stale and were removed
on 2026-11-01. Do not recreate a plan document — put decisions in the code, a
test, or a dated file under `artifacts/`.

## Run and verify

```sh
python3 preflight.py                 # exit 0 when ready to serve
python3 -m unittest discover -s tests
python3 verify_index.py              # vector audit, exit 0 when clean
python3 store.py --check data/index.sqlite
python3 scripts/launch.py --open     # engine + warmup
```

Live checks that need no extra tooling:

```sh
curl -s localhost:8000/health
curl -s 'localhost:8000/retrieve?q=watermark&book_id=fde&k=2'
curl -s -X POST localhost:8000/ask -H 'content-type: application/json' \
  -d '{"mode":"answer","book_id":"fde","question":"what is a watermark"}'
python3 observe.py --last 5          # what the engine actually did
python3 observe.py --dry-run "how do watermarks work" --book fde --json
```

Debug retrieval with `observe.py --dry-run`, never by calling
`retrieve.search` from a scratch script — the server also canonicalises,
applies guards, fuses and picks the window, so raw search ranks differ from the
five passages the model saw.

## Guarantees the tests hold

| Guarantee | Where it lives | Test |
|---|---|---|
| refusal is exactly `Not in this book.` | `answer._refusal`, `prompt.REFUSAL` | `test_contract`, `test_answer` |
| 200 body keys are `answer`, `citations`, `figures`, `refused`, `followups` | `answer.py` return paths | `test_contract` |
| every answer body names a passage, or is a refusal | citation gate (`citation_recovered` / `uncited_refused`) | `test_answer`, `test_free_answer` |
| routes: `/`, `/health`, `/figures/{id}`, `/retrieve`, `/chunks`, `POST /ask` | `server.py` | `test_reader_routes`, `test_server_multibook`, `test_server_packaging` |
| `stream=1` emits `token`, `reset`, then exactly one `final` or `error` | `server.py` | `test_stream_contract` |
| `stream=1` on an import emits `book`, then `progress {done,total}`, then exactly one `final` or `error` | `server._handle_import` | `test_stream_contract` |
| an imported file name becomes a book id of at most 64 characters, and a long index file name still writes | `ingest.book_id_for`, `store.write_index` | `test_ingest`, `test_store` |
| logic modules carry no book ids, chunk ids, chapter numbers or query strings | the listed modules | `test_generalization` |
| every in-book quote in `data/finetune/*.jsonl` is verbatim | data factory | `test_training_quotes` |
| UI style: tokens only, no hex outside `tokens.css`, no emoji, allowlisted deps | `web/` | `test_frontend_rules` |
| sealed and fair `locked` items never leak into training or dev | datasets | `test_eval_leakage`, `test_hard_mt_leakage` |

Changing one of these means changing its test in the same edit, and re-running
the harness that measures it.

## Operational facts

- A running server keeps the code and model it loaded at start. Restart it
  after any `*.py` edit or `ANSWER_MODEL` change, then confirm with
  `curl -s localhost:8000/health` (`warm.answer_model`).
- One listener on `:8000`. `scripts/launch.py` clears only `server.py`
  processes from that port.
- `data/` and `books/` are gitignored: index databases, figure files, model
  weights, book binaries. `models/` holds committed Modelfiles.
- Figure files are individual PNGs under `data/figures/<book_id>/`. If
  `GET /figures/...` 404s, the files are missing — re-run `ingest.py` for that
  book. `ingest.py` wipes the target figures directory first.
- An imported EPUB's id is `ingest.book_id_for(<file name>)`: slugged and
  capped at 64 characters, because the id is a file name three times over and
  Anna's Archive names derive 200+ characters. Two long names that share a
  prefix keep a digest suffix, so they never overwrite each other.
- `ingest.py` then `retrieve.py` is the rebuild path: ingest writes chunks and
  figures without vectors, `retrieve.py` embeds what is missing (hash-checked,
  idempotent) and saves.
- Traces are on by default for HTTP (`artifacts/runs/traces.jsonl`),
  `OBSERVE=0` disables, `OBSERVE_LOG=<path>` redirects. Eval and unit runs do
  not write unless `OBSERVE_LOG` is set.
- `OLLAMA_KEEP_ALIVE` defaults to `10m`; `-1` pins the model (measured at
  6.9 GB working set over 8 h). Cold load is ~25 s, warm asks ~1 s.
- Iterate evals on `--split dev`. The sealed suite and the fair `locked` split
  are hold-outs; `trace_inspect.py` redacts their text unless
  `--allow-locked-text` is passed, and looking invalidates the number.

## Working style in this repo

- Measure, then state the number and the command that produced it. A change
  nobody re-measured is unproven.
- Fix the root cause. A guard bolted onto a symptom is a second bug.
- Generalise: no book-specific ids or question strings in the logic modules
  (enforced by `test_generalization`). Thresholds justified only by the test
  they keep green are fitted constants; say so when you see one.
- Dated reports under `artifacts/` are snapshots. Older than two days means
  stale: re-run, do not build on it.
- Do not commit unless asked.

## This machine

macOS arm64, `python3` 3.13.5, Node 22.x, Ollama on `127.0.0.1:11434`, engine on
`:8000`, web dev server on `:3100`. `web/out/` exists, so `GET /` serves the
built UI.
