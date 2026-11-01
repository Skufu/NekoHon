# web/ — the NekoHon reader

Next.js 16 static export. One page state object, one engine. Nothing here
talks to the internet: no webfonts, no CDN, no telemetry. Verified against the
code on 2026-11-01.

```sh
npm install
npm run dev     # http://localhost:3100, engine expected on :8000
npm run build   # writes web/out/, which the Python engine serves at /
```

Node ≥ 22.5 (`engines` in `package.json`). Dependencies are deliberately small:
`next`, `react`, `react-dom`, `zustand`, plus Tailwind v4 and
`@aiforui/lapse` (dev-only panel).

## Pages

| Path | File | What it is |
|---|---|---|
| `/` | `app/page.tsx` → `components/Reader.tsx` | the whole app: shelf and reader |
| `/traces` | `app/traces/page.tsx` | dev-only inspector for `artifacts/runs/traces.jsonl` |
| `/api/traces` | `app/api/traces/route.ts` | build-time snapshot of the trace log + catalog, read from `node:sqlite` |

`/api/traces` is `dynamic = "force-static"`: the JSON is baked at build time, so
new traces need a rebuild.

## Engine contract

`lib/engine.ts` resolves the base URL: `NEXT_PUBLIC_ENGINE_URL` if set, else
`http://127.0.0.1:8000` when the page is on `:3100`, else same-origin.

| Call | Where | Shape |
|---|---|---|
| `GET /health` | `checkHealth` ← `store.refreshHealth` | `{ok, book_id, ollama, books, warm}` |
| `GET /chunks?book_id=` | `fetchChunks` ← `Reader` | `{book_id, title, author, chunks[], figures[], books[]}` |
| `GET /retrieve?q=&book_id=&k=` | `fetchPassages` ← `AnswerView` "show passages" | `{query, book_id, passages[]}` |
| `POST /ask` | `askStream` | `mode, book_id, question, selection, chunk_id, end_chunk_id, heading, history`; `stream: 1` replies NDJSON `token` / `reset` / `final` / `error` |
| `POST /ask` `mode:"import"` | `importEpubBook` ← `LibraryView` | `{filename, data_base64, stream: 1}`, 10-minute timeout; NDJSON `book` / `progress {done,total}` / `final` / `error` |
| `GET /figures/{id}` | `<img src>` from the payload | not fetched, just rendered |

## State

One zustand store, `lib/store.ts` (`useAsk`). It holds:

- navigation and catalog: `viewMode`, `activeBookId`, `booksCatalog`,
  `bookProgress`
- the gloss cards: `glosses`, `glossAnchors`, `activeGlossId`, per-turn
  `status` / `streamText` / `body` / `elapsed`
- highlights, theme (`night` / `paper` / `sepia` / `snow` / `ink`), pen colour,
  reading size
- engine readiness (`refreshHealth`, 500 ms → 2 s backoff, 60 s cap; a failed
  health check never disables input)
- actions: `askSelection`, `submitWholeBook`, `askFollowUp`, `startQuiz`,
  `openBook`, `stopGloss`

Streams are managed outside React state in an `inFlightMap`
(`{controller, ticker, pacerTimer, startedAt}`); starting a turn aborts every
other in-flight turn. Progress saves are debounced 1 s and flushed on
`pagehide` / `beforeunload` / `visibilitychange`.

localStorage keys: `atb-settings`, `atb-highlights`, `nekohon-state-<bookId>`,
`nekohon-progress`, `nekohon-catalog`.

## Components

| File | Role |
|---|---|
| `Reader.tsx` | shell: library/reader panes, chunk fetch, focus line at 42 % viewport, mounts the rest |
| `TopBar.tsx` | volume switcher, contents, focus toggle, notes cycler, `Aa` appearance |
| `LibraryView.tsx` | wooden-shelf catalog, `/`-to-search, EPUB drag-and-drop |
| `IngestCard.tsx` | the importing book: the engine's jacket at `--ingest-dim`, a dial under it filled from `progress {done,total}`, spinning until the first batch, then the real counts and elapsed; `done` shows a check, `error` the message and a Dismiss |
| `Lens.tsx` | selection pill and highlighter swatches |
| `Margin.tsx` | wide margin cards vs narrow bottom sheet |
| `MarginCard.tsx` | one gloss card: drag, resize, multi-turn accordion, streaming text, follow-ups |
| `AnswerView.tsx` | answer body: gloss, quote, citation chips, figures, refusal copy |
| `Composer.tsx` | sticky whole-book ask bar (`/` or ⌘K), quiz action |
| `LapsePanel.tsx` | renders nothing; dev-only motion inspector |

## Design rules

Colour literals live only in `app/tokens.css` (five `[data-theme]` blocks, four
`[data-pen]` inks, marker inks, type and layout tokens). `app/globals.css`
imports tokens and Tailwind; `app/nightfall.css` is the override layer and may
only restate what it changes.

`tests/test_frontend_rules.py` enforces, across `app/`, `components/` and
`lib/`:

- no hex or `rgb()/rgba(` outside `tokens.css`
- every `box-shadow` contains `var(`
- no `monospace` / `font-mono`
- no emoji or pictographs
- a literal `className="…"` token has a matching stylesheet selector
  (template-literal class names are not checked)
- the dependency allowlist above

`tests/test_frontend_health_and_progress_rules.py` pins the health backoff,
the progress flush and `ChunkBlock` subscription scope.
`tests/test_server_packaging.py` pins that the engine serves `web/out`, rejects
path traversal, caches `/_next/static` immutably, and never shadows engine
routes.

## Known gaps

- `store.refreshHealth` checks `health.ready === false`, but `GET /health`
  never sends a `ready` key, so that branch is dead.
- Through the engine, `/traces` and `/traces/` 404 (`web/out/traces` is a
  directory); only `/traces.html` is reachable. `/api/traces` is served as
  `application/octet-stream` because the export has no file extension; the page
  still parses it.
