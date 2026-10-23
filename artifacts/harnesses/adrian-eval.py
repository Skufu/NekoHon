import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from engine.answering import answer as A
from engine.retrieval.retrieve import INDEX, load_index
from engine.answering.prompt import REFUSAL

DATASET_PATH = ROOT / "artifacts" / "datasets" / "adrian-realworld-eval-2026-10-17.json"
EVIDENCE_DIR = ROOT / "artifacts" / "runs" / "adrian-eval"
SERVER_URL = "http://127.0.0.1:8000/ask"


def is_self_contained_new_topic(question: str) -> bool:
    q = question.strip()
    lower = q.lower()
    starts_with_def = bool(re.match(r"^(?:what is|what are|define|who is)\b", q, re.I))
    if not starts_with_def:
        return False
    if re.match(r"^(?:what are the (?:specific )?reasons|what are the (?:cost )?trade-offs|what is the reason|what is the trade-off)\b", q, re.I):
        return False
    deictic = re.search(r"\b(?:this|that|it|its|they|them|their|these|those|here)\b", lower, re.I)
    if deictic:
        return False
    return True


def post_http(payload, timeout=60):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SERVER_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_direct(index, payload):
    mode = payload.get("mode")
    history = payload.get("history")
    chunk_id = payload.get("chunk_id")
    end_chunk_id = payload.get("end_chunk_id")
    selection = payload.get("selection") or ""
    heading = payload.get("heading") or ""
    question = payload.get("question") or ""

    if mode == "explain":
        return A.explain(index, selection, chunk_id=chunk_id, end_chunk_id=end_chunk_id, heading=heading)
    elif mode == "ask":
        return A.ask(index, question, history=history, pin_chunk=chunk_id, end_chunk_id=end_chunk_id, selection=selection, heading=heading)
    elif mode == "answer":
        return A.respond(index, question, history=history, pin_chunk=chunk_id, end_chunk_id=end_chunk_id, selection=selection, heading=heading)
    else:
        raise ValueError(f"Unsupported mode: {mode}")


