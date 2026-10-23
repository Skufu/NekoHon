"""Rank fusion of the dense and lexical channels. Post-v1 retrieval step.

Replaces the boost's swap-last-slot with reciprocal rank fusion. Both
channels rank; the ranks fuse as 1/(RRF_K + dense rank) + 1/(RRF_K + lexical
rank). A lexical candidate must sit inside the dense top RANK_BAND of the
corpus or it never enters the candidate list: the band is the tail veto, and
it is the deciding gate, not the word counts (measured 2026-10-12: with the
df gate forced open, the France candidate is rejected at band 0.10 and
injected at 1.00; "capital" df=10 of 1042).

Candidates are the current passages plus the single strongest admissible
lexical candidate. The model receives the fused top of that pool, same size
as before. A candidate already in the set moves nothing: the boost bailed
the same way, and the battery has cases that fell over when a present
passage was moved.

Measured 2026-10-12 on the live 1042-chunk index (re-measured after the
sentence-chunk rebuild; the boost-era numbers 51 of 1065 and 35 of 1065 no
longer describe this corpus):
- "what does data engineers need to be pragmatic about" — the flexibility
  chunk sits at dense rank 76 (7.3%); with lexical rank 1 it fuses above
  every pure-dense passage, so it now leads the set instead of riding last.
- "MAD data landscape" — captions.py seeds the figure-naming chunk before
  fusion; fusion must leave it near the front (its dense rank beats the
  data-mesh chunk's, and both carry the same anchor).
- "What is the capital of France?" — the best "capital" chunk sits at rank
  649 (62.3%), outside the band, so fusion cannot reach it. The refusal is
  the answer layer's, and the tail veto is what keeps it that way. The band
  first stood at 0.10, which silently dropped the MAD case (13.1% then) and
  with it the MAD sentence; 0.20 admits every measured legitimate anchor and
  refuses France by more than 3x.

RRF_K and the single-candidate rule are not tuned: 60 is the constant from
the RRF paper, and the lexical channel contributes one candidate the way the
boost did. A head of five was tried first and narrowed the same day: the
lexical tail is dense with mid-frequency word sums (measured df: about 178,
need 209, engineers 333), five candidates flooded out dense leaders, and the
MAD quote flipped back to the data-mesh passage. One candidate reproduces
the boost's set; RRF only decides where it lands.

The trigger stays where the boost had it: the caller runs fusion only when
the question carries a rare word (keywords.rare). Widening the trigger is a
separate, measured step.

Stdlib only. The embedder is injected so tests never call Ollama.
"""

import math

from engine.retrieval.preprocess import words
from engine.retrieval.retrieve import DEFAULT_EMBEDDER, dense_rank

RRF_K = 60
# A lexical candidate must sit in the dense top RANK_BAND of the corpus.
# Dimensionless on purpose: an absolute count would mean a different thing on
# a bigger book.
RANK_BAND = 0.20


def lexical_scores(question, word_map, chunks, ranks, band):
    """chunk position -> idf-weighted overlap, admissible chunks only.

    The math the boost scored with: a word that lives in more than half the
    corpus weighs nothing, only positive weights contribute, and a chunk
    outside the dense band is not admissible whatever it scores.
    """
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
    """Passages reordered by reciprocal rank fusion, or unchanged.

    The pool is the current passages plus the single strongest admissible
    lexical candidate: the boost's one shot, placed by rank math instead of
    the last slot. A candidate already in the set moves nothing. A candidate
    with no dense rank has no evidence and is dropped (fails closed). Ties
    break on dense rank, then lexical rank: the sort is deterministic.
    """
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
