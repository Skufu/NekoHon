#!/usr/bin/env python3
"""trace_inspect.py — Runtime trace inspector & RAG eval diagnostics.

Provides both a programmatic API and CLI for inspecting live telemetry
(artifacts/runs/traces.jsonl) and stage-attributed eval runs (fair-eval JSON).
Stdlib only. Zero network calls.

See AGENTS.md ("Observability and failure diagnosis" section).
"""

import argparse
import copy
import json
import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import observe


# =============================================================================
# Programmatic API: Stage Attribution & Eval Diagnostics
# =============================================================================

def attribute_eval_item(item, result):
    """Attribute an evaluation item failure to a pipeline stage.

    Stages:
      - None (if item passed)
      - "guard_false_refusal": pre-LLM guard blocked an answerable item
      - "trap_false_answer": out-of-book refusal item answered
      - "retrieval_miss": answerable item where no gold chunk/chapter is in shown top-5
      - "false_refusal": gold in top-5 but model refused
      - "wrong_citation": model answered but cited wrong chapter or invalid citation
      - "missing_key_fact": model answered but missed a required key fact
      - "generation_other": other generation failure
    """
    item = item or {}
    result = result or {}
    passed = bool(result.get("passed"))
    refused = bool(result.get("refused"))
    expect = item.get("expect")
    trace = result.get("trace") or {}

    shown = (
        trace.get("retrieval", {}).get("shown_passages")
        or result.get("shown_passages")
        or []
    )

    gold_chunks = [str(c) for c in (item.get("gold_chunks") or [])]
    gold_chapters = [str(ch) for ch in (item.get("gold_chapters") or [])]

    gold_shown_rank = None
    gold_in_shown_top5 = False

    for idx, p in enumerate(shown[:5], start=1):
        p_chunk = str(p.get("chunk_id") if isinstance(p, dict) else p)
        p_chap = (
            str(p.get("chapter"))
            if isinstance(p, dict) and p.get("chapter") is not None
            else ""
        )
        if gold_chunks:
            if p_chunk in gold_chunks:
                gold_shown_rank = idx
                gold_in_shown_top5 = True
                break
        elif gold_chapters:
            if p_chap and p_chap in gold_chapters:
                gold_shown_rank = idx
                gold_in_shown_top5 = True
                break

    stage = None
    if not passed:
        if expect == "refuse" and not refused:
            stage = "trap_false_answer"
        elif expect == "answer":
            guard_blocked = (trace.get("query") or {}).get("guard_blocked")
            if guard_blocked:
                stage = "guard_false_refusal"
            elif (gold_chunks or gold_chapters) and not gold_in_shown_top5:
                stage = "retrieval_miss"
            elif refused:
                stage = "false_refusal"
            else:
                reasons_str = " ".join(result.get("reasons") or []).lower()
                if any(w in reasons_str for w in ("citation", "chapter")):
                    stage = "wrong_citation"
                elif any(w in reasons_str for w in ("key_fact", "misses")):
                    stage = "missing_key_fact"
                else:
                    stage = "generation_other"
        else:
            stage = "generation_other"

    return {
        "stage": stage,
        "gold_shown_rank": gold_shown_rank,
        "gold_in_shown_top5": gold_in_shown_top5,
    }


