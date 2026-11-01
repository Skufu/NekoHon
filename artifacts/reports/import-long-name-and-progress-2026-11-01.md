# Import: the long name that failed, and the framed wait — 2026-11-01

Two changes, both measured live against the engine on `127.0.0.1:8000` on
macOS arm64, `python3` 3.14.8, Ollama on `11434`.

## 1. `import failed: unable to open database file`

### Reproduction

The failing input was an Anna's Archive EPUB whose on-disk stem is 204
characters. `server._handle_import` derived the book id from the uploaded
file name with `re.sub(r"[^a-zA-Z0-9_-]", "-", ...)`, which produced a
**226-character** id for the browser's file name.

The id becomes `data/index.<id>.sqlite` — 240 bytes, legal on APFS. The write
went through `store.write_index`, which created its atomic temp file as
`tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp")`: 253 bytes, still
legal. SQLite then creates `<temp>-journal` beside it — **261 bytes**, past the
255-byte `NAME_MAX` — and `sqlite3.connect`/`executescript` returned:

```
sqlite3.OperationalError: unable to open database file
  File "store.py", line 205, in write_index
    conn.executescript(SCHEMA)
```

So the name budget was consumed by the temp name *and* SQLite's sidecar, not by
the index file itself. The existing `ai-agents` book (213-char id, 226-byte
temp) sat just under the limit, which is why only long Anna's Archive names
failed.

### Fix

Two layers, both real:

1. `ingest.book_id_for(name)` — one slugger for the two places that derive an
   id from a file name (HTTP import, `ingest.py` CLI). It slugs, then caps at
   `BOOK_ID_MAX = 64`, keeping the readable head and appending 8 hex digits of
   the sha1 of the whole slug so two long titles that share a prefix stay
   distinct. The failing name now derives 62 characters:
   `mushoku-tensei_-jobless-reincarnation-light-novel-vol-4dce1b20`.
2. `store.write_index` no longer puts the target's name into the temp file
   (`prefix=".index-"`). The atomic write is now independent of the target
   name's length, so a legal 240-byte index name writes instead of failing on
   SQLite's journal name. Verified: the 226-char id saved a 2,887,680-byte
   index after the change.

### Coverage

- `tests/test_store.py::test_a_name_near_the_filesystem_limit_still_writes`
  (240-byte target name).
- `tests/test_ingest.py::BookIdTests` (bound, distinctness, short/empty names).

## 2. The importing book: jacket, dimmed, with a real dial

Before: a full-width status bar above the shelf with an indeterminate spinner
and elapsed time. Nothing showed the cover and the wait gave no sense of
distance.

Now the import occupies the next shelf cell as a book: `web/components/
IngestCard.tsx` renders the engine's extracted jacket at `--ingest-dim` (0.42)
with a 48px dial underneath. `POST /ask` `mode:"import"` gained `stream: 1`
(NDJSON), so the numbers are the engine's own:

| Frame | When | Client use |
|---|---|---|
| `book {book_id, title, author, cover_url, chunk_count}` | after `ingest_epub` wrote the jacket | the real cover and the OPF title replace the file name |
| `progress {done, total}` | after each embedding batch of 16 | dial `stroke-dashoffset` = `total-done` fraction, percent inside, `N of M passages · M:SS` under it |
| `final {ok, book_id, book, books}` | after `save_index` + catalogue | add to the shelf, check mark, open the book |
| `error {error}` | any failure after the header | the message in place of the stage line, plus Dismiss |

Until the first `progress` frame the dial spins rather than inventing a
percentage; `prefers-reduced-motion: reduce` removes the spin, the arc
transition and the entry animation.

### Measured

One live import of the 16 MB light novel (274 chunks, 12 chapters, cover
1,216,556-byte JPEG), timed from the NDJSON read:

```
0.2s  book    {'book_id': 'mushoku-tensei_...-4dce1b20', 'title': 'Mushoku Tensei: Jobless Reincarnation Vol. 25'}
3.7s  progress 80/274
7.5s  progress 176/274
11.4s progress 272/274
11.8s final   {'ok': True}
```

21 frames total, 19 of them progress. The shelf card read
`16 of 274 passages · 0:00` at 6% (1.2 s), `80 of 274 passages · 0:02` at 29%,
and the title under the dial was the engine's, not the slug.

Visual check, Chromium driven through the omp browser tab at 1440×900 and
390×844: jacket dimmed, dial filling, counts and elapsed legible at both
widths in the two-column mobile shelf; a 16-byte `broken.epub` reached
`import failed: File is not a zip file` with a working Dismiss.

### Coverage

`tests/test_stream_contract.py::ImportStreamContractTest` pins book → progress
→ final, an `error`-only stream on a rejected import, the `import failed: …`
frame for an unexpected exception, and the unchanged single-JSON body without
`stream`.

## Operational notes

- `data/figures/` was empty on this machine when this work started (the
  catalog's `figures_dir` values had no files, so every cover and figure
  404'd). Re-extracting with `ingest.ingest_epub(..., write_images=True)` per
  catalog book — no index write — restored 58 MB: 111 / 76 / 90 / 161 / 69
  figures plus covers. `test_server_multibook::test_figures_cover_mime_types`
  passes again.
- This EPUB's chapter labels are mixed: 8 documents resolve to `1`…`12` from
  their headings, the rest fall back to the doc id, so a citation can read
  `Ch. section-0015`. Its illustrations carry no captions, so the extractor
  records `figure_count: 0` for the book. Both are ingest behaviour that
  predates this change; neither was touched.
- Three `tests/test_canonical.py` tests fail on this tree (`What is CDC?` now
  becomes `What is change data capture?`): `answer.py` gained an
  `acronyms.expand` stage in another session's in-flight work. Unrelated to
  this change; the tests and the stage need to be reconciled by whoever owns
  that work.