def evaluate_turn(turn_idx, turn_spec, response, expected, finished_turns=None, index=None):
    reasons = []
    refused = bool(response.get("refused"))
    answer_text = (response.get("answer") or "").strip()
    citations = response.get("citations") or []
    cited_chapters = [str(c.get("chapter")) for c in citations if c.get("chapter")]
    cited_chunks = [c.get("chunk_id") for c in citations if c.get("chunk_id")]

    exp_refused = expected.get("refused")
    if exp_refused is True:
        if not refused:
            reasons.append("Expected refusal, but got answered")
        if expected.get("must_be_exact_refusal") and answer_text != REFUSAL:
            reasons.append(f"Answer was '{answer_text[:40]}...', expected exact '{REFUSAL}'")
        return reasons

    if exp_refused is False and refused:
        reasons.append(f"Expected answer, but got refusal '{REFUSAL}'")
        return reasons

    if refused:
        reasons.append(f"Answer refused with '{REFUSAL}'")
        return reasons

    quote = ""
    if citations and isinstance(citations, list) and len(citations) > 0:
        first_cite = citations[0]
        quote = (first_cite.get("quote") or "").strip()
        if quote:
            if quote.count("(") != quote.count(")"):
                reasons.append(f"Truncated quote: unbalanced parentheses ({quote!r})")
            if re.search(r"\b(?:on|of|in|to|for|with|by|at|from|the|a|an|and|or|as|not|simply|large|into|such|than)\s*$", quote, re.I):
                reasons.append(f"Truncated quote: dangling word at end ({quote!r})")

    leaky_phrases = [
        "The passages do not mention Regarding",
        "Regarding ",
        "How does this.",
        "In this context",
    ]
    for lp in leaky_phrases:
        if lp in answer_text:
            reasons.append(f"Leaky internal prefix/boilerplate: contains '{lp}'")

    lines = [l.strip() for l in answer_text.splitlines() if l.strip()]
    if len(lines) >= 2:
        gloss = lines[1]
        if gloss.lower().startswith(("[ch.", "[chapter")):
            reasons.append(f"Leaky 2nd-line gloss starts with chapter citation: '{gloss[:35]}...'")

    if len(lines) < 2:
        reasons.append("Missing 2nd-line gloss")
    else:
        gloss = lines[1]
        norm_gloss = re.sub(r"[^\w\s]", "", gloss).lower()
        norm_quote = re.sub(r"[^\w\s]", "", quote).lower()
        norm_gloss_ws = " ".join(norm_gloss.split())
        norm_quote_ws = " ".join(norm_quote.split())
        if norm_quote_ws and (norm_gloss_ws == norm_quote_ws or (len(norm_gloss_ws) > 30 and norm_gloss_ws in norm_quote_ws)):
            reasons.append("Gloss repeats quote verbatim")

    followups = response.get("followups") or []
    cited_cid = citations[0].get("chunk_id") if citations else None
    chunk_text = ""
    if index and cited_cid and "chunks" in index:
        for c in index["chunks"]:
            if c.get("chunk_id") == cited_cid:
                chunk_text = c.get("text") or ""
                break

    for pill in followups:
        for bad_phrase in ("Google Ads", "Microsoft Excel", "data or otherwise", "Generation Storage Ingestion"):
            if bad_phrase.lower() in pill.lower():
                reasons.append(f"Bad generated pill '{pill}': contains '{bad_phrase}'")
        if chunk_text:
            for m in re.finditer(r"\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\s+([A-Z][a-z]+)\b", pill):
                w1, w2, w3 = m.group(1), m.group(2), m.group(3)
                if re.search(rf"\b{w1}\s*\n\s*{w2}\s*\n\s*{w3}\b", chunk_text, re.I):
                    reasons.append(f"Bad generated pill '{pill}': 3+ capitalized words glued across newlines ('{m.group(0)}')")
                    break

    exp_chapter = expected.get("chapter")
    allowed_chapters = expected.get("allowed_chapters")
    if exp_chapter:
        if not cited_chapters:
            reasons.append(f"No chapter cited, expected Ch. {exp_chapter}")
        elif not any(ch == exp_chapter for ch in cited_chapters):
            reasons.append(f"Cited chapter(s) {cited_chapters} != expected Ch. {exp_chapter}")
    elif allowed_chapters:
        allowed_str = [str(ac) for ac in allowed_chapters]
        if not cited_chapters:
            reasons.append(f"No chapter cited, expected one of Ch. {allowed_str}")
        elif not any(ch in allowed_str for ch in cited_chapters):
            reasons.append(f"Cited chapter(s) {cited_chapters} not in allowed chapters {allowed_str}")

    if expected.get("same_chapter_as_previous_turn") or expected.get("match_previous_turn_chapter"):
        if finished_turns:
            prev_turn_cites = finished_turns[-1].get("citations") or []
            prev_chapters = [str(c.get("chapter")) for c in prev_turn_cites if c.get("chapter")]
            if prev_chapters and cited_chapters:
                if not any(ch in prev_chapters for ch in cited_chapters):
                    reasons.append(f"Chapter drift: cited {cited_chapters}, expected same chapter as previous turn ({prev_chapters})")

    forbidden_chaps = expected.get("forbidden_chapters") or []
    for fch in forbidden_chaps:
        if any(ch == str(fch) for ch in cited_chapters):
            reasons.append(f"Hallucinatory chapter jump: cited forbidden Ch. {fch} (from {cited_chunks})")

    must_contain = expected.get("must_contain") or []
    for mc in must_contain:
        if mc.lower() not in answer_text.lower():
            reasons.append(f"Answer missing required concept '{mc}'")

    forbidden_terms = expected.get("forbidden_terms") or []
    for ft in forbidden_terms:
        if ft.lower() in answer_text.lower():
            reasons.append(f"Answer contains off-topic/forbidden term '{ft}'")

    forbidden_answers = expected.get("forbidden_answers") or []
    for fa in forbidden_answers:
        if fa.lower() in answer_text.lower():
            reasons.append(f"Answer contains forbidden cop-out phrase '{fa}'")

    forbidden_hal = expected.get("forbidden_hallucinations") or []
    for fh in forbidden_hal:
        if fh.lower() in answer_text.lower():
            reasons.append(f"Answer contains hallucination: '{fh}'")

    return reasons


