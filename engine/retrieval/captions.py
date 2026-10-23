import math

from engine.figures import cited_numbers, number_from_id
from engine.retrieval.retrieve import DEFAULT_EMBEDDER, dot_product, cosine, embed_texts, ollama_embed


def caption_seed(index, question, passages, model=DEFAULT_EMBEDDER, embed_fn=None):
    figures = index.get("figures") or []
    chunks = index.get("chunks") or []
    if not figures or not chunks or not passages:
        return passages
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
    q_norm = math.sqrt(dot_product(query, query))
    q_unit = [x / q_norm for x in query] if q_norm > 0.0 else query
    best_figure = None
    best_score = 0.0
    for figure in figures:
        f_uvec = figure.get("_uvec")
        if f_uvec is not None:
            score = dot_product(q_unit, f_uvec)
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
            return dot_product(q_unit, c_uvec)
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
