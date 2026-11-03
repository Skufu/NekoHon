# Gemma embedder experiments — protocol

**Every gemma experiment runs in this worktree** (`ask-this-book-gemma`, branch
`test-gemma-embedder`). `ask-this-book` on `main` is read-only for this work:
its 45 uncommitted paths are the generation/teach work, and it does not carry the
gemma indexes. If a tool call takes a relative path, prefix
`../ask-this-book-gemma/` or pass `cwd`.

One question: can `embeddinggemma-2:270m-bf16-text` be made to beat, or at least
match, `nomic-embed-text` on exact-chunk retrieval without giving up its window
recall advantage?

## Known baseline (do not re-derive, but reproduce once if cheap)

42-row authored set, 35 answerable, six technical books, dense only (k=5):

| embedder | top-1 | top-5 | window (full pipeline) |
|---|---|---|---|
| nomic (main worktree) | 26/35 | 31/35 | 81.8 % over 170 questions |
| gemma (this worktree) | 19/35 | 30/35 | 86.5 % over 170 questions |

Ruled out already, with numbers: query instruction (4 conventions: 19/35, 21, 20,
19), vector dimension (the served model returns 768-d, not the 512 the manifest
advertises), anisotropy (random chunk pairs 0.62 for gemma vs 0.67 for nomic).
Six of the nine top-1 losses are the adjacent chunk or a second correct passage;
one is a real miss ("who proposed the Kappa architecture").

## Rules for every experiment

1. Never write to `data/` or to engine source in this worktree. Copy an index to
   `/tmp` if you need to mutate vectors, or hold them in memory. The one engine
   change allowed is the one named in your task, and only if the lead asks.
2. Scripts live in `/tmp/<your-name>/`. Results go to
   `artifacts/experiments/gemma/<your-name>.json` and a short
   `<your-name>.md` beside it, both in the gemma worktree.
3. Measure on the same 35 answerable rows:
   `artifacts/datasets/retrieval/retrieval-recall-2026-11-02.jsonl`, rows where
   `expected_refusal` is false and `gold_chunk_ids` is non-empty.
   Report **top-1 (gold at rank 1)**, **top-5 (any gold in top 5)**, and **mean
   gold rank**. One row per configuration, plus the per-row gold ranks in the
   JSON so the lead can diff configurations.
4. Embeddings come from the same Ollama at 127.0.0.1:11434. Call
   `retrieve.ollama_embed([...], model)` with the text already formatted — do not
   go through `format_input`, so the formatting is yours to vary.
5. Report wall-clock time, and note whether Ollama was under load from the other
   experiments. Never inflate a number; a null result is a real result.
6. Message the lead (`agent://Lead` is not wired — use `agent://all`) with your
   table when done. If your hypothesis dies, say so in one line and stop.
