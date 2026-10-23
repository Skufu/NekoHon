"""Caption-seeded passage recall. Post-v1 retrieval step.

A figure caption is a short, dense name for an artifact. Dense chunk search
buries the long chunk that names the figure, and the lexical channel can pick
the wrong neighbor on a tie. When a figure caption matches the question better
than the best chunk, the best-scoring chunk that names that figure leads the
passage set. Phase 5 then attaches the figure by its own naming rule.

This runs after fusion (answer.ask): the comparison base is the best chunk
score in the set, not the first passage's, because fusion reorders and
position no longer tracks the score. A naming chunk that is already in the
set is left alone — that guard is load-bearing: measured 2026-10-12, moving
a present naming chunk to the front broke the transformations golden, because
a caption outscored the set and fronted a chunk that was already there.

Measured 2026-10-12 ("MAD data landscape"):
- best chunk ch03-102 "Data Mesh" scores 0.671,
- figure-4-1 caption "Matt Turck's 2021 MAD data landscape" scores 0.751,
- ch04-020 names Figure 4-1 and holds the (MAD) landscape sentence; with it
  leading, the ask quotes it and attaches the figure.

Stdlib only. The embedder is injected so tests never call Ollama.
"""

import math

from engine.figures import cited_numbers, number_from_id
from engine.retrieval.retrieve import DEFAULT_EMBEDDER, _dot, cosine, embed_texts, ollama_embed


def caption_seed(index, question, passages, model=DEFAULT_EMBEDDER, embed_fn=None):
    """Passages with the figure-naming chunk prepended, or unchanged.

    Fires only when a figure caption scores above the best chunk score. A
    naming chunk already in the passages is left where it is, never
    duplicated or reordered.
    """
    figures = index.get("figures") or []
    chunks = index.get("chunks") or []
    if not figures or not chunks or not passages:
        return passages
    # Fusion reorders, so the base is the best chunk score in the set, not the
    # first passage's.
    top_score = max((hit.get("score") or 0.0) for hit in passages)
    embed_fn = embed_fn or ollama_embed
    query = embed_texts([question], model, embed_fn, "query")[0]
    if (
        not isinstance(query, list)
        or not query
        or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in query)
        or all(value == 0.0 for value in query)
    ):
        raise SystemExit(
            "query embedding is empty, non-finite, or all-zero; refusing to rank."
        )
    q_norm = math.sqrt(_dot(query, query))
    q_unit = [x / q_norm for x in query] if q_norm > 0.0 else query
    best_figure = None
    best_score = 0.0
    for figure in figures:
        f_uvec = figure.get("_uvec")
        if f_uvec is not None:
            score = _dot(q_unit, f_uvec)
        else:
            vector = figure.get("embedding")
            if not vector:
                continue
            score = cosine(query, vector)
        if best_figure is None or score > best_score:
            best_figure, best_score = figure, score
    if best_figure is None or best_score <= top_score:
        return passages
    number = number_from_id(best_figure.get("id"))
    if not number:
        return passages
    naming = [
        chunk
        for chunk in chunks
        if number in (chunk.get("_cited_numbers") if chunk.get("_cited_numbers") is not None else cited_numbers(chunk.get("text")))
    ]
    if not naming:
        return passages

    def relevance(chunk):
        c_uvec = chunk.get("_uvec")
        if c_uvec is not None:
            return _dot(q_unit, c_uvec)
        vector = chunk.get("embedding")
        return cosine(query, vector) if vector else 0.0

    best = max(naming, key=relevance)
    present = {hit.get("chunk_id") for hit in passages}
    if best.get("chunk_id") in present:
        return passages
    seed = {
        "score": best_score,
        "chunk_id": best["chunk_id"],
        "chapter": best["chapter"],
        "heading": best.get("heading", ""),
        "text": best.get("text", ""),
        "source": best.get("source", ""),
    }
    return [seed] + passages[:-1]
