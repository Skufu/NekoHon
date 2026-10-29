"""CLI inspector and RAG diagnostic analyzer for runtime traces and eval runs.

Works for both humans and coding agents:
1. Runtime JSONL traces (`artifacts/runs/traces.jsonl`):
     python artifacts/harnesses/trace_inspect.py
     python artifacts/harnesses/trace_inspect.py --traces artifacts/runs/traces.jsonl --last 20 --slow
2. Evaluation JSON runs (`fair-eval-*.json`), including side-by-side comparison:
     python artifacts/harnesses/trace_inspect.py --eval artifacts/runs/fair-eval-...json --failures
     python artifacts/harnesses/trace_inspect.py --eval new.json --compare old.json
     python artifacts/harnesses/trace_inspect.py --eval run.json --json

Stdlib only. Zero LLM calls.
"""

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import observe

DEFAULT_TRACES = ROOT / "artifacts" / "runs" / "traces.jsonl"
FAIR_DATASET = ROOT / "artifacts" / "datasets" / "fair-2026-10-27.jsonl"
INDEX_PATHS = {
    "fde": ROOT / "data" / "index.json",
    "quantization": ROOT / "data" / "index.quantization.json",
    "ddia": ROOT / "data" / "index.ddia.json",
}


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return round(ordered[low] * (1.0 - frac) + ordered[high] * frac, 2)


def diagnose_eval_item(item, result, trace_dict=None):
    """Attribute an evaluated item to its exact RAG/LLM stage without ambiguity."""
    expect = item.get("expect") or result.get("expect")
    passed = bool(result.get("passed"))
    refused = bool(result.get("refused"))
    reasons = result.get("reasons") or []
    gold_chunks = item.get("gold_chunks") or []
    category = item.get("category") or result.get("category") or "unknown"

    tr = trace_dict or result.get("trace") or {}
    q_info = tr.get("query") or {}
    ret_info = tr.get("retrieval") or {}
    llm_info = tr.get("llm") or {}
    out_info = tr.get("outcome") or {}

    shown_passages = ret_info.get("shown_passages") or []
    shown_ids = [p.get("chunk_id") for p in shown_passages if p.get("chunk_id")]
    gold_ranks = [shown_ids.index(g) + 1 for g in gold_chunks if g in shown_ids]
    gold_in_shown = len(gold_ranks) > 0
    best_gold_rank = min(gold_ranks) if gold_ranks else None

    guard_blocked = q_info.get("guard_blocked")
    transforms = out_info.get("transforms") or []
    calls = llm_info.get("calls") or []
    has_trace = bool(tr)

    diag = {
        "has_trace": has_trace,
        "shown_chunks": shown_ids,
        "gold_chunks": list(gold_chunks),
        "gold_in_shown": gold_in_shown if expect == "answer" else None,
        "best_gold_rank": best_gold_rank if expect == "answer" else None,
        "guard_blocked": guard_blocked,
        "transforms": transforms,
        "llm_calls": llm_info.get("call_count", len(calls)),
        "failure_stage": None,
        "defense_source": None,
    }

    if expect == "refuse":
        if passed:
            if guard_blocked:
                diag["defense_source"] = f"guard:{guard_blocked}"
            elif any(t in ("parse_refused", "half_covered_refused", "history_guard_refused") for t in transforms):
                diag["defense_source"] = "post_filter"
            elif has_trace:
                diag["defense_source"] = "model"
            else:
                diag["defense_source"] = "unknown_no_trace"
        else:
            diag["failure_stage"] = "trap_false_answer"
        return diag

    # expect == "answer"
    if passed:
        return diag

    if guard_blocked:
        diag["failure_stage"] = "guard_false_refusal"
    elif has_trace and not gold_in_shown:
        diag["failure_stage"] = "retrieval_miss"
    elif refused:
        if any(t in ("parse_refused", "half_covered_refused", "history_guard_refused") for t in transforms):
            diag["failure_stage"] = "post_filter_false_refusal"
        else:
            diag["failure_stage"] = "model_false_refusal"
    else:
        if any("echoes the question" in r or "dumps long chunk" in r or "verbatim-copies" in r for r in reasons):
            diag["failure_stage"] = "echo_or_chunk_dump"
        elif any("no citation" in r for r in reasons):
            diag["failure_stage"] = "wrong_citation"
        elif any("misses key_fact" in r for r in reasons):
            diag["failure_stage"] = "missing_key_fact"
        else:
            diag["failure_stage"] = "other_answer_defect"

    return diag