def summarize_eval_diagnostics(items, results):
    """Summarize overall, retrieval, generation, and stage diagnostics.

    Returns:
      (summary_dict, annotated_results_list)
    """
    if isinstance(items, list):
        items_dict = {
            it.get("id"): it
            for it in items
            if isinstance(it, dict) and it.get("id")
        }
    elif isinstance(items, dict):
        items_dict = items
    else:
        items_dict = {}

    if isinstance(results, dict):
        results_list = list(results.values())
    else:
        results_list = list(results or [])

    annotated_results = []
    total = len(results_list)
    passed_count = 0
    failure_stages = {}

    answerable_count = 0
    gold_in_top1_count = 0
    gold_in_top5_count = 0
    mrr_ranks = []
    passed_given_gold_shown = 0

    for res in results_list:
        res_copy = copy.deepcopy(res)
        item_id = res_copy.get("id")
        item = items_dict.get(item_id) or res_copy
        diag = attribute_eval_item(item, res_copy)
        res_copy["diagnostics"] = diag
        annotated_results.append(res_copy)

        if res_copy.get("passed"):
            passed_count += 1
        else:
            stage = diag.get("stage")
            if stage:
                failure_stages[stage] = failure_stages.get(stage, 0) + 1

        expect = item.get("expect")
        gold_chunks = item.get("gold_chunks") or []
        if expect == "answer" and bool(gold_chunks):
            answerable_count += 1
            rank = diag.get("gold_shown_rank")
            if rank == 1:
                gold_in_top1_count += 1
            if diag.get("gold_in_shown_top5"):
                gold_in_top5_count += 1
                mrr_ranks.append(rank)
                if res_copy.get("passed"):
                    passed_given_gold_shown += 1
            else:
                mrr_ranks.append(None)

    pass_rate = round(passed_count / total, 4) if total else 0.0
    recall_at_5 = (
        round(gold_in_top5_count / answerable_count, 4) if answerable_count else 0.0
    )
    reciprocals_sum = sum((1.0 / r) for r in mrr_ranks if r)
    mrr_at_5 = round(reciprocals_sum / answerable_count, 4) if answerable_count else 0.0
    pass_rate_given_gold_shown = (
        round(passed_given_gold_shown / gold_in_top5_count, 4)
        if gold_in_top5_count
        else 0.0
    )

    sorted_failure_stages = {
        k: failure_stages[k]
        for k in sorted(failure_stages)
        if failure_stages[k] > 0
    }

    summary = {
        "overall": {
            "total": total,
            "passed": passed_count,
            "failed": total - passed_count,
            "pass_rate": pass_rate,
        },
        "retrieval": {
            "answerable_with_gold": answerable_count,
            "gold_in_shown_top1": gold_in_top1_count,
            "gold_in_shown_top5": gold_in_top5_count,
            "recall_at_5": recall_at_5,
            "mrr_at_5": mrr_at_5,
        },
        "generation": {
            "passed_given_gold_shown": passed_given_gold_shown,
            "total_gold_shown": gold_in_top5_count,
            "pass_rate_given_gold_shown": pass_rate_given_gold_shown,
        },
        "failure_stages": sorted_failure_stages,
    }
    return summary, annotated_results


# =============================================================================
# Book Index Loading & Passage Reconstruction
# =============================================================================

def load_book_index(book_id="fde", index_file=None):
    """Load a book index JSON from explicit path or data/ directory."""
    if index_file:
        p = Path(index_file)
        if not p.is_absolute():
            p = ROOT / p
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass

    try:
        import server
        idx = server.get_book_index(book_id)
        if idx:
            return idx
    except Exception:
        pass

    data_dir = ROOT / "data"
    candidates = [
        data_dir / f"index.{book_id}.json",
        data_dir / "index.json",
    ]
    for c in candidates:
        if c.is_file():
            try:
                return json.loads(c.read_text(encoding="utf-8"))
            except Exception:
                pass
    return None


def reconstruct_trace(trace, book_index=None, index_file=None):
    """Reconstruct chunk text, heading, and text_preview for shown_passages and cited_chunks."""
    if not isinstance(trace, dict):
        return trace

    if book_index is None:
        b_id = trace.get("book_id") or "fde"
        book_index = load_book_index(book_id=b_id, index_file=index_file)

    if not book_index or not isinstance(book_index, dict):
        return trace

    chunk_map = {
        c.get("chunk_id"): c
        for c in (book_index.get("chunks") or [])
        if isinstance(c, dict) and c.get("chunk_id")
    }

    # Reconstruct shown passages
    retrieval = trace.get("retrieval") or {}
    shown = retrieval.get("shown_passages") or []
    for p in shown:
        if isinstance(p, dict):
            cid = p.get("chunk_id")
            chunk = chunk_map.get(cid)
            if chunk:
                p["heading"] = chunk.get("heading", "")
                full_text = chunk.get("text", "")
                p["text"] = full_text
                p["text_preview"] = full_text[:300]

    # Reconstruct cited chunks
    outcome = trace.get("outcome") or {}
    cited = outcome.get("cited_chunks") or []
    reconstructed_cited = []
    for c_entry in cited:
        cid = c_entry.get("chunk_id") if isinstance(c_entry, dict) else str(c_entry)
        chunk = chunk_map.get(cid)
        if chunk:
            full_text = chunk.get("text", "")
            reconstructed_cited.append({
                "chunk_id": cid,
                "chapter": chunk.get("chapter"),
                "heading": chunk.get("heading", ""),
                "text": full_text,
                "text_preview": full_text[:300],
            })
        else:
            reconstructed_cited.append({"chunk_id": cid})
    outcome["cited_chunks_reconstructed"] = reconstructed_cited
    return trace


# =============================================================================
# Live Traces: Loading, Filtering & Anomalies
# =============================================================================

