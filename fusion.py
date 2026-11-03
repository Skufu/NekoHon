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
as before. A candidate already in the set is re-placed by the same fusion
(2026-10-31: the earlier bail-out was measured to strand a gold chunk at
dense rank 2 behind a distractor).

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

That five-candidate rejection was measured against the *rare-word* trigger.
The 2026-11-02 trigger also opens on book-named words (`keywords.lexical_terms`),
where the lexical candidate is often already inside the dense window, so the
count is a knob again: ``MAX_LEXICAL_CANDIDATES``. The sweep and what each
value did to chapter coverage are in the constant's comment; the default
stays 1, which reproduces the pre-2026-11-02 output byte for byte.

Raising that count was measured and rejected on 2026-11-02: every value above
one bought chapter spread by evicting the answering chunk (novel chunk recall
0.700 -> 0.600 at three). The widening that shipped is the displacement-free
shape instead: ``added=k`` keeps the dense head and appends up to k admissible
BM25 chunks after it, so recall cannot fall by construction. The counts and
the measurements behind them are on ``MAX_LEXICAL_ADDITIONS``.

The trigger is `keywords.lexical_terms`: the question carries a rare book word
(the original trigger) or names something the book names by capitalising it
(2026-11-02). Dense-only asks still do not pay for fusion.

``LEXICAL_BACKEND`` stays ``fts5`` by default and ``legacy`` is still the
explicit seam. If FTS5 is unavailable or its SQLite query fails, fusion warns,
marks ``lexical_backend=legacy`` in the request trace, and uses the legacy idf
channel for that request; the served path must never change channels silently.

Stdlib only. The embedder is injected so tests never call Ollama.
"""

import logging
import math
import os

from preprocess import words
from retrieve import DEFAULT_EMBEDDER, dense_rank

_LOGGER = logging.getLogger(__name__)

RRF_K = 60
# A lexical candidate must sit in the dense top RANK_BAND of the corpus.
# Dimensionless on purpose: an absolute count would mean a different thing on
# a bigger book.
RANK_BAND = 0.20
# How many BM25 candidates the RRF path fuses. One is the pre-2026-11-02
# behaviour and must stay byte-identical at this value. The 2026-11-02 sweep
# on the pinned 42-row retrieval-recall set rejected more: cap 2 dropped
# quantization chunk recall 1.000 -> 0.875, cap 3 dropped novel recall
# 0.700 -> 0.600 and halved process recall, buying chapter spread by evicting
# the answering chunk. The cap stays 1; MAX_LEXICAL_ADDITIONS is the shipped
# widening.
MAX_LEXICAL_CANDIDATES = 1
# Lexical additions ride after the dense head instead of displacing it, so
# chunk recall cannot fall: the dense five stay and BM25 chunks follow.
# Measured 2026-11-02 on the pinned 42-row retrieval-recall set (dense 5 + k
# additions, gate = keywords.lexical_terms):
#   novel coverage@5+k 0.575 / 0.742 / 0.775 / 0.775 at k=0/1/2/3; recall
#     flat at 0.700; entity coverage 0.458 / 0.569 / 0.625 / 0.625.
#   ddia recall 0.750 / 1.000 / 1.000 / 1.000; fde 0.875 until k=3; every
#     other technical book 1.000 at every k.
# Fiction takes two: the novel curve is flat from there. Technical takes one:
# it is the only k that buys a recall row (ddia) without paying two extra
# chunks on the books that gain nothing. Cost at k=2 is about 2,600 extra
# shown characters on a gate-open novel ask, about 950 at k=1 on a technical
# one.
MAX_LEXICAL_ADDITIONS = 1
MAX_LEXICAL_ADDITIONS_FICTION = 2
LEXICAL_BACKEND = os.environ.get("LEXICAL_BACKEND", "fts5")


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


def _note_lexical_backend(backend, warning=None):
    """Record which lexical channel served this request.

    Telemetry is optional: a tracing failure must never change retrieval.
    A fallback also logs at WARNING so a served-path backend change is visible
    outside the trace log.
    """
    if warning:
        _LOGGER.warning(
            "%s; falling back to the legacy idf lexical channel", warning
        )
    try:
        from observe import record_transform

        record_transform(f"lexical_backend={backend}")
    except Exception:
        pass


def _as_passage(chunk):
    return {
        "score": None,
        "chunk_id": chunk["chunk_id"],
        "chapter": chunk["chapter"],
        "heading": chunk.get("heading", ""),
        "section": chunk.get("section", ""),
        "anchor": chunk.get("anchor", ""),
        "text": chunk.get("text", ""),
        "source": chunk.get("source", ""),
    }


def _additions(chunks, scores, passages, count):
    """Up to count admissible lexical chunks the passages do not already hold."""
    have = {hit.get("chunk_id") for hit in passages}
    added = []
    for position in sorted(scores, key=lambda position: (-scores[position], position)):
        if len(added) >= count:
            break
        chunk = chunks[position]
        if chunk.get("chunk_id") in have:
            continue
        added.append(_as_passage(chunk))
    return added


def fuse(index, question, passages, word_map=None, ranks=None,
         model=None, embed_fn=None, added=0):
    """Passages reordered by reciprocal rank fusion, or unchanged.

    The pool is the current passages plus the single strongest admissible
    lexical candidate: the boost's one shot, placed by rank math instead of
    the last slot. A candidate already in the set is placed by the same math
    and never duplicated. A candidate
    with no dense rank has no evidence and is dropped (fails closed). Ties
    break on dense rank, then lexical rank: the sort is deterministic.

    ``added`` switches to the displacement-free shape instead: the passages
    come back first and in their own order, with up to ``added`` admissible
    BM25 chunks the window does not already hold appended. The caller raises
    its own window limit by the number it actually received, so a route that
    asks for two additions shows seven passages and every dense chunk stays.
    """
    chunks = index.get("chunks") or []
    if not chunks or not passages:
        return passages
    if word_map is None:
        from keywords import postings

        word_map = postings(index)
    if ranks is None:
        ranks = dense_rank(index, question, model, embed_fn)
    total = len(chunks)
    band = max(1, round(RANK_BAND * total))
    if LEXICAL_BACKEND == "fts5":
        try:
            from fts_index import FtsUnavailable, fts_bm25_scores

            scores = fts_bm25_scores(index, question, ranks=ranks, band=band)
        except FtsUnavailable as exc:
            _note_lexical_backend("legacy", f"FTS5 unavailable: {exc}")
            scores = lexical_scores(question, word_map, chunks, ranks, band)
        else:
            _note_lexical_backend("fts5")
    else:
        _note_lexical_backend("legacy")
        scores = lexical_scores(question, word_map, chunks, ranks, band)
    if not scores:
        return passages
    if added:
        return list(passages) + _additions(chunks, scores, passages, added)
    ordered = sorted(scores, key=lambda position: (-scores[position], position))
    by_id = {hit["chunk_id"]: hit for hit in passages}
    # A candidate already in the set still earns its lexical rank: measured
    # 2026-10-31, two gold chunks sat at dense rank 2 with lexical rank 1 and
    # the old early return left them behind a distractor (25 to 27 of 42
    # wide-net-v2 answerable items with the gold chunk shown first, no item
    # lost; the always-fuse trigger was tried and rejected, 25 to 24).
    lex_rank = {}
    for rank, position in enumerate(ordered[:MAX_LEXICAL_CANDIDATES], start=1):
        candidate = _as_passage(chunks[position])
        by_id.setdefault(candidate["chunk_id"], candidate)
        lex_rank[candidate["chunk_id"]] = rank
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
