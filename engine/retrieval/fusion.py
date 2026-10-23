import math

from engine.retrieval.preprocess import words
from engine.retrieval.retrieve import DEFAULT_EMBEDDER, dense_rank

RRF_K = 60
RANK_BAND = 0.20


def lexical_scores(question, word_map, chunks, ranks, band):
    total = len(chunks)
    scores = {}
    for word in set(words(question)):
        positions = word_map.get(word)
        if not positions or len(positions) > total / 2:
            continue
        weight = math.log((total - len(positions) + 0.5) / (len(positions) + 0.5))
        if weight <= 0:
            continue
        for position in positions:
            rank = ranks.get(chunks[position].get("chunk_id"))
            if not rank or rank > band:
                continue
            scores[position] = scores.get(position, 0.0) + weight
    return scores


def _as_passage(chunk):
    return {
        "score": None,
        "chunk_id": chunk["chunk_id"],
        "chapter": chunk["chapter"],
        "heading": chunk.get("heading", ""),
        "text": chunk.get("text", ""),
        "source": chunk.get("source", ""),
    }


def fuse(index, question, passages, word_map=None, ranks=None,
         model=DEFAULT_EMBEDDER, embed_fn=None):
    chunks = index.get("chunks") or []
    if not chunks or not passages:
        return passages
    if word_map is None:
        from engine.retrieval.keywords import postings

        word_map = postings(index)
    if ranks is None:
        ranks = dense_rank(index, question, model, embed_fn)
    total = len(chunks)
    band = max(1, round(RANK_BAND * total))
    scores = lexical_scores(question, word_map, chunks, ranks, band)
    if not scores:
        return passages
    best_pos = min(scores, key=lambda position: (-scores[position], position))
    candidate = _as_passage(chunks[best_pos])
    by_id = {hit["chunk_id"]: hit for hit in passages}
    if candidate["chunk_id"] in by_id:
        return passages
    by_id[candidate["chunk_id"]] = candidate
    lex_rank = {candidate["chunk_id"]: 1}
    fused = []
    for chunk_id, hit in by_id.items():
        dense = ranks.get(chunk_id)
        if not dense:
            continue
        score = 1.0 / (RRF_K + dense)
        lexical = lex_rank.get(chunk_id)
        if lexical:
            score += 1.0 / (RRF_K + lexical)
        fused.append((score, dense, lexical or 0, hit))
    fused.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [hit for _, _, _, hit in fused[:len(passages)]]