def load_traces(log_path=None):
    """Load all JSON lines from traces log path."""
    p = observe.resolve_log_path(log_path)
    if not p.is_file():
        return []
    traces = []
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    traces.append(json.loads(line_str))
                except Exception:
                    continue
    except Exception:
        return []
    return traces


def is_trace_failure_or_anomaly(t):
    """Check if trace contains a failure, error, guard block, or performance anomaly."""
    if not isinstance(t, dict):
        return False
    if t.get("status") != "ok":
        return True
    if bool(t.get("error")):
        return True
    if bool((t.get("query") or {}).get("guard_blocked")):
        return True
    if bool(t.get("anomalies")):
        return True
    transforms = set((t.get("outcome") or {}).get("transforms") or [])
    if any(k in transforms for k in ("parse_refused", "half_covered_refused", "retry_uncited")):
        return True
    if (t.get("vram_load_ms") or 0.0) >= 100.0:
        return True
    llm = t.get("llm") or {}
    if (llm.get("vram_load_ms") or 0.0) >= 100.0:
        return True
    for call in llm.get("calls") or []:
        if isinstance(call, dict) and (call.get("vram_load_ms") or 0.0) >= 100.0:
            return True
    return False


def filter_traces(traces, book=None, trace_id=None, failures_only=False, slow_ms=None):
    """Filter list of traces by criteria."""
    filtered = []
    for t in traces:
        if not isinstance(t, dict):
            continue
        if trace_id:
            tid = str(t.get("trace_id", ""))
            if not (tid == trace_id or tid.startswith(trace_id)):
                continue
        if book:
            t_book = str(t.get("book_id", ""))
            if not (t_book.lower() == book.lower() or book.lower() in t_book.lower()):
                continue
        if failures_only and not is_trace_failure_or_anomaly(t):
            continue
        if slow_ms is not None and (t.get("total_ms") or 0.0) < float(slow_ms):
            continue
        filtered.append(t)
    return filtered


def summarize_trace_log(traces):
    """Compute summary statistics over a list of traces."""
    total = len(traces)
    if total == 0:
        return {
            "total_traces": 0,
            "status": {"ok": 0, "error": 0},
            "failures_or_anomalies": 0,
            "slow_traces": 0,
            "books": {},
            "latency": {"avg_total_ms": 0.0, "avg_retrieval_ms": 0.0, "avg_llm_ms": 0.0},
        }

    status_counts = {"ok": 0, "error": 0}
    failures = 0
    slow_count = 0
    books = {}
    tot_total_ms = 0.0
    tot_retrieval_ms = 0.0
    tot_llm_ms = 0.0
    tok_sec_values = []

    for t in traces:
        st = t.get("status", "ok")
        status_counts[st] = status_counts.get(st, 0) + 1
        if is_trace_failure_or_anomaly(t):
            failures += 1
        tot_ms = t.get("total_ms") or 0.0
        if tot_ms >= 2000.0:
            slow_count += 1
        tot_total_ms += tot_ms

        b_id = t.get("book_id") or "unspecified"
        books[b_id] = books.get(b_id, 0) + 1

        ret = t.get("retrieval") or {}
        tot_retrieval_ms += ret.get("retrieval_ms") or 0.0

        llm = t.get("llm") or {}
        tot_llm_ms += llm.get("llm_ms") or 0.0
        if llm.get("tok_per_sec"):
            tok_sec_values.append(llm["tok_per_sec"])

    return {
        "total_traces": total,
        "status": status_counts,
        "failures_or_anomalies": failures,
        "slow_traces_ge_2000ms": slow_count,
        "books": books,
        "latency": {
            "avg_total_ms": round(tot_total_ms / total, 2),
            "avg_retrieval_ms": round(tot_retrieval_ms / total, 2),
            "avg_llm_ms": round(tot_llm_ms / total, 2),
            "avg_tok_per_sec": round(sum(tok_sec_values) / len(tok_sec_values), 1) if tok_sec_values else None,
        },
    }


# =============================================================================
# Diffing Traces
# =============================================================================

