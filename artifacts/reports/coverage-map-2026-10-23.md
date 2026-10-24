# Coverage map — per-chapter chunk counts, 2026-10-23

Measured with `artifacts/probes/coverage-map-2026-10-23.py` (new, stdlib only,
read-only). Every number below is copied from the script's printed output.

## How a book's index is located

`data/books.json` lists each book with an `index_path`. `server.get_book_index`
resolves a book as follows (`server.py:169`): the default book `fde` is served
by `retrieve.INDEX` (`data/index.json`); any other `book_id` uses
`data/index.<book_id>.json` when that file exists, and only falls back to the
catalog's `index_path` otherwise. The script mirrors that rule and reads the
JSON index directly with `json`, so no server, model, or network call is made.

Command run:

```
python artifacts/probes/coverage-map-2026-10-23.py
```

## fde — Fundamentals of Data Engineering

Index: `data/index.json`

| chapter | chunks |
| --- | ---: |
| 1 | 76 |
| 2 | 93 |
| 3 | 108 |
| 4 | 98 |
| 5 | 86 |
| 6 | 131 |
| 7 | 99 |
| 8 | 166 |
| 9 | 74 |
| 10 | 29 |
| 11 | 30 |
| app01 | 20 |
| app02 | 12 |
| part01 | 1 |
| part02 | 1 |
| part03 | 1 |
| preface01 | 17 |
| **TOTAL** | **1042** |

Totals: chapters 17, chunks 1042, figures 111; catalog says chapters 17 /
chunks 1042. Chapters with fewer than 3 chunks: 3 (part01, part02, part03 —
1 each).

## quantization — Quantization and Fast Inference

Index: `data/index.quantization.json`

| chapter | chunks |
| --- | ---: |
| 1 | 27 |
| 2 | 84 |
| 3 | 89 |
| 4 | 62 |
| 5 | 70 |
| 6 | 61 |
| 7 | 80 |
| **TOTAL** | **473** |

Totals: chapters 7, chunks 473, figures 76; catalog says chapters 7 /
chunks 473. Chapters with fewer than 3 chunks: 0.

## ddia — Designing Data-Intensive Applications

Index: `data/index.ddia.json`

| chapter | chunks |
| --- | ---: |
| 1 | 52 |
| 2 | 88 |
| 3 | 87 |
| 4 | 75 |
| 5 | 107 |
| 6 | 46 |
| 7 | 121 |
| 8 | 113 |
| 9 | 160 |
| 10 | 124 |
| 11 | 120 |
| 12 | 173 |
| glossary | 12 |
| preface | 17 |
| text00005 | 1 |
| text00010 | 7 |
| text00016 | 4 |
| **TOTAL** | **1307** |

Totals: chapters 17, chunks 1307, figures 90; catalog says chapters 17 /
chunks 1307. Chapters with fewer than 3 chunks: 1 (text00005 — 1 chunk).

## Catalog totals

| books | chapters | chunks | chapters with < 3 chunks |
| ---: | ---: | ---: | ---: |
| 3 | 41 | 2822 | 4 |

**4 of the catalog's 41 chapters have fewer than 3 chunks** (fde part01,
part02 and part03 with 1 chunk each; ddia text00005 with 1 chunk).

Chapter labels are the index's own `chapter` values. Numeric labels are
chapters; `app01`/`app02`/`preface01`/`preface`/`glossary` and
`part01`–`part03`/`text00005`/`text00010`/`text00016` are front/back matter,
part dividers, or unlabeled sections that the ingestion gave non-numeric
labels. Measured chunk and chapter counts match the catalog's declared
`chunk_count` and `chapter_count` for all three books.
