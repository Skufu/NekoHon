"""Caption-seeded passage recall. Post-v1 retrieval step.

A figure caption is a short, dense name for an artifact. Dense chunk search
buries the long chunk that names the figure, and the rare-word boost can pick
the wrong neighbor on a tie. When a figure caption matches the question better
than the best chunk, seed the passage set with the best-scoring chunk that
names that figure. Phase 5 then attaches the figure by its own naming rule.

Measured 2026-10-12 ("MAD data landscape"):
- best chunk ch03-102 "Data Mesh" scores 0.671,
- figure-4-1 caption "Matt Turck's 2021 MAD data landscape" scores 0.751,
- ch04-020 names Figure 4-1 and holds the (MAD) landscape sentence.
The rare-word boost picked ch04-019 on a position tie and placed it last, so
the model still quoted the data-mesh passage.

Stdlib only. The embedder is injected so tests never call Ollama.
"""

import re

from figures import cited_numbers
from retrieve import DEFAULT_EMBEDDER, cosine, embed_texts, ollama_embed

NUMBER_RE = re.compile(r"(\d+-\d+)")


def _figure_number(figure_id):
    match = NUMBER_RE.search(figure_id or "")
    return match.group(1) if match else ""


def caption_seed(index, question, passages, model=DEFAULT_EMBEDDER, embed_fn=None):
    """Passages with the figure-naming chunk prepended, or unchanged.

    Fires only when a figure caption scores above the best dense chunk. The
    seeded passage keeps that caption score so it sorts as the strongest.
    A chunk already in the passages is never duplicated.
    """
    figures = index.get("figures") or []
    chunks = index.get("chunks") or []
    if not figures or not chunks or not passages:
        return passages
    top_score = passages[0].get("score") or 0.0
    embed_fn = embed_fn or ollama_embed
    query = embed_texts([question], model, embed_fn, "query")[0]
    best_figure = None
    best_score = 0.0
    for figure in figures:
        vector = figure.get("embedding")
        if not vector:
            continue
        score = cosine(query, vector)
        if best_figure is None or score > best_score:
            best_figure, best_score = figure, score
    if best_figure is None or best_score <= top_score:
        return passages
    number = _figure_number(best_figure.get("id"))
    if not number:
        return passages
    naming = [
        chunk
        for chunk in chunks
        if number in cited_numbers(chunk.get("text"))
    ]
    if not naming:
        return passages
    present = {hit.get("chunk_id") for hit in passages}
    if any(chunk.get("chunk_id") in present for chunk in naming):
        return passages

    def relevance(chunk):
        vector = chunk.get("embedding")
        return cosine(query, vector) if vector else 0.0

    best = max(naming, key=relevance)
    seed = {
        "score": best_score,
        "chunk_id": best["chunk_id"],
        "chapter": best["chapter"],
        "heading": best.get("heading", ""),
        "text": best.get("text", ""),
        "source": best.get("source", ""),
    }
    return [seed] + passages[:-1]