def diff_traces(trace1, trace2):
    """Compare two traces and report query, retrieval rank, LLM, and outcome differences."""
    q1 = trace1.get("query") or {}
    q2 = trace2.get("query") or {}
    query_diff = {}
    for k in (
        "raw",
        "resolved",
        "asked",
        "guard_blocked",
        "history_turns",
        "pin_chunk",
        "has_selection",
        "topic_shift",
        "reading_repair",
    ):
        v1 = q1.get(k)
        v2 = q2.get(k)
        if v1 != v2:
            query_diff[k] = {"from": v1, "to": v2}

    # Retrieval rank deltas
    shown1 = trace1.get("retrieval", {}).get("shown_passages") or []
    shown2 = trace2.get("retrieval", {}).get("shown_passages") or []
    ranks1 = {
        p.get("chunk_id"): (p.get("rank") or idx)
        for idx, p in enumerate(shown1, start=1)
        if isinstance(p, dict) and p.get("chunk_id")
    }
    ranks2 = {
        p.get("chunk_id"): (p.get("rank") or idx)
        for idx, p in enumerate(shown2, start=1)
        if isinstance(p, dict) and p.get("chunk_id")
    }

    ids1 = set(ranks1.keys())
    ids2 = set(ranks2.keys())

    added_chunks = [cid for cid in ranks2 if cid not in ids1]
    removed_chunks = [cid for cid in ranks1 if cid not in ids2]
    rank_deltas = {}
    for cid in ids1.intersection(ids2):
        r1 = ranks1[cid]
        r2 = ranks2[cid]
        if r1 != r2:
            rank_deltas[cid] = {"from": r1, "to": r2, "delta": r2 - r1}

    shown_passages_diff = {
        "added": added_chunks,
        "removed": removed_chunks,
        "rank_deltas": rank_deltas,
    }

    # LLM telemetry deltas
    llm1 = trace1.get("llm") or {}
    llm2 = trace2.get("llm") or {}
    llm_diff = {
        "call_count_delta": (llm2.get("call_count") or 0) - (llm1.get("call_count") or 0),
        "llm_ms_delta": round((llm2.get("llm_ms") or 0.0) - (llm1.get("llm_ms") or 0.0), 2),
        "prompt_tokens_delta": (llm2.get("prompt_tokens") or 0) - (llm1.get("prompt_tokens") or 0),
        "completion_tokens_delta": (llm2.get("completion_tokens") or 0) - (llm1.get("completion_tokens") or 0),
        "tok_per_sec_from": llm1.get("tok_per_sec"),
        "tok_per_sec_to": llm2.get("tok_per_sec"),
        "total_ms_delta": round((trace2.get("total_ms") or 0.0) - (trace1.get("total_ms") or 0.0), 2),
        "vram_load_ms_delta": round((trace2.get("vram_load_ms") or 0.0) - (trace1.get("vram_load_ms") or 0.0), 2),
    }

    # Transform differences
    t1 = set(trace1.get("outcome", {}).get("transforms") or [])
    t2 = set(trace2.get("outcome", {}).get("transforms") or [])
    transforms_diff = {
        "from": sorted(t1),
        "to": sorted(t2),
        "added": sorted(t2 - t1),
        "removed": sorted(t1 - t2),
    }

    # Outcome differences
    out1 = trace1.get("outcome") or {}
    out2 = trace2.get("outcome") or {}
    outcome_diff = {
        "final_refused_from": out1.get("final_refused"),
        "final_refused_to": out2.get("final_refused"),
        "cited_chunks_from": out1.get("cited_chunks") or [],
        "cited_chunks_to": out2.get("cited_chunks") or [],
        "answer_chars_delta": (out2.get("answer_chars") or 0) - (out1.get("answer_chars") or 0),
    }

    return {
        "trace_id_1": trace1.get("trace_id"),
        "trace_id_2": trace2.get("trace_id"),
        "query_diff": query_diff,
        "shown_passages_diff": shown_passages_diff,
        "llm_diff": llm_diff,
        "transforms_diff": transforms_diff,
        "outcome_diff": outcome_diff,
    }


# =============================================================================
# Dry Run Execution (Query Resolution & Retrieval Only)
# =============================================================================