def summarize_eval_diagnostics(items_by_id, results):
    """Compute 4-layer RAG & LLM evaluation scorecard across item results."""
    ans_total = 0
    ans_passed = 0
    ans_traced = 0
    gold_top1 = 0
    gold_top5 = 0
    mrr_sum = 0.0
    passed_given_gold_top5 = 0
    passed_without_gold_top5 = 0

    ref_total = 0
    ref_passed = 0
    defense_counts = {}

    failure_stages = {}
    trap_failures_by_cat = {}
    by_category = {}
    by_book = {}

    latencies_ms = []
    retrieval_ms_list = []
    llm_ms_list = []
    tok_rates = []
    vram_stalls = 0
    multi_call_count = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0

    enriched = []
    for res in results:
        rid = res.get("id")
        item = items_by_id.get(rid, res)
        diag = res.get("diagnostics") or diagnose_eval_item(item, res)
        expect = item.get("expect") or res.get("expect")
        passed = bool(res.get("passed"))
        cat = item.get("category") or res.get("category") or "unknown"
        book = item.get("book_id") or res.get("book_id") or "unknown"

        by_category.setdefault(cat, {"passed": 0, "total": 0})
        by_category[cat]["total"] += 1
        if passed:
            by_category[cat]["passed"] += 1

        by_book.setdefault(book, {"passed": 0, "total": 0})
        by_book[book]["total"] += 1
        if passed:
            by_book[book]["passed"] += 1

        if res.get("latency_sec") is not None:
            latencies_ms.append(float(res["latency_sec"]) * 1000.0)

        tr = res.get("trace") or {}
        if tr:
            ret_ms = (tr.get("retrieval") or {}).get("retrieval_ms")
            if ret_ms is not None:
                retrieval_ms_list.append(float(ret_ms))
            llm_block = tr.get("llm") or {}
            if llm_block.get("llm_ms") is not None:
                llm_ms_list.append(float(llm_block["llm_ms"]))
            if llm_block.get("tok_per_sec") is not None:
                tok_rates.append(float(llm_block["tok_per_sec"]))
            if (llm_block.get("call_count") or 0) > 1:
                multi_call_count += 1
            total_prompt_tokens += llm_block.get("prompt_tokens") or 0
            total_completion_tokens += llm_block.get("completion_tokens") or 0
            if (tr.get("vram_load_ms") or 0.0) >= 100.0:
                vram_stalls += 1

        if expect == "answer":
            ans_total += 1
            if passed:
                ans_passed += 1
            if diag.get("has_trace"):
                ans_traced += 1
                rank = diag.get("best_gold_rank")
                if rank is not None:
                    gold_top5 += 1
                    if rank == 1:
                        gold_top1 += 1
                    mrr_sum += 1.0 / rank
                    if passed:
                        passed_given_gold_top5 += 1
                elif passed:
                    passed_without_gold_top5 += 1
        else:
            ref_total += 1
            if passed:
                ref_passed += 1
                src = diag.get("defense_source") or "unknown"
                defense_counts[src] = defense_counts.get(src, 0) + 1

        f_stage = diag.get("failure_stage")
        if f_stage:
            failure_stages[f_stage] = failure_stages.get(f_stage, 0) + 1
            if f_stage == "trap_false_answer":
                trap_failures_by_cat[cat] = trap_failures_by_cat.get(cat, 0) + 1

        enriched.append((item, res, diag))

    total = len(results)
    passed_all = ans_passed + ref_passed
    summary = {
        "overall": {
            "passed": passed_all,
            "total": total,
            "pass_rate": round(passed_all / total, 4) if total else 0.0,
        },
        "retrieval": {
            "evaluated_answer_items": ans_traced,
            "gold_in_top1": gold_top1,
            "recall_at_1": round(gold_top1 / ans_traced, 4) if ans_traced else None,
            "gold_in_shown_top5": gold_top5,
            "recall_at_5": round(gold_top5 / ans_traced, 4) if ans_traced else None,
            "mrr_at_5": round(mrr_sum / ans_traced, 4) if ans_traced else None,
        },
        "generation": {
            "answer_passed": ans_passed,
            "answer_total": ans_total,
            "end_to_end_answer_rate": round(ans_passed / ans_total, 4) if ans_total else 0.0,
            "passed_given_gold_shown": passed_given_gold_top5 if ans_traced else None,
            "gold_shown_total": gold_top5 if ans_traced else None,
            "conditional_pass_rate_given_gold": (
                round(passed_given_gold_top5 / gold_top5, 4) if gold_top5 else None
            ),
            "passed_via_same_chapter_non_gold": passed_without_gold_top5 if ans_traced else None,
        },
        "abstention": {
            "refusal_passed": ref_passed,
            "refusal_total": ref_total,
            "refusal_accuracy": round(ref_passed / ref_total, 4) if ref_total else 0.0,
            "defense_sources": defense_counts,
            "trap_failures_by_category": trap_failures_by_cat,
        },
        "failure_stages": dict(sorted(failure_stages.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_book": by_book,
        "by_category": by_category,
        "runtime": {
            "total_p50_ms": percentile(latencies_ms, 50),
            "total_p90_ms": percentile(latencies_ms, 90),
            "total_max_ms": percentile(latencies_ms, 100),
            "retrieval_p50_ms": percentile(retrieval_ms_list, 50) if retrieval_ms_list else None,
            "llm_p50_ms": percentile(llm_ms_list, 50) if llm_ms_list else None,
            "mean_tok_per_sec": round(sum(tok_rates) / len(tok_rates), 1) if tok_rates else None,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "multi_llm_call_items": multi_call_count,
            "vram_reload_stalls": vram_stalls,
        },
    }
    return summary, enriched


def reconstruct_missing_traces(items_by_id, results):
    """Deterministically reconstruct query + retrieval + guard spans without LLM calls."""
    import answer as A
    from retrieve import load_index

    indexes = {}
    for b, p in INDEX_PATHS.items():
        if p.is_file():
            indexes[b] = load_index(p)

    def _no_llm(*_args, **_kwargs):
        raise RuntimeError("offline trace reconstruction skips LLM calls")

    for res in results:
        if res.get("trace"):
            continue
        rid = res.get("id")
        item = items_by_id.get(rid)
        if not item:
            continue
        book_id = item.get("book_id")
        index = indexes.get(book_id)
        if index is None:
            continue
        raw_q = item["question"]
        history = A.sanitize_history(item.get("history"))
        clean_history = [
            h for h in (history or [])
            if isinstance(h, dict) and (h.get("question") or h.get("answer"))
        ]
        with observe.trace(source="reconstructed", mode="ask", book_id=book_id, write_log=False) as tr:
            observe.record_query(raw_question=raw_q, history_turns=len(clean_history))
            if A.is_prompt_injection(raw_q):
                observe.record_guard("prompt_injection")
            else:
                q_san = A.sanitize_query(raw_q)
                topic_shift = A._is_topic_shift_followup(q_san, history, "", pin_chunk=None, index=index)
                observe.record_query(topic_shift=topic_shift)
                resolved_q = A._resolve_contextual_query(
                    index, q_san, pin_chunk=None, selection="", heading="", history=history
                )
                asked_form = A.canonical_query(resolved_q)
                observe.record_query(resolved_question=resolved_q, asked_form=asked_form)
                ctx = A.retrieval_context(index, asked_form, generate_fn=_no_llm, history=history)
                passages = ctx["passages"]
                eval_q = ctx.get("asked") or q_san
                if not passages:
                    observe.record_guard("empty_passages")
                elif A.names_absent_person(index, eval_q):
                    observe.record_guard("absent_person")
                elif A.has_unmentioned_technical_anchor(index, eval_q):
                    observe.record_guard("unmentioned_technical_anchor")
            observe.finish_body(res)
        res["trace"] = tr.to_dict()


def format_eval_report(summary, enriched, show_failures=False, stage_filter=None, item_id=None, allow_locked=False):
    lines = []
    ov = summary["overall"]
    ret = summary["retrieval"]
    gen = summary["generation"]
    abst = summary["abstention"]
    rt = summary["runtime"]

    lines.append("=" * 78)
    lines.append(
        f"RAG & LLM SCORECARD: {ov['passed']} of {ov['total']} pass "
        f"({ov['total'] - ov['passed']} fail)"
    )
    lines.append("=" * 78)

    if ret["evaluated_answer_items"]:
        n_ret = ret["evaluated_answer_items"]
        lines.append(
            f"1. Retrieval (gold passage in top-5 shown to LLM): "
            f"{ret['gold_in_shown_top5']} of {n_ret} hit "
            f"(top-1: {ret['gold_in_top1']} of {n_ret}, MRR@5: {ret['mrr_at_5']:.3f})"
        )
        g_tot = gen["gold_shown_total"] or 0
        g_pass = gen["passed_given_gold_shown"] or 0
        lines.append(
            f"2. Generation given Retrieval Hit: "
            f"{g_pass} of {g_tot} pass when gold passage is shown "
            f"({g_tot - g_pass} lost in LLM/post-parse)"
        )
        if gen.get("passed_via_same_chapter_non_gold"):
            lines.append(
                f"   (+{gen['passed_via_same_chapter_non_gold']} passed via an alternate chunk in the same gold chapter)"
            )
    else:
        lines.append(
            f"1-2. Answer items (no trace spans attached): "
            f"{gen['answer_passed']} of {gen['answer_total']} pass"
        )

    def_parts = ", ".join(f"{k}={v}" for k, v in sorted(abst["defense_sources"].items()))
    lines.append(
        f"3. Refusal & Trap Defense: {abst['refusal_passed']} of {abst['refusal_total']} traps refused"
        + (f" ({def_parts})" if def_parts else "")
    )

    tok_str = f", {rt['mean_tok_per_sec']} tok/s" if rt["mean_tok_per_sec"] else ""
    stall_str = f", VRAM stalls: {rt['vram_reload_stalls']}" if rt["vram_reload_stalls"] else ""
    lines.append(
        f"4. Latency & Calls: p50 {rt['total_p50_ms']:.0f}ms, p90 {rt['total_p90_ms']:.0f}ms, "
        f"max {rt['total_max_ms']:.0f}ms{tok_str}, multi-call items: {rt['multi_llm_call_items']}{stall_str}"
    )

    if summary["failure_stages"]:
        lines.append("\nFailure Attribution (1 failure = 1 root-cause stage):")
        for stg, cnt in summary["failure_stages"].items():
            lines.append(f"  - {stg:28s}: {cnt}")

    lines.append("\nBy Book:")
    for bk, counts in sorted(summary["by_book"].items()):
        lines.append(
            f"  - {bk:16s}: {counts['passed']} of {counts['total']} pass "
            f"({counts['total'] - counts['passed']} fail)"
        )

    if item_id or show_failures or stage_filter:
        lines.append("\n" + "-" * 78)
        lines.append("ITEM DRILL-DOWN:")
        for item, res, diag in enriched:
            if item_id and res.get("id") != item_id:
                continue
            if not item_id:
                if res.get("passed"):
                    continue
                if stage_filter and diag.get("failure_stage") != stage_filter:
                    continue
            is_locked = (item.get("split") or res.get("split")) == "locked"
            tr = res.get("trace") or {}
            q_block = tr.get("query") or {}
            q_text = "[LOCKED SPLIT HIDDEN]" if (is_locked and not allow_locked) else item.get("question", "")
            ans_preview = (
                "[LOCKED SPLIT HIDDEN]"
                if (is_locked and not allow_locked)
                else (res.get("answer") or "").replace("\n", " | ")[:180]
            )
            lines.append(
                f"\n[{res.get('id')}] stage={diag.get('failure_stage') or 'PASS'} "
                f"book={res.get('book_id')} cat={res.get('category')} expect={res.get('expect')} "
                f"({res.get('latency_sec', 0):.2f}s)"
            )
            lines.append(f"  question : {q_text}")
            if not is_locked or allow_locked:
                if q_block.get("asked") and q_block.get("asked") != item.get("question"):
                    lines.append(f"  asked_as : {q_block.get('asked')}")
            if diag.get("guard_blocked"):
                lines.append(f"  guard    : {diag['guard_blocked']}")
            if diag.get("shown_chunks"):
                lines.append(
                    f"  retrieval: shown={diag['shown_chunks']} | gold={diag['gold_chunks']} "
                    f"| best_gold_rank={diag['best_gold_rank']}"
                )
            if diag.get("transforms"):
                lines.append(f"  transforms: {diag['transforms']}")
            for r in res.get("reasons") or []:
                lines.append(f"  reason   : {r}")
            lines.append(f"  answer   : {ans_preview}")

    return "\n".join(lines)


def compare_eval_runs(items_by_id, new_results, old_results):
    old_map = {r["id"]: r for r in old_results}
    wins = []
    losses = []
    for r in new_results:
        rid = r["id"]
        prev = old_map.get(rid)
        if not prev:
            continue
        if r["passed"] and not prev["passed"]:
            old_diag = prev.get("diagnostics") or diagnose_eval_item(items_by_id.get(rid, prev), prev)
            wins.append((rid, r.get("category"), old_diag.get("failure_stage")))
        elif not r["passed"] and prev["passed"]:
            new_diag = r.get("diagnostics") or diagnose_eval_item(items_by_id.get(rid, r), r)
            losses.append((rid, r.get("category"), new_diag.get("failure_stage")))
    return {"wins": wins, "losses": losses}


def inspect_runtime_traces(traces_path, last_n=50, slow_only=False, failures_only=False, trace_id=None):
    if not traces_path.is_file():
        return {"count": 0, "error": f"No trace file at {traces_path}"}, f"No runtime traces found at {traces_path}."

    records = []
    with traces_path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue

    if trace_id:
        matches = [r for r in records if r.get("trace_id") == trace_id]
        return {"matches": matches}, json.dumps(matches, indent=2)

    window = records[-last_n:] if last_n and last_n > 0 else records
    if not window:
        return {"count": 0}, "Trace file is empty."

    totals = [r.get("total_ms", 0.0) for r in window]
    ret_ms = [(r.get("retrieval") or {}).get("retrieval_ms", 0.0) for r in window]
    llm_ms = [(r.get("llm") or {}).get("llm_ms", 0.0) for r in window if (r.get("llm") or {}).get("call_count")]
    ttfts = [
        (r.get("llm") or {}).get("ttft_ms")
        for r in window
        if (r.get("llm") or {}).get("ttft_ms") is not None
    ]
    tok_rates = [
        (r.get("llm") or {}).get("tok_per_sec")
        for r in window
        if (r.get("llm") or {}).get("tok_per_sec") is not None
    ]
    stalls = [r for r in window if (r.get("vram_load_ms") or 0.0) >= 100.0]
    errors = [r for r in window if r.get("status") != "ok"]
    refusals = [r for r in window if (r.get("outcome") or {}).get("final_refused")]
    multi_calls = [r for r in window if ((r.get("llm") or {}).get("call_count") or 0) > 1]

    summary = {
        "total_logged": len(records),
        "window_count": len(window),
        "errors": len(errors),
        "refusals": len(refusals),
        "multi_llm_calls": len(multi_calls),
        "vram_stalls": len(stalls),
        "total_p50_ms": percentile(totals, 50),
        "total_p90_ms": percentile(totals, 90),
        "total_max_ms": percentile(totals, 100),
        "retrieval_p50_ms": percentile(ret_ms, 50),
        "llm_p50_ms": percentile(llm_ms, 50) if llm_ms else None,
        "ttft_p50_ms": percentile(ttfts, 50) if ttfts else None,
        "mean_tok_per_sec": round(sum(tok_rates) / len(tok_rates), 1) if tok_rates else None,
    }

    lines = [
        "=" * 78,
        f"LIVE RUNTIME TRACES ({len(window)} most recent of {len(records)} total in {traces_path.name})",
        "=" * 78,
        f"Latency  : p50 {summary['total_p50_ms']:.0f}ms | p90 {summary['total_p90_ms']:.0f}ms | max {summary['total_max_ms']:.0f}ms "
        f"(retrieval p50 {summary['retrieval_p50_ms']:.0f}ms"
        + (f", LLM p50 {summary['llm_p50_ms']:.0f}ms" if summary["llm_p50_ms"] is not None else "")
        + (f", TTFT p50 {summary['ttft_p50_ms']:.0f}ms" if summary["ttft_p50_ms"] is not None else "")
        + ")",
        f"Health   : {len(errors)} errors | {len(refusals)} refusals | "
        f"{len(multi_calls)} multi-call retries | {len(stalls)} VRAM reload stalls (>=100ms)"
        + (f" | {summary['mean_tok_per_sec']} tok/s" if summary["mean_tok_per_sec"] else ""),
        "-" * 78,
    ]

    shown_rows = window
    if slow_only:
        p90 = summary["total_p90_ms"]
        shown_rows = [r for r in shown_rows if r.get("total_ms", 0.0) >= max(1000.0, p90)]
    if failures_only:
        shown_rows = [
            r for r in shown_rows
            if r.get("status") != "ok"
            or (r.get("outcome") or {}).get("final_refused")
            or ((r.get("llm") or {}).get("call_count") or 0) > 1
        ]

    for r in shown_rows[-15:]:
        q = ((r.get("query") or {}).get("raw") or "")[:48]
        out = r.get("outcome") or {}
        llm = r.get("llm") or {}
        tag = "ERR" if r.get("status") != "ok" else ("REF" if out.get("final_refused") else "ANS")
        lines.append(
            f"{r.get('trace_id')}  {r.get('mode', ''):8s}  {r.get('book_id', ''):12s}  "
            f"{tag}  {r.get('total_ms', 0):6.0f}ms  calls={llm.get('call_count', 0)}  {q}"
        )

    return summary, "\n".join(lines)


def load_fair_items():
    items = {}
    if FAIR_DATASET.is_file():
        with FAIR_DATASET.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    obj = json.loads(line)
                    items[obj["id"]] = obj
    return items


def main():
    parser = argparse.ArgumentParser(description="Inspect runtime traces and RAG evaluation runs.")
    parser.add_argument("--traces", default=str(DEFAULT_TRACES), help="Path to runtime JSONL traces.")
    parser.add_argument("--eval", dest="eval_path", default="", help="Path to fair-eval JSON result file.")
    parser.add_argument("--compare", default="", help="Baseline fair-eval JSON to diff against.")
    parser.add_argument("--reconstruct", action="store_true", help="Reconstruct retrieval traces for older eval JSONs.")
    parser.add_argument("--failures", action="store_true", help="Drill down into failed items / traces.")
    parser.add_argument("--slow", action="store_true", help="Filter runtime traces to slow requests.")
    parser.add_argument("--stage", default="", help="Filter eval drill-down to one failure stage.")
    parser.add_argument("--id", dest="target_id", default="", help="Inspect one specific eval item ID or trace_id.")
    parser.add_argument("--last", type=int, default=50, help="Number of recent runtime traces to summarize.")
    parser.add_argument("--allow-locked-text", action="store_true", help="Allow printing locked-split text in drill-down.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON for agents.")
    args = parser.parse_args()

    if args.eval_path:
        eval_file = Path(args.eval_path)
        data = json.loads(eval_file.read_text(encoding="utf-8"))
        results = data.get("results") or []
        items_by_id = load_fair_items()
        if args.reconstruct or any(not r.get("trace") for r in results):
            if args.reconstruct:
                reconstruct_missing_traces(items_by_id, results)
        summary, enriched = summarize_eval_diagnostics(items_by_id, results)

        diff = None
        if args.compare:
            old_data = json.loads(Path(args.compare).read_text(encoding="utf-8"))
            old_results = old_data.get("results") or []
            if args.reconstruct:
                reconstruct_missing_traces(items_by_id, old_results)
            diff = compare_eval_runs(items_by_id, results, old_results)
            summary["comparison"] = diff

        if args.json:
            print(json.dumps(summary, indent=2))
            return

        report = format_eval_report(
            summary,
            enriched,
            show_failures=args.failures,
            stage_filter=args.stage or None,
            item_id=args.target_id or None,
            allow_locked=args.allow_locked_text,
        )
        print(report)
        if diff:
            print("\n" + "-" * 78)
            print(f"COMPARISON vs {Path(args.compare).name}: +{len(diff['wins'])} wins, -{len(diff['losses'])} losses")
            for wid, cat, old_stg in diff["wins"]:
                print(f"  WIN  {wid:16s} ({cat}) — fixed prior {old_stg}")
            for lid, cat, new_stg in diff["losses"]:
                print(f"  LOSS {lid:16s} ({cat}) — regressed at {new_stg}")
        return

    summary, text = inspect_runtime_traces(
        Path(args.traces),
        last_n=args.last,
        slow_only=args.slow,
        failures_only=args.failures,
        trace_id=args.target_id or None,
    )
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(text)


if __name__ == "__main__":
    main()