def run_scenario(scenario, index, use_http=True):
    gloss_kind = None
    gloss_chunk_id = None
    gloss_heading = None
    gloss_selection = None
    finished_turns = []
    scenario_passed = True
    turn_results = []

    for t_spec in scenario["turns"]:
        turn_num = t_spec["turn"]
        action = t_spec["action"]
        expected = t_spec.get("expected") or {}
        pre_reasons = []

        if action == "explainSelection":
            gloss_kind = "selection"
            gloss_chunk_id = t_spec.get("chunk_id")
            gloss_heading = t_spec.get("heading", "")
            gloss_selection = t_spec.get("selection")
            payload = {
                "mode": "explain",
                "selection": t_spec["selection"],
                "chunk_id": gloss_chunk_id,
                "heading": gloss_heading,
            }
            q_text = t_spec["selection"]

        elif action == "askSelection":
            gloss_kind = "selection"
            gloss_chunk_id = t_spec.get("chunk_id")
            gloss_heading = t_spec.get("heading", "")
            gloss_selection = t_spec.get("selection")
            q_text = t_spec["question"]
            payload = {
                "mode": "ask",
                "question": q_text,
                "selection": t_spec["selection"],
                "chunk_id": gloss_chunk_id,
                "heading": gloss_heading,
            }

        elif action == "submitWholeBook":
            gloss_kind = "whole"
            gloss_chunk_id = None
            gloss_heading = ""
            gloss_selection = None
            q_text = t_spec["question"]
            payload = {
                "mode": "answer",
                "question": q_text,
            }

        elif action == "clickGeneratedPill":
            pill_idx = t_spec.get("pill_index", 0)
            last_followups = finished_turns[-1].get("followups", []) if finished_turns else []
            if not last_followups or pill_idx >= len(last_followups):
                pre_reasons.append(f"clickGeneratedPill: pill_index {pill_idx} out of range in followups: {last_followups}")
                q_text = f"MISSING_PILL_INDEX_{pill_idx}"
            else:
                q_text = last_followups[pill_idx]

            is_new_topic = (gloss_kind == "whole") or is_self_contained_new_topic(q_text)
            last_cite_id = None
            if finished_turns:
                last_turn_cites = finished_turns[-1].get("citations") or []
                if last_turn_cites:
                    last_cite_id = last_turn_cites[0].get("chunk_id")

            target_chunk = None if is_new_topic else (last_cite_id or gloss_chunk_id)
            target_heading = None if is_new_topic else (gloss_heading or None)
            target_selection = None if is_new_topic else (gloss_selection if gloss_kind == "selection" else None)
            turn_mode = "ask" if gloss_kind == "selection" else "answer"

            hist = []
            for ft in finished_turns[-2:]:
                hist.append({
                    "question": ft["question"],
                    "answer": ft["answer"],
                })

            payload = {
                "mode": turn_mode,
                "question": q_text,
                "chunk_id": target_chunk or None,
                "heading": target_heading or None,
                "selection": target_selection or None,
                "history": hist if hist else None,
            }
            payload = {k: v for k, v in payload.items() if v is not None}

        elif action == "askFollowUp":
            q_text = t_spec["question"]
            is_new_topic = (gloss_kind == "whole") or is_self_contained_new_topic(q_text)
            last_cite_id = None
            if finished_turns:
                last_turn_cites = finished_turns[-1].get("citations") or []
                if last_turn_cites:
                    last_cite_id = last_turn_cites[0].get("chunk_id")

            target_chunk = None if is_new_topic else (last_cite_id or gloss_chunk_id)
            target_heading = None if is_new_topic else (gloss_heading or None)
            target_selection = None if is_new_topic else (gloss_selection if gloss_kind == "selection" else None)
            turn_mode = "ask" if gloss_kind == "selection" else "answer"

            hist = []
            for ft in finished_turns[-2:]:
                hist.append({
                    "question": ft["question"],
                    "answer": ft["answer"],
                })

            payload = {
                "mode": turn_mode,
                "question": q_text,
                "chunk_id": target_chunk or None,
                "heading": target_heading or None,
                "selection": target_selection or None,
                "history": hist if hist else None,
            }
            payload = {k: v for k, v in payload.items() if v is not None}
        else:
            raise ValueError(f"Unknown action: {action}")

        t0 = time.perf_counter()
        try:
            if use_http:
                resp = post_http(payload)
            else:
                resp = run_direct(index, payload)
        except Exception as e:
            resp = {"error": str(e), "refused": True, "answer": f"ERROR: {e}", "citations": []}
        elapsed = round(time.perf_counter() - t0, 3)

        reasons = pre_reasons + evaluate_turn(turn_num, t_spec, resp, expected, finished_turns=finished_turns, index=index)
        turn_passed = (len(reasons) == 0)
        if not turn_passed:
            scenario_passed = False

        turn_record = {
            "turn": turn_num,
            "action": action,
            "question": q_text,
            "payload": payload,
            "elapsed_sec": elapsed,
            "passed": turn_passed,
            "refused": bool(resp.get("refused")),
            "answer": resp.get("answer", ""),
            "citations": resp.get("citations", []),
            "figures": resp.get("figures", []),
            "followups": resp.get("followups", []),
            "reasons": reasons,
        }
        turn_results.append(turn_record)

        finished_turns.append({
            "question": q_text,
            "answer": resp.get("answer", ""),
            "citations": resp.get("citations", []),
            "followups": resp.get("followups", []),
        })

    return {
        "id": scenario["id"],
        "category": scenario["category"],
        "name": scenario["name"],
        "passed": scenario_passed,
        "turns": turn_results,
    }


