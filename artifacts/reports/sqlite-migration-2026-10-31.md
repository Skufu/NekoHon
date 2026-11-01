# SQLite FTS5 index storage — 2026-10-31

JSON index files were replaced by one SQLite database per book. The engine keeps
its in-memory dict shape, so retrieval, answer logic, and the reader contract are
unchanged; this record covers the storage swap and what it measured.

## Store

`store.py` owns schema version 1:

| Object | Contents |
| --- | --- |
| `meta` | JSON value per top-level index key; `schema_version` |
| `chunks` | position, `chunk_id`, chapter, heading, text, source, section, doc, anchor, blocks, figures, embedding blob, input hash, `extra` |
| `figures` | position, `figure_id`, chapter, caption, referencing paragraph, file, anchor, source, embedding blob, input hash, `extra` |
| `chunks_fts` | FTS5 porter unicode61 over `(heading, section, body)` |
| `chunks_trigram` | FTS5 trigram over `heading + section + body` |

Unknown record keys travel in `extra`, so no field is lost. Embeddings are
little-endian float64 blobs: loaded values are identical to the JSON store, and
the dense ranker still builds its hot-path matrix in float32. Writes go to a
unique `.tmp` database and replace the target with `os.replace` only after a
successful commit. Readers open `mode=ro`. `fts_index` opens the persisted FTS
tables instead of rebuilding them in memory.

Paths: `data/index.sqlite` for the default book, `data/index.<book_id>.sqlite`
for others. `retrieve.book_index_path(book_id)` is the only resolver.

## Migration

`python store.py --migrate <json>` converted the five catalog indexes. Each pair
was compared with `store.compare_indexes` (metadata, every chunk and figure
field, every embedding) and printed `equivalent`; the JSON files were then
deleted. Old bake-off/backup JSON files (`index.pre-*`,
`index.embeddinggemma-2.json`, `index.quantbook.json`) were left untouched.

| Book | JSON | SQLite | Change |
| --- | ---: | ---: | ---: |
| fde | 10.1 MiB | 15.1 MiB | +49% |
| quantization | 5.0 MiB | 7.6 MiB | +51% |
| ddia | 12.5 MiB | 19.6 MiB | +57% |
| ai-engineering | 10.6 MiB | 17.0 MiB | +60% |
| ai-agents | 6.6 MiB | 10.3 MiB | +56% |
| **total** | **44.7 MiB** | **69.4 MiB** | **+55%** |

Disk grows because the FTS5 tables are now persisted; the embeddings themselves
are smaller as binary blobs than as JSON decimal text.

## Measured performance

Host: this Mac, Python 3.13.5. Same process, `fde`, one simulated query vector so
Ollama and network are excluded. The JSON side was reconstructed from the
database after migration; its file size matched the deleted original exactly
(10,574,128 bytes). Medians unless noted.

| Workload | JSON | SQLite |
| --- | ---: | ---: |
| Parse/read only | 43.5 ms | 16.4 ms |
| Cold load + prepare (7 trials) | 151.5 ms | 126.2 ms |
| First FTS query | 52.5 ms (build) | 1.0 ms (open) |
| Warm FTS query | 0.29 ms | 0.20 ms |
| Dense rank, warm | 0.29 ms | 0.20 ms |
| Full pre-LLM retrieval, first call | 53.9 ms | 2.3 ms |
| Full pre-LLM retrieval, warm | 0.96 ms | 0.85 ms |
| In-memory FTS tables per book | 5.97 MiB | none (page cache only) |

The win is startup and the first lexical query; warm requests were already
sub-millisecond, so user-visible ask latency is unchanged — generation dominates
at seconds.

## Verification

```sh
python store.py --check data/index.sqlite data/index.quantization.sqlite \
    data/index.ddia.sqlite data/index.ai-engineering.sqlite
python verify_index.py --book-id fde
python preflight.py
python -m unittest tests.test_store tests.test_fts_runtime
python observe.py --dry-run "what is a watermark" --book fde --json
python observe.py --dry-run "what is a watermark" --book fde \
    --index-file data/index.json --json   # before deletion; same five passages
```

- `store.py --check`: all five databases clean (quick_check, schema version,
  FTS row counts equal chunk counts).
- `verify_index.py --book-id` × 5: vectors clean, storage clean.
- `preflight.py`: ready.
- FTS BM25 scores identical to the in-memory build for three probe queries.
- fde top-10 chunk ids identical for three Ollama-embedded queries.
- Full dry-run pipeline: same five passages, `lexical_backend=fts5` both stores.
- Live engine after restart: `POST /ask` answered watermark (fde) and quorum
  (ddia); `GET /chunks` served 1,042 / 473 / 1,306 chunks from SQLite.
- Unit suite: 1,342 tests, 1,337 pass. The five failures are outside storage:
  PyMuPDF absent, cross-encoder weights not cached, `data/figures/` empty, and
  `test_agentic` expecting an older passage dict without `section`/`anchor`.
- `verify_index.py` and `preflight.py` now run `store.check_database` as well:
  SQLite `quick_check`, schema version, and `chunks_fts` / `chunks_trigram` row
  counts must equal the `chunks` row count. All five databases report clean.
- Web trace dashboard: `web/app/api/traces/route.ts` reads chunk text from the
  SQLite index with Node's built-in `node:sqlite` (read-only), no JSON index.
  `npx tsc --noEmit` and `npm run build` are green; `package.json` declares
  `node >= 22.5` for that builtin.

## Evidence note

A `sealed-eval.py` run after migration (default model, 30 items, in-process)
passed 28/30 at a 5.807 s mean and rewrote
`evidence/sealed-eval/sealed-eval-2026-10-24.model-nekohon_q35_2b_x3_2e.json`.
It replaced the 2026-10-31 03:03 file of the same name, whose log recorded the
same 28/30 at 4.06 s mean and 18/27 pin hits versus 17/27 here. The prior JSON is
not recoverable; the log remains under
`runs/data-release-2026-10-29/candidate-run-2026-10-31/sealed-shipped.log`.

## Historical references

Dated probes, reports, and evidence written before 2026-10-31 still say
`data/index.json`; they are records, not current instructions, and will not run
against current data without a path update. Undated reusable probes that read
the index were switched to `retrieve.load_index` / `data/index.sqlite`.
