# One SQLite database per book, vectors as float64 blobs inside it

Each ingested book is one SQLite file (`data/index.<book_id>.sqlite`) holding
the chunks, the figures, both FTS5 indexes and the embedding vectors as
little-endian float64 blobs. The alternative was a JSON index plus sidecar
vector files; it was rejected because the lexical index had to be rebuilt in
process on every start, and because a half-written JSON index is
indistinguishable from a whole one. SQLite gives atomic replacement (write a
sibling temp file, then rename), a read-only open mode, and a persisted FTS
table for free.

**Consequences.** Writes cost a full file rewrite, so ingestion and embedding
are batch operations, not incremental ones. A reader never sees a partial
index, and `store.py --check` can verify the FTS row counts against the chunk
table. Floats are rounded to six decimals to keep the file small, which means
a vector loaded from disk is not bit-identical to the one computed in memory.
