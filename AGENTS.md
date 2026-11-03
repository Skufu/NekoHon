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
| `keywords.py` | postings, rare-term detection (`RARE_DF`), named-term detection (`NAMED_DF`) |
| `canonical.py` | bare phrase → question ("watermark" → "What is watermark?") |
| `preprocess.py` | NFKC fold, tokenising, stemming |
| `intent.py` | intent analysis, follow-up pills |
| `readings.py` | second reading of a misread question (typo repair) |
| `acronyms.py` | short head term ("what is ai") asked with the book's own spelling |
| `captions.py` | figure-caption seeding |
| `figures.py` | figure cards, figure file lookup |
| `prompt.py` | system prompts, `ANSWER_MODEL`, `OLLAMA_KEEP_ALIVE`, sampler sets |
| `bookkind.py` | book kind (fiction or non-fiction) and the generation settings it picks |
| `entity.py` | "who is X": the book's own sentences about a person, one per chapter |
| `observe.py` | per-request JSONL trace |
| `ingest.py` | EPUB/PDF → chunks, figures, SQLite |
| `preflight.py`, `verify_index.py` | readiness, index audit |
| `web/` | Next.js UI (own README) |
| `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md` | pipeline and how to run/measure it |
| `docs/adr/` | decisions that are hard to reverse — read before changing one |
| `GLOSSARY.md` | the project's vocabulary; a term is settled there or it is not settled |
| `artifacts/` | dated measurements, zone rules in `artifacts/README.md` |
| `tests/` | 67 test modules, `python3 -m unittest discover -s tests` |
| `scripts/` | `launch.py`, `setup_models.py`, `show-passages.py`, `book-kind.py` |

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
| the lexical leg joins for a named term as well as a rare one, and widens the window by additions instead of evicting the dense head; `added=0` is byte-identical to the old fusion | `keywords.lexical_terms`, `fusion.fuse(added=)` | `test_lexical_gate`, `test_fusion_lexical_cap` |
| logic modules carry no book ids, chunk ids, chapter numbers or query strings | the listed modules | `test_generalization` |
| a fiction book is answered warm from eight passages with a paragraph kept, a technical book cold from five with one gloss line | `bookkind.for_index`, `answer._fiction_body` | `test_fiction_profile` |
| "who is X" on a fiction book is answered from the book's own sentences, one per chapter, with the titles it uses; nothing is generated | `entity.py`, `answer._entity_profile_body` | `test_entity_profile` |
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
- A book's kind is `index["kind"]` when set, else read off dialogue density
  (`bookkind.detect_kind`). `python3 scripts/book-kind.py <index>` prints the
  numbers and the kind; `--set fiction` pins it for a book the guess gets
  wrong. `ingest.py --kind fiction` writes it at ingest time. The trace records
  `query.generation_profile`.
- The fiction knobs are environment-readable, so a new book can be tried
  without an edit: `FICTION_TEMPERATURE` (0.55), `FICTION_PASSAGE_LIMIT` (8),
  `FICTION_QUOTE_TARGET` (2), `FICTION_SAMPLE_ROUNDS` (3). A fiction answer is
  two or three generations (one quote each, merged), measured at 20 s a
  question on the M-series machine against 5 s for a technical one.
- Retrieval scoreboard: `python3 artifacts/harnesses/retrieval-recall.py` over the
  authored six-book set (`artifacts/datasets/retrieval/retrieval-recall-2026-11-02.jsonl`,
  42 rows). It reports chapter coverage@5 and chunk recall@5 per book; coverage
  shows diffusion, recall decides a ship. Dense-only equals the pre-fix rare
  gate, so any future lexical change must be measured against this file, not
  argued.
- The lexical gate is `keywords.lexical_terms`: a term opens the BM25 leg when it
  is rare (`df <= RARE_DF = 8`) or named in the book (capitalised in >= 2 chunks
  and in >= 50% of its mentions). Named detection costs ~60 ms once per book per
  process (ddia, 1306 chunks), then 0.6 us. `rare()` is kept for callers that
  want the old question.
- Fusion appends lexical candidates instead of re-placing dense ones:
  `MAX_LEXICAL_ADDITIONS_FICTION = 2`, `MAX_LEXICAL_ADDITIONS = 1`.
  `MAX_LEXICAL_CANDIDATES` stays 1 because raising it cost recall: cap 2 dropped
  quantization 1.000 -> 0.875, cap 3 dropped novel 0.700 -> 0.600. The window
  grows by what was appended and the trace records `fusion_added=<n>`.
- `mode: "teach"` is the stuck-reader mode: plain explanation in the model's own
  words plus one line starting `Example:`, which is the model's illustration and
  says so. Two calls (explanation prefilled `In plain words, `, example prefilled
  `Example: `), citations attached by the engine, refusal still exact. A
  non-Latin or shapeless explanation is rejected and degrades to `mode: "answer"`
  rather than refusing. Example correctness is not checked — measured 3 right, 1
  wrong (`artifacts/reports/teach-mode-2026-11-02.md`).
- A "who is X" question on a fiction book takes the entity path (`entity.py`)
  before retrieval: the sentences that name the person, one per chapter, plus
  the titles their own sentences use ("Known as: Immortal Demon King Atofe").
  No model call, so it answers in ~15 ms and cannot invent. It fires only for
  a fresh question on a fiction book, and only when the name appears in at
  least two chapters; otherwise the normal path answers.
- Answer length is `TECHNICAL_ANSWER_WORDS` and `FICTION_ANSWER_WORDS`, in
  words of the answer's own prose (quotes excluded). `0`, the default, keeps
  every prompt exactly as measured; any other value aims the answer and forces
  the gloss pass. The target is an aim, not a guarantee: this fine-tune stops
  at about 65 words of gloss, measured 26 -> 36 -> 57 words for targets 0, 80,
  200 on `ddia`, and 16 -> 22 -> 29 on the novel (`artifacts/reports/answer-length-2026-11-02.md`).
  `outcome.answer_words` in the trace reports what was actually written.
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
