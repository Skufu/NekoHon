# Phase 2 Brief — Ingest (`ask-this-book`)

Status 2026-10-11. Phases 0 / 0b / 1 done: book at `books/fde.epub`, fixture + server + contract test green.
Phase 2 builds `ingest.py`: EPUB -> `data/index.json` + `data/figures/`. Plain JSON, no vectors, no AI, offline.

## Rules (locked, from README)
- Split text on headings first. Target ~300 tokens. ~40-token overlap only for over-long sections.
- Keep the heading text at the start of each chunk. Never split a table.
- Figure record: `{id, chapter, caption, referencing_paragraph, file}`. Caption = book's caption, else alt, else "". Never invented.
- Referencing paragraph = nearest paragraph mentioning the figure ("Figure X-Y", "Fig.", "Figure"); else "".
- One record per spine document. Reloadable with stdlib `json`. No pickle, marshal, shelve, or sqlite. Pictures stay files, not base64 in the index. stdlib only.

## Done when
- `python -m unittest tests.test_ingest -v` passes (tiny fake EPUB built inside the test: one heading, one table, one image; table stays one chunk; caption + citing paragraph captured).
- Real run on `books/fde.epub` prints chunk count (> 0), figure count, 3 captions. Printout read and checked against the book; that is the evidence.
- A heading from the real book appears in a chunk.

## Measured facts about this EPUB (read-only probe, 2026-10-11)
- Spine, 24 docs in reading order: cover, dedication, titlepage, copyright, preface, part01, ch01-ch04, part02, ch05-ch09, part03, ch10-ch11, app01, app02, ix01, colophon01, colophon02. (`toc01.html` exists; not in spine.)
- Chapters ch01-ch11. 114 PNGs; ~110 referenced by chapters (ch10 has none, ch11 has one).
- Captions are NOT `<figcaption>` (0 in the whole book). They are `h6` inside `<figure><div class="figure">`, e.g.
  `<h6><span class="label">Figure 2-1. </span>Components and undercurrents of the data engineering lifecycle</h6>`.
  `<img alt="">` is empty. Caption must come from the h6.
- Tables: 24 real `<table>` with `<caption>`; 21 in ch08, 2 in ch05, 1 in ch06.
- Heading depth h1-h4 (ch08: 8 h1 / 21 h2 / 36 h3 / 24 h4). ch09 and ch11 have no h3+.
- Metadata matches the handoff: title "Fundamentals of Data Engineering", creator "Reis, Joe; Housley, Matt", publisher O'Reilly, 2022.

## Known bumps + plan
1. Book-specific caption spot (h6 in figure block, empty alt) -> parse it there; fallback alt -> "".
2. Front matter / index noise -> one record per spine doc, but skip docs with no real text; tag chunks with their source label.
3. No tokenizer in stdlib -> ~300 tokens approximated (~1200-1500 chars); tune after first output.

## Non-goals for Phase 2
No Ollama, no embeddings, no search, no answers, no server changes, no downloads. Wifi can be off.
Phase 3 embeds these chunks with `nomic-embed-text`; Phase 3b re-uses the SAME frozen chunks, so chunk quality is eyeballed now.

## Commands
- `python -m unittest tests.test_ingest -v`
- `python ingest.py` (real book; prints counts + 3 captions)