def dry_run(question, book_id="fde", mode="ask", pin=None, select="", index_file=None, embed_fn=None):
    """Run query understanding, reading repairs, pre-LLM guards, and retrieval without calling Ollama."""
    book = load_book_index(book_id=book_id, index_file=index_file)
    if not book:
        raise ValueError(f"Could not load book index for book_id={book_id!r} or index_file={index_file!r}")

    if embed_fn is None:
        def _safe_embed(texts, model=None):
            dim = book.get("embedding_dims") or 768
            if dim != 768:
                return [[1.0] + [0.0] * (dim - 1) for _ in texts]
            try:
                from retrieve import ollama_embed
                res = ollama_embed(texts, model=model)
                if res and len(res[0]) == dim:
                    return res
                return [[1.0] + [0.0] * (dim - 1) for _ in texts]
            except Exception:
                return [[1.0] + [0.0] * (dim - 1) for _ in texts]
        embed_fn = _safe_embed

    def noop_generate(sys_prompt, user_prompt, *args, **kwargs):
        return "Not in this book."

    noop_generate._observe_wrapped = True

    import answer
    with observe.trace(
        source="dry_run",
        mode=mode,
        book_id=book.get("book_id", book_id),
        write_log=False,
    ) as tr:
        if mode == "explain":
            answer.explain(
                book,
                select or question,
                generate_fn=noop_generate,
                chunk_id=pin,
                embed_fn=embed_fn,
            )
        elif mode == "answer":
            answer.respond(
                book,
                question,
                generate_fn=noop_generate,
                pin_chunk=pin,
                selection=select,
                embed_fn=embed_fn,
            )
        else:
            answer.ask(
                book,
                question,
                generate_fn=noop_generate,
                pin_chunk=pin,
                selection=select,
                embed_fn=embed_fn,
            )
        tr.llm_calls.clear()
        tr.transforms = [t for t in tr.transforms if t not in ("parse_refused", "retry_uncited", "half_covered_refused")]
        tr.final_refused = bool(tr.guard_blocked)
        tr.answer_preview = ""
        tr.answer_chars = 0

    trace_dict = tr.to_dict()
    reconstruct_trace(trace_dict, book_index=book)
    return {
        "trace": trace_dict,
        "reconstructed_top5": (trace_dict.get("retrieval") or {}).get("shown_passages", [])[:5],
    }


# =============================================================================
# Eval Inspection & Locked Split Privacy
# =============================================================================

def redact_locked_item(r):
    """Redact confidential text and chunk IDs for locked-split items."""
    redacted = "[REDACTED:locked]"
    if "question" in r:
        r["question"] = redacted
    if "answer" in r:
        r["answer"] = redacted
    if "raw_output_preview" in r:
        r["raw_output_preview"] = redacted
    if "cited_chunks" in r and isinstance(r["cited_chunks"], list):
        r["cited_chunks"] = [redacted for _ in r["cited_chunks"]]
    if "cited" in r and isinstance(r["cited"], list):
        r["cited"] = [redacted for _ in r["cited"]]
    if "gold_chunks" in r and isinstance(r["gold_chunks"], list):
        r["gold_chunks"] = [redacted for _ in r["gold_chunks"]]
    if "citations" in r and isinstance(r["citations"], list):
        for cit in r["citations"]:
            if isinstance(cit, dict):
                cit["chunk_id"] = redacted
                cit["quote"] = redacted

    tr = r.get("trace")
    if isinstance(tr, dict):
        q = tr.get("query")
        if isinstance(q, dict):
            for k in ("raw", "resolved", "asked"):
                if k in q:
                    q[k] = redacted
        llm = tr.get("llm")
        if isinstance(llm, dict):
            for call in llm.get("calls") or []:
                if isinstance(call, dict) and "raw_output_preview" in call:
                    call["raw_output_preview"] = redacted
        ret = tr.get("retrieval")
        if isinstance(ret, dict):
            for p in ret.get("shown_passages") or []:
                if isinstance(p, dict):
                    p["chunk_id"] = redacted
                    if "heading" in p:
                        p["heading"] = redacted
                    if "text" in p:
                        p["text"] = redacted
                    if "text_preview" in p:
                        p["text_preview"] = redacted
        out = tr.get("outcome")
        if isinstance(out, dict):
            if "cited_chunks" in out and isinstance(out["cited_chunks"], list):
                out["cited_chunks"] = [redacted for _ in out["cited_chunks"]]


def inspect_eval(eval_path, failures_only=False, stage=None, item_id=None, allow_locked_text=False):
    """Inspect and filter fair-eval run results with privacy and stage diagnostics."""
    p = Path(eval_path)
    if not p.is_file():
        raise FileNotFoundError(f"Eval file not found: {eval_path}")

    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, list):
        results = data
        data_dict = {"results": results}
    else:
        data_dict = dict(data)
        results = data_dict.get("results") or []

    items = data_dict.get("items") or {
        r.get("id"): r
        for r in results
        if isinstance(r, dict) and r.get("id")
    }

    summary, annotated = summarize_eval_diagnostics(items, results)
    data_dict["summary"] = summary

    filtered = []
    for r in annotated:
        rid = str(r.get("id", ""))
        if item_id and not (rid == item_id or rid.startswith(item_id)):
            continue
        if failures_only and r.get("passed"):
            continue
        if stage and (r.get("diagnostics") or {}).get("stage") != stage:
            continue

        r_copy = copy.deepcopy(r)
        if r_copy.get("split") == "locked" and not allow_locked_text:
            redact_locked_item(r_copy)
        filtered.append(r_copy)

    data_dict["results"] = filtered
    data_dict["filtered_count"] = len(filtered)
    data_dict["total_count"] = len(annotated)
    return data_dict


