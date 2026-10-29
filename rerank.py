"""Neural Cross-Encoder reranking for retrieved book passages.

Uses local cached HuggingFace cross-encoders (e.g. cross-encoder/ms-marco-MiniLM-L-6-v2)
running in-process via PyTorch/CUDA or CPU with local_files_only=True.
"""

import os
from typing import Any, Dict, List, Optional

DEFAULT_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_CROSS_ENCODERS = {}


def get_cross_encoder(model_name: str = DEFAULT_RERANK_MODEL, device: Optional[str] = None):
    """Load or retrieve cached CrossEncoder model instance."""
    import torch
    from sentence_transformers import CrossEncoder

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    key = (model_name, device)
    if key in _CROSS_ENCODERS:
        return _CROSS_ENCODERS[key]

    try:
        model = CrossEncoder(model_name, device=device, local_files_only=True)
    except Exception:
        # Fallback to CPU if CUDA fails
        device = "cpu"
        key = (model_name, device)
        if key in _CROSS_ENCODERS:
            return _CROSS_ENCODERS[key]
        model = CrossEncoder(model_name, device=device, local_files_only=True)

    _CROSS_ENCODERS[key] = model
    return model


def rerank_passages(
    question: str,
    passages: List[Dict[str, Any]],
    top_k: int = 5,
    model_name: str = DEFAULT_RERANK_MODEL,
    keep_top1: bool = False,
    device: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Rerank passages using neural cross-encoder.

    If keep_top1 is True, the passage at rank 0 remains at rank 0, and the
    remaining passages are re-ordered by cross-encoder score.
    """
    if not passages or not question:
        return passages[:top_k]

    try:
        model = get_cross_encoder(model_name=model_name, device=device)
        pairs = [
            (question, f"{p.get('heading', '')}\n{p.get('text', '')}".strip())
            for p in passages
        ]
        scores = model.predict(pairs)
    except Exception:
        # Graceful fallback if model loading or inference fails
        return passages[:top_k]

    scored = []
    for p, s in zip(passages, scores):
        item = dict(p)
        item["rerank_score"] = float(s)
        scored.append(item)

    if keep_top1 and scored:
        top1 = scored[0]
        rest = scored[1:]
        rest.sort(key=lambda x: x.get("rerank_score", -1e9), reverse=True)
        result = [top1] + rest
    else:
        scored.sort(key=lambda x: x.get("rerank_score", -1e9), reverse=True)
        result = scored

    return result[:top_k]


def rerank_rrf(
    question: str,
    passages: List[Dict[str, Any]],
    top_k: int = 5,
    model_name: str = DEFAULT_RERANK_MODEL,
    rrf_k: int = 60,
    device: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Blend initial retrieval order and cross-encoder ranking via RRF."""
    if not passages or not question:
        return passages[:top_k]

    reranked = rerank_passages(
        question, passages, top_k=len(passages), model_name=model_name, device=device
    )
    ce_ranks = {
        p.get("chunk_id"): rank
        for rank, p in enumerate(reranked, start=1)
        if p.get("chunk_id")
    }

    fused = []
    for dense_rank, p in enumerate(passages, start=1):
        cid = p.get("chunk_id")
        ce_rank = ce_ranks.get(cid, len(passages))
        score = 1.0 / (rrf_k + dense_rank) + 1.0 / (rrf_k + ce_rank)
        item = dict(p)
        item["rrf_score"] = score
        fused.append((score, -dense_rank, item))

    fused.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [item for _, _, item in fused[:top_k]]
