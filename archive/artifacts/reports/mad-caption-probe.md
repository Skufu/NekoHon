# MAD data landscape — caption-seeded recall (2026-10-12)

Query: `MAD data landscape`. Index `data/index.json` (nomic-embed-text, 1065
chunks, 111 figures). Answer model qwen2.5:7b, temperature 0.

## Measured before / after

| stage | top passage | answer quote | figures |
|---|---|---|---|
| dense chunk search | `ch03-102` Data Mesh (0.671) | — | — |
| + rare-word boost (before) | `ch04-019` injected **last** | data-mesh sentence | 3 (incl. wrong) |
| + caption seed (after) | `ch04-020` **first** (0.751) | MAD landscape sentence | 2 |

The correct chunk `ch04-020` ("…the ML, AI, and data (MAD) landscape … (Figure
4-1)") sits at dense rank **35** (0.596) — outside any sane top-k. Query
expansion ("MAD" → "ML AI and data") only lifted it to rank 16.

The signal that already exists: the figure caption. `figure-4-1` =
"Matt Turck's 2021 MAD data landscape" scores **0.751**, above every chunk.
`captions.py` seeds the passage set with the best-scoring chunk that names that
figure. Phase 5 then attaches `figure-4-1` by its own naming rule.

## Commands

- Passages before/after (no model):
  `python -c "from retrieve import load_index,INDEX,search; from keywords import boost; from captions import caption_seed; ..."`
- End-to-end: `answer.ask(data/index.json, "MAD data landscape")`
- Regression (in-process): golden 10/10, France exact refusal, MAD probe
  `ch04-020`.
- Unit tests: `python -m unittest discover -s tests` → 48 green.
- HTTP battery with the new probe: `python artifacts/step2-battery.py`
  (restart `server.py` first — the running PID must load `captions.py`).

## Known noise (not fixed)

`figure-3-18` (data-mesh architecture) still attaches because the data-mesh
chunk stays in the top-5 and names it. This predates the caption seed. Tightening
it means attaching figures only from *cited* passages, a Phase 5 semantics change.