def compare_evals(current_eval_path, older_eval_path):
    """Compare two eval runs, computing pass-rate deltas, regressions, fixes, and stage transitions."""
    curr_data = inspect_eval(current_eval_path, allow_locked_text=True)
    older_data = inspect_eval(older_eval_path, allow_locked_text=True)

    curr_results = curr_data.get("results") or []
    older_results = older_data.get("results") or []

    curr_map = {r["id"]: r for r in curr_results if "id" in r}
    older_map = {r["id"]: r for r in older_results if "id" in r}

    common_ids = sorted(set(curr_map.keys()).intersection(older_map.keys()))
    regressions = []
    fixes = []
    unchanged_pass = []
    unchanged_fail = []
    stage_transitions = []

    for cid in common_ids:
        c_item = curr_map[cid]
        o_item = older_map[cid]
        c_passed = bool(c_item.get("passed"))
        o_passed = bool(o_item.get("passed"))

        if o_passed and not c_passed:
            regressions.append(cid)
        elif not o_passed and c_passed:
            fixes.append(cid)
        elif o_passed and c_passed:
            unchanged_pass.append(cid)
        else:
            unchanged_fail.append(cid)

        o_stage = (o_item.get("diagnostics") or {}).get("stage")
        c_stage = (c_item.get("diagnostics") or {}).get("stage")
        if o_stage != c_stage:
            stage_transitions.append({"id": cid, "from": o_stage, "to": c_stage})

    curr_summary = curr_data.get("summary") or {}
    older_summary = older_data.get("summary") or {}
    curr_pass_rate = curr_summary.get("overall", {}).get("pass_rate", 0.0)
    older_pass_rate = older_summary.get("overall", {}).get("pass_rate", 0.0)

    return {
        "current_eval": str(current_eval_path),
        "older_eval": str(older_eval_path),
        "current_overall": curr_summary.get("overall"),
        "older_overall": older_summary.get("overall"),
        "pass_rate_delta": round(curr_pass_rate - older_pass_rate, 4),
        "regressions": regressions,
        "fixes": fixes,
        "unchanged_pass_count": len(unchanged_pass),
        "unchanged_fail_count": len(unchanged_fail),
        "stage_transitions": stage_transitions,
    }


# =============================================================================
# CLI & Terminal Formatter
# =============================================================================

