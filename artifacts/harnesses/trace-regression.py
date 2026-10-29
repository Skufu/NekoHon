"""Trace-derived interaction regression: reader interactions that must pass.

Each item is a real reader conversation taken from `runs/traces.jsonl` that
went wrong. The gate is the reader's contract, not chunk identity alone:
a covered question answers with a citation from the passage that carries the
asked-for content, and an out-of-book question refuses with the exact sentence.

Turns run in order against one conversation, so a follow-up inherits the real
answers of the turns before it. Only the last turn is graded.

Run:
  python artifacts/harnesses/trace-regression.py
  python artifacts/harnesses/trace-regression.py --model nekohon_q35_2b_x3_2e
  python artifacts/harnesses/trace-regression.py --only fde-early-2000s-repeat

Dataset: artifacts/datasets/trace-interaction-2026-10-29.jsonl
Report:  artifacts/runs/trace-regression-2026-10-29.json (gitignored)
"""

import json
import os
import re
import sys
import time
from pathlib import Path

os.environ.setdefault("OBSERVE", "0")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import answer as A  # noqa: E402
from prompt import ANSWER_MODEL, REFUSAL  # noqa: E402
from retrieve import load_index  # noqa: E402

DATASET = ROOT / "artifacts" / "datasets" / "trace-interaction-2026-10-29.jsonl"
OUT = ROOT / "artifacts" / "runs" / "trace-regression-2026-10-29.json"
BOOKS = ROOT / "data" / "books.json"


def load_items():
    with DATASET.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def index_paths():
    catalog = json.loads(BOOKS.read_text(encoding="utf-8"))
    return {b["book_id"]: ROOT / b["index_path"] for b in catalog}


def norm(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def run_turns(index, turns, model):
    history = []
    final = {}
    for turn in turns:
        result = A.respond(index, turn["question"], model=model, history=history or None)
        history.append({
            "question": turn["question"],
            "answer": (result.get("answer") or "").strip(),
        })
        final = result
    return final, history


def grade(item, result):
    """Return (passed, reasons). Contract-level, content-based."""
    answer_text = (result.get("answer") or "").strip()
    refused = bool(result.get("refused"))
    citations = result.get("citations") or []
    cited = [c.get("chunk_id") for c in citations]
    body = norm(answer_text)
    reasons = []

    if item["expect"] == "refused":
        if not refused:
            reasons.append("answered an out-of-book question")
        elif answer_text != REFUSAL:
            reasons.append(f"refusal is not the exact sentence: {answer_text[:40]!r}")
        return (not reasons), reasons

    if refused:
        reasons.append("refused a question the book covers")
    if not citations:
        reasons.append("no citation")
    elif not set(cited) & set(item["gold_chunk_ids"]):
        reasons.append(f"cited {cited} outside gold {item['gold_chunk_ids']}")
    missing = [t for t in item["must_include_terms"] if norm(t) not in body]
    if len(missing) == len(item["must_include_terms"]):
        reasons.append("none of the asked-for terms reached the answer")
    return (not reasons), reasons


def main(argv):
    only = None
    model = ANSWER_MODEL
    for i, arg in enumerate(argv):
        if arg == "--only":
            only = argv[i + 1]
        elif arg == "--model":
            model = argv[i + 1]

    items = [it for it in load_items() if only is None or it["id"] == only]
    indexes = index_paths()
    loaded = {}
    rows = []
    passed = 0

    print(f"trace regression · {len(items)} items · model {model}")
    for item in items:
        book = item["book_id"]
        if book not in loaded:
            loaded[book] = load_index(indexes[book])
        started = time.perf_counter()
        result, history = run_turns(loaded[book], item["turns"], model)
        ok, reasons = grade(item, result)
        passed += 1 if ok else 0
        cited = [c.get("chunk_id") for c in (result.get("citations") or [])]
        print(
            f"  {'PASS' if ok else 'FAIL'} {item['id']:<28} "
            f"{len(item['turns'])} turn(s) {time.perf_counter() - started:5.2f}s "
            f"cited={cited or '-'}"
        )
        if reasons:
            print(f"       {'; '.join(reasons)}")
        rows.append({
            "id": item["id"],
            "expect": item["expect"],
            "passed": ok,
            "reasons": reasons,
            "cited": cited,
            "answer": (result.get("answer") or "")[:600],
            "turns": history,
        })

    print(f"\n{passed} of {len(items)} pass, {len(items) - passed} fail")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "dataset": str(DATASET.relative_to(ROOT)),
        "model": model,
        "passed": passed,
        "total": len(items),
        "rows": rows,
    }, indent=1), encoding="utf-8")
    print(f"evidence: {OUT.relative_to(ROOT)}")
    return 0 if passed == len(items) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
