"""Cross-Book Evil Stress Eval Harness 2026-10-18.

Evaluates multi-turn scenarios across multiple books (`quantization`, `ddia`)
and adversarial cross-book traps.
Simulates the exact payload construction of `web/lib/store.ts` with `book_id`.
Enforces strict quality gates, cross-book isolation, false-premise defense,
and transparently documents all passes and failures.

Usage:
    python artifacts/harnesses/crossbook-evil-eval.py
    python artifacts/harnesses/crossbook-evil-eval.py --id crossbook-01
    python artifacts/harnesses/crossbook-evil-eval.py --category crossbook_isolation_and_shifts
    python artifacts/harnesses/crossbook-evil-eval.py --limit 10
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from prompt import REFUSAL

DATASET_PATH = ROOT / "artifacts" / "datasets" / "crossbook-evil-eval-2026-10-18.json"
EVIDENCE_DIR = ROOT / "artifacts" / "runs" / "crossbook-eval"
SERVER_URL = "http://127.0.0.1:8000/ask"


def is_self_contained_new_topic(question: str) -> bool:
    """Replication of web/lib/store.ts isSelfContainedNewTopic()."""
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


def evaluate_turn(turn_idx, turn_spec, response, expected, finished_turns=None):
    reasons = []
    refused = bool(response.get("refused"))
    answer_text = (response.get("answer") or "").strip()
    citations = response.get("citations") or []
    cited_chapters = [str(c.get("chapter")) for c in citations if c.get("chapter")]
    cited_chunks = [c.get("chunk_id") for c in citations if c.get("chunk_id")]
    attached_figures = response.get("figures") or []
    attached_fig_ids = [f.get("id") for f in attached_figures if f.get("id")]

    exp_refused = expected.get("refused")
    if exp_refused is True:
        if not refused:
            reasons.append("Expected refusal, but got answered")
        if expected.get("refusal_exact") and answer_text != expected.get("refusal_exact"):
            reasons.append(f"Answer was '{answer_text[:40]}...', expected exact '{expected.get('refusal_exact')}'")
        return reasons

    if exp_refused is False and refused:
        reasons.append(f"Expected answer, but got refusal '{REFUSAL}'")
        return reasons

    if refused:
        reasons.append(f"Answer refused with '{REFUSAL}'")
        return reasons

    # Strict Automatic Quality Gates on every non-refused answer:
    # 1. Truncated Quote Gate
    quote = ""
    if citations and isinstance(citations, list) and len(citations) > 0:
        first_cite = citations[0]
        quote = (first_cite.get("quote") or "").strip()
        if quote:
            if quote.count("(") != quote.count(")"):
                reasons.append(f"Truncated quote: unbalanced parentheses ({quote!r})")
            if re.search(r"\b(?:on|of|in|to|for|with|by|at|from|the|a|an|and|or|as|not|simply|large|into|such|than)\s*$", quote, re.I):
                reasons.append(f"Truncated quote: dangling word at end ({quote!r})")

    # 2. Leaky Internal Prefix / Boilerplate Gate
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

    # 3. Quote-Repeating Gloss Gate
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

    # 4. Chapter checks
    exp_chapter = expected.get("chapter")
    if exp_chapter:
        if not cited_chapters:
            reasons.append(f"No chapter cited, expected Ch. {exp_chapter}")
        elif not any(ch == exp_chapter for ch in cited_chapters):
            reasons.append(f"Cited chapter(s) {cited_chapters} != expected Ch. {exp_chapter}")

    # 5. Must contain strings
    must_contain = expected.get("must_contain") or []
    for mc in must_contain:
        if mc.lower() not in answer_text.lower():
            reasons.append(f"Answer missing required concept '{mc}'")

    # 6. Forbidden terms
    forbidden_terms = expected.get("forbidden_terms") or []
    for ft in forbidden_terms:
        if ft.lower() in answer_text.lower():
            reasons.append(f"Answer contains forbidden term/phrase '{ft}'")

    # 7. Figure attachment check
    exp_figure = expected.get("figure_attached")
    if exp_figure:
        if not any(f_id == exp_figure for f_id in attached_fig_ids):
            reasons.append(f"Expected figure '{exp_figure}' attached, but got {attached_fig_ids}")

    return reasons


def run_scenario(scenario):
    gloss_kind = None
    gloss_chunk_id = None
    gloss_heading = None
    gloss_selection = None
    finished_turns = []
    scenario_passed = True
    turn_results = []
    book_id = scenario.get("book_id", "quantization")

    for t_spec in scenario["turns"]:
        turn_num = t_spec["turn"]
        action = t_spec["action"]
        t_book_id = t_spec.get("book_id") or book_id
        expected = t_spec.get("expected") or {}
        pre_reasons = []

        if action == "explainSelection":
            gloss_kind = "selection"
            gloss_chunk_id = t_spec.get("chunk_id")
            gloss_heading = t_spec.get("heading", "")
            gloss_selection = t_spec.get("selection")
            payload = {
                "mode": "explain",
                "book_id": t_book_id,
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
                "book_id": t_book_id,
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
                "book_id": t_book_id,
                "question": q_text,
            }

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
                "book_id": t_book_id,
                "question": q_text,
                "chunk_id": target_chunk or None,
                "heading": target_heading or None,
                "selection": target_selection or None,
                "history": hist if hist else None,
            }
            payload = {k: v for k, v in payload.items() if v is not None}
        else:
            raise ValueError(f"Unknown action: {action}")

        # Execute
        t0 = time.perf_counter()
        try:
            resp = post_http(payload)
        except Exception as e:
            resp = {"error": str(e), "answer": "", "citations": [], "figures": [], "refused": True}
        elapsed = time.perf_counter() - t0

        reasons = pre_reasons + evaluate_turn(turn_num, t_spec, resp, expected, finished_turns)
        turn_passed = len(reasons) == 0
        if not turn_passed:
            scenario_passed = False

        record = {
            "turn": turn_num,
            "action": action,
            "question": q_text,
            "payload": payload,
            "response": resp,
            "elapsed_seconds": round(elapsed, 2),
            "passed": turn_passed,
            "reasons": reasons,
        }
        turn_results.append(record)
        finished_turns.append({
            "question": q_text,
            "answer": resp.get("answer", ""),
            "citations": resp.get("citations", []),
            "figures": resp.get("figures", []),
            "followups": resp.get("followups", []),
        })

    return {
        "id": scenario["id"],
        "category": scenario["category"],
        "book_id": book_id,
        "name": scenario["name"],
        "passed": scenario_passed,
        "turns": turn_results,
    }


def main():
    parser = argparse.ArgumentParser(description="Cross-Book Evil Stress Eval Harness.")
    parser.add_argument("--id", help="Run a specific scenario ID.")
    parser.add_argument("--category", help="Run a specific scenario category.")
    parser.add_argument("--limit", type=int, help="Limit number of scenarios.")
    args = parser.parse_args()

    if not DATASET_PATH.is_file():
        print(f"Error: dataset not found at {DATASET_PATH}")
        sys.exit(1)

    scenarios = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(scenarios)} cross-book evil scenarios from {DATASET_PATH.name}")

    # Check server health
    try:
        req = urllib.request.Request("http://127.0.0.1:8000/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            health = json.loads(resp.read().decode("utf-8"))
            print(f"Connected to live server on :8000 (Ollama: {health.get('ollama')}, Books: {len(health.get('books', []))})")
    except Exception as e:
        print(f"Error: Server on :8000 not reachable: {e}")
        sys.exit(1)

    if args.id:
        scenarios = [s for s in scenarios if s["id"] == args.id]
    if args.category:
        scenarios = [s for s in scenarios if s.get("category") == args.category]
    if args.limit:
        scenarios = scenarios[:args.limit]

    print(f"Running {len(scenarios)} scenarios...")
    print("=" * 90)

    category_stats = {}
    total_passed = 0
    all_results = []

    for i, scen in enumerate(scenarios, 1):
        scen_id = scen["id"]
        cat = scen["category"]
        name = scen["name"]
        print(f"\n[{i:02d}/{len(scenarios):02d}] {scen_id} [{cat}]: {name}")
        res = run_scenario(scen)
        all_results.append(res)

        if cat not in category_stats:
            category_stats[cat] = {"pass": 0, "fail": 0}

        if res["passed"]:
            total_passed += 1
            category_stats[cat]["pass"] += 1
            print(f"  -> RESULT: PASS (all {len(res['turns'])} turns clean)")
        else:
            category_stats[cat]["fail"] += 1
            print("  -> RESULT: FAIL")
            for t in res["turns"]:
                if not t["passed"]:
                    print(f"     Turn {t['turn']} ({t['action']} '{t['question'][:35]}'):")
                    for r in t["reasons"]:
                        print(f"       - {r}")
                    ans_lines = [l for l in (t['response'].get('answer') or '').splitlines() if l.strip()]
                    if ans_lines:
                        print(f"         Answer: {ans_lines[0][:80]}")
                        if len(ans_lines) > 1:
                            print(f"         Gloss:  {ans_lines[1][:80]}")

    print("\n" + "=" * 90)
    print("CROSS-BOOK EVIL STRESS EVALUATION REPORT (2026-10-18)")
    print("=" * 90)
    total_scenarios = len(scenarios)
    pass_pct = (total_passed / total_scenarios * 100) if total_scenarios else 0.0
    fail_pct = 100.0 - pass_pct
    print(f"Overall Scenario Pass Rate: {total_passed}/{total_scenarios} ({pass_pct:.1f}%)")
    print(f"Overall Failure Rate:       {total_scenarios - total_passed}/{total_scenarios} ({fail_pct:.1f}%)")
    print("-" * 90)
    print("Category Breakdown:")
    for c, stats in sorted(category_stats.items()):
        c_tot = stats["pass"] + stats["fail"]
        c_pass_pct = (stats["pass"] / c_tot * 100) if c_tot else 0.0
        c_fail_pct = 100.0 - c_pass_pct
        print(f"  {c:<32}: {stats['pass']:>2}/{c_tot:<2} ({c_pass_pct:>5.1f}% pass | {c_fail_pct:>5.1f}% fail)")

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    evidence_path = EVIDENCE_DIR / "crossbook-eval-2026-10-18.json"
    evidence_path.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
    print(f"\nSaved detailed run evidence to {evidence_path}")


if __name__ == "__main__":
    main()