def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Inspect runtime traces and stage-attributed eval diagnostics."
    )
    parser.add_argument("--log", type=str, default=None, help="Path to traces.jsonl log file")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output")
    parser.add_argument("--last", type=int, default=None, help="Return the last N traces")
    parser.add_argument("--id", type=str, default=None, help="Inspect a specific trace ID or eval item ID")
    parser.add_argument("--book", type=str, default=None, help="Filter traces by book_id")
    parser.add_argument("--failures", action="store_true", help="Filter traces that failed or have anomalies")
    parser.add_argument("--anomalies", action="store_true", help="Alias for --failures")
    parser.add_argument("--slow", nargs="?", const=2000.0, default=None, type=float, help="Filter traces with total_ms >= MS (default 2000.0)")
    parser.add_argument("--reconstruct", action="store_true", help="Reconstruct chunk text/headings for shown_passages and cited_chunks")
    parser.add_argument("--index-file", type=str, default=None, help="Path to book index JSON file")
    parser.add_argument("--diff", nargs=2, metavar=("ID1", "ID2"), default=None, help="Compare two traces by ID")
    parser.add_argument("--dry-run", type=str, default=None, help="Run dry-run query understanding and retrieval without LLM")
    parser.add_argument("--explain-query", type=str, default=None, help="Alias for --dry-run")
    parser.add_argument("--mode", type=str, default="ask", choices=["ask", "answer", "explain"], help="Mode for dry-run")
    parser.add_argument("--pin", type=str, default=None, help="Pin chunk_id for dry-run")
    parser.add_argument("--select", type=str, default="", help="Selection text for dry-run")
    parser.add_argument("--eval", type=str, default=None, help="Path to fair-eval JSON file")
    parser.add_argument("--stage", type=str, default=None, help="Filter eval items by failure stage bucket")
    parser.add_argument("--compare", type=str, default=None, help="Compare eval run with older eval run JSON")
    parser.add_argument("--allow-locked-text", action="store_true", help="Allow unredacted locked-split text")
    return parser


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # 1. Eval comparison mode
    if args.eval and args.compare:
        comp = compare_evals(args.eval, args.compare)
        if args.json:
            print(json.dumps(comp, indent=2))
        else:
            print(f"Comparing {comp['current_eval']} vs older {comp['older_eval']}")
            print(f"Pass rate: {comp['older_overall']['pass_rate']*100:.1f}% -> {comp['current_overall']['pass_rate']*100:.1f}% (delta: {comp['pass_rate_delta']:+.4f})")
            print(f"Fixes ({len(comp['fixes'])}): {', '.join(comp['fixes']) if comp['fixes'] else 'none'}")
            print(f"Regressions ({len(comp['regressions'])}): {', '.join(comp['regressions']) if comp['regressions'] else 'none'}")
            print(f"Unchanged: {comp['unchanged_pass_count']} passed, {comp['unchanged_fail_count']} failed")
            if comp["stage_transitions"]:
                print("Stage transitions:")
                for st in comp["stage_transitions"][:10]:
                    print(f"  {st['id']}: {st['from']} -> {st['to']}")
        return 0

    # 2. Eval inspection mode
    if args.eval:
        failures_only = args.failures or args.anomalies
        inspected = inspect_eval(
            args.eval,
            failures_only=failures_only,
            stage=args.stage,
            item_id=args.id,
            allow_locked_text=args.allow_locked_text,
        )
        if args.json:
            print(json.dumps(inspected, indent=2))
        else:
            summ = inspected.get("summary") or {}
            ov = summ.get("overall") or {}
            ret = summ.get("retrieval") or {}
            gen = summ.get("generation") or {}
            print(f"Eval Summary for {args.eval}")
            print(f"Overall: {ov.get('passed', 0)}/{ov.get('total', 0)} passed ({ov.get('pass_rate', 0.0)*100:.1f}%)")
            print(f"Retrieval: Recall@5={ret.get('recall_at_5', 0.0)} MRR@5={ret.get('mrr_at_5', 0.0)} (answerable={ret.get('answerable_with_gold', 0)})")
            print(f"Generation given gold shown: {gen.get('passed_given_gold_shown', 0)}/{gen.get('total_gold_shown', 0)} ({gen.get('pass_rate_given_gold_shown', 0.0)*100:.1f}%)")
            stages = summ.get("failure_stages") or {}
            if stages:
                print("Failure stages: " + ", ".join(f"{k}: {v}" for k, v in stages.items()))
            print(f"Items displayed: {inspected.get('filtered_count', 0)}")
            for it in inspected.get("results", [])[:10]:
                print(f"  [{it.get('id')}] passed={it.get('passed')} stage={(it.get('diagnostics') or {}).get('stage')}")
                print(f"    Q: {it.get('question')}")
                if it.get("reasons"):
                    print(f"    Reasons: {'; '.join(it.get('reasons'))}")
        return 0

    # 3. Dry-run mode
    dry_q = args.dry_run or args.explain_query
    if dry_q:
        book_id = args.book or "fde"
        res = dry_run(
            dry_q,
            book_id=book_id,
            mode=args.mode,
            pin=args.pin,
            select=args.select,
            index_file=args.index_file,
        )
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            tr = res.get("trace") or {}
            q = tr.get("query") or {}
            print(f"Dry Run ({tr.get('mode')}, book={tr.get('book_id')})")
            print(f"Raw query: {q.get('raw')}")
            if q.get("guard_blocked"):
                print(f"Guard blocked: {q.get('guard_blocked')}")
            if q.get("reading_repair"):
                print(f"Reading repair: {q.get('reading_repair')}")
            print("Top shown passages:")
            for p in res.get("reconstructed_top5") or []:
                print(f"  Rank {p.get('rank')}: [{p.get('chunk_id')}] (score={p.get('score')}) Heading: {p.get('heading', '')}")
                if p.get("text_preview"):
                    print(f"    Preview: {p.get('text_preview')[:120]}...")
        return 0

    # 4. Diff two traces
    if args.diff:
        traces = load_traces(args.log)
        id1, id2 = args.diff
        t1 = next((t for t in traces if str(t.get("trace_id", "")).startswith(id1)), None)
        t2 = next((t for t in traces if str(t.get("trace_id", "")).startswith(id2)), None)
        if not t1 or not t2:
            sys.stderr.write(f"Error: could not find traces for ids {id1!r} and {id2!r} in log\n")
            return 1
        d = diff_traces(t1, t2)
        if args.json:
            print(json.dumps(d, indent=2))
        else:
            print(f"Diff Trace {id1} -> {id2}")
            if d["query_diff"]:
                print("Query changes:", json.dumps(d["query_diff"]))
            print(f"Passage changes: added={d['shown_passages_diff']['added']}, removed={d['shown_passages_diff']['removed']}")
            if d["shown_passages_diff"]["rank_deltas"]:
                print(f"Rank deltas: {json.dumps(d['shown_passages_diff']['rank_deltas'])}")
            print(f"LLM deltas: latency={d['llm_diff']['llm_ms_delta']}ms, prompt_toks={d['llm_diff']['prompt_tokens_delta']}, completion_toks={d['llm_diff']['completion_tokens_delta']}")
            print(f"Outcome deltas: refused={d['outcome_diff']['final_refused_from']} -> {d['outcome_diff']['final_refused_to']}")
        return 0

    # 5. Live traces log inspection
    traces = load_traces(args.log)
    failures_only = args.failures or args.anomalies
    filtered = filter_traces(
        traces,
        book=args.book,
        trace_id=args.id,
        failures_only=failures_only,
        slow_ms=args.slow,
    )

    if args.last is not None:
        filtered = filtered[-args.last :]

    if args.reconstruct:
        for t in filtered:
            reconstruct_trace(t, index_file=args.index_file)

    if args.json:
        if args.id or args.last is not None or failures_only or args.slow is not None or args.book:
            output = {"traces": filtered, "count": len(filtered)}
        else:
            output = {
                "summary": summarize_trace_log(traces),
                "recent_traces": filtered[-5:] if filtered else [],
            }
        print(json.dumps(output, indent=2))
    else:
        if not (args.id or args.last is not None or failures_only or args.slow is not None or args.book):
            summ = summarize_trace_log(traces)
            log_p = observe.resolve_log_path(args.log)
            print(f"=== Trace Log Summary ({log_p}) ===")
            print(f"Total traces: {summ['total_traces']}")
            print(f"Status: {summ['status'].get('ok', 0)} ok, {summ['status'].get('error', 0)} error")
            print(f"Failures or anomalies: {summ['failures_or_anomalies']}")
            print(f"Slow traces (>=2000ms): {summ['slow_traces_ge_2000ms']}")
            print(f"Books: {', '.join(f'{k} ({v})' for k, v in summ['books'].items()) if summ['books'] else 'none'}")
            lat = summ["latency"]
            print(f"Latency: avg total {lat['avg_total_ms']}ms, avg retrieval {lat['avg_retrieval_ms']}ms, avg LLM {lat['avg_llm_ms']}ms ({lat.get('avg_tok_per_sec') or 'n/a'} tok/s)")
            print("\nRecent traces:")
            for t in traces[-5:]:
                q_raw = (t.get("query") or {}).get("raw", "")
                print(f"  [{t.get('trace_id')}] {t.get('book_id', 'none')} | {t.get('mode', 'ask')} | {t.get('total_ms', 0)}ms | {t.get('status', 'ok')} | Q: {q_raw[:60]}")
        else:
            print(f"Found {len(filtered)} matching traces:")
            for t in filtered:
                q_raw = (t.get("query") or {}).get("raw", "")
                shown_ids = [p.get("chunk_id") for p in (t.get("retrieval") or {}).get("shown_passages", [])]
                cited_ids = (t.get("outcome") or {}).get("cited_chunks") or []
                print(f"[{t.get('trace_id')}] {t.get('book_id')} | {t.get('mode')} | {t.get('total_ms')}ms | status={t.get('status')}")
                print(f"  Query: {q_raw}")
                if (t.get("query") or {}).get("guard_blocked"):
                    print(f"  Guard: {(t.get('query') or {}).get('guard_blocked')}")
                print(f"  Shown: {', '.join(shown_ids[:5])}")
                print(f"  Outcome: refused={(t.get('outcome') or {}).get('final_refused')}, cited={', '.join(cited_ids)}")
                if args.reconstruct and shown_ids:
                    p1 = (t.get("retrieval") or {}).get("shown_passages", [])[0]
                    if p1.get("text_preview"):
                        print(f"  Top passage [{p1.get('chunk_id')}]: {p1.get('heading', '')} | {p1.get('text_preview')[:100]}...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