def main():
    parser = argparse.ArgumentParser(description="Adrian Real-World Multi-Turn Eval")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--id", type=str, default=None)
    parser.add_argument("--category", type=str, default=None)
    parser.add_argument("--direct", action="store_true", help="Run direct in-process rather than HTTP :8000")
    args = parser.parse_args()

    scenarios = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    if args.id:
        scenarios = [s for s in scenarios if s["id"] == args.id]
    if args.category:
        scenarios = [s for s in scenarios if s["category"] == args.category]
    if args.limit:
        scenarios = scenarios[:args.limit]

    print(f"Loaded {len(scenarios)} Adrian real-world scenarios from {DATASET_PATH.name}")
    index = load_index(INDEX)

    use_http = not args.direct
    if use_http:
        try:
            req = urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2)
            health = json.loads(req.read().decode())
            print(f"Connected to live server on :8000 (Ollama: {health.get('ollama')})")
        except Exception as e:
            print(f"Warning: Server on :8000 not reachable ({e}). Falling back to in-process --direct.")
            use_http = False

    print(f"Mode: {'HTTP :8000' if use_http else 'in-process'}")
    print("=" * 90)

    results = []
    cat_summary = {}

    for i, scen in enumerate(scenarios, 1):
        scen_id = scen["id"]
        cat = scen["category"]
        name = scen["name"]
        if cat not in cat_summary:
            cat_summary[cat] = {"passed": 0, "total": 0}

        print(f"\n[{i:02d}/{len(scenarios):02d}] {scen_id} [{cat}]: {name}")
        res = run_scenario(scen, index, use_http=use_http)
        results.append(res)

        cat_summary[cat]["total"] += 1
        if res["passed"]:
            cat_summary[cat]["passed"] += 1
            print(f"  -> RESULT: PASS (all {len(res['turns'])} turns clean)")
        else:
            print(f"  -> RESULT: FAIL")
            for t in res["turns"]:
                if not t["passed"]:
                    print(f"     Turn {t['turn']} ({t['action']} '{t['question'][:35]}'): {'; '.join(t['reasons'])}")
                    ans_first = t['answer'].splitlines()[0] if t['answer'] else "<EMPTY>"
                    ans_second = t['answer'].splitlines()[1] if len(t['answer'].splitlines()) > 1 else ""
                    print(f"       Answer: {ans_first}")
                    if ans_second:
                        print(f"       Gloss:  {ans_second}")

    total_scenarios = len(results)
    passed_scenarios = sum(1 for r in results if r["passed"])
    failed_scenarios = total_scenarios - passed_scenarios
    pass_pct = (passed_scenarios / total_scenarios * 100) if total_scenarios else 0

    print("\n" + "=" * 90)
    print(f"ADRIAN REAL-WORLD MULTI-TURN EVALUATION REPORT (2026-10-17)")
    print("=" * 90)
    print(f"Overall Scenario Pass Rate: {passed_scenarios}/{total_scenarios} ({pass_pct:.1f}%)")
    print(f"Overall Failure Rate:       {failed_scenarios}/{total_scenarios} ({100-pass_pct:.1f}%)")
    print("-" * 90)
    print(f"Category Breakdown:")
    for cat, stats in cat_summary.items():
        pct = (stats["passed"] / stats["total"] * 100) if stats["total"] else 0
        print(f"  {cat:<26}: {stats['passed']:>2}/{stats['total']:<2} ({pct:>5.1f}% pass | {100-pct:>5.1f}% fail)")

    ev_json_path = EVIDENCE_DIR / "adrian-eval-2026-10-17.json"
    ev_json_path.parent.mkdir(parents=True, exist_ok=True)
    ev_json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved detailed run evidence to {ev_json_path}")


if __name__ == "__main__":
    main()
