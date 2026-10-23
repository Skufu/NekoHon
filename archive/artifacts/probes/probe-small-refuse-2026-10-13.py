"""Small-model refusal canary: the bench file's two refusal targets.

The pin battery cannot see refusals; this probe asks the two exact-refusal
questions from `data/finetune/quote-refuse-2026-10-13.bench.jsonl` through
the shipped seam and demands the exact sentence, run in-process so a
candidate model is measured without a server swap.

Run: python artifacts/probes/probe-small-refuse-2026-10-13.py [--model smallbook]
Writes artifacts/evidence/probe-small-refuse/probe-small-refuse-2026-10-13.{json,log}.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
from retrieve import INDEX, load_index

CASES = [
    ("france", "What is the capital of France?"),
    ("iops", "what does iops mean"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="smallbook")
    args = parser.parse_args()

    index = load_index(INDEX)
    rows = []
    passed = 0
    for name, question in CASES:
        body = A.ask(index, question, model=args.model)
        exact = body["refused"] and body["answer"].strip() == A.REFUSAL
        passed += exact
        rows.append({
            "case": name,
            "question": question,
            "exact": exact,
            "refused": body["refused"],
            "cited": [c["chunk_id"] for c in body["citations"]][:3],
            "first_line": body["answer"].split("\n", 1)[0][:160],
        })

    lines = [f"model {args.model}: {passed}/{len(CASES)} exact refusals"]
    for row in rows:
        mark = "PASS" if row["exact"] else "FAIL"
        lines.append(
            f"{mark} [{row['case']:6}] refused={row['refused']} "
            f"cited={row['cited']}"
        )
        lines.append(f"     {row['first_line']}")
    log = "\n".join(lines)
    (ROOT / "artifacts" / "evidence" / "probe-small-refuse" / "probe-small-refuse-2026-10-13.log").write_text(log, encoding="utf-8")
    (ROOT / "artifacts" / "evidence" / "probe-small-refuse" / "probe-small-refuse-2026-10-13.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
