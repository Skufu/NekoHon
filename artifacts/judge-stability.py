"""Judge verdict flip-rate probe. Artifact, not engine.

Re-judges one stored eval-plain answer N times on a frozen prompt and reports
whether the verdict is stable. Motivated 2026-10-13: the wired-vs-probe
scorecard delta (6/10 vs 8/10) traced to single verdict flips on identical
answers, and a frozen-prompt probe then measured ['supported', 'supported',
'unsupported'] in three consecutive Muse calls at temperature 0 on the same
borderline item. Single-draw scorecard numbers carry that noise on borderline
items; run this before claiming a one-question A/B difference.

Run (cloud judge):
    JUDGE_BACKEND=openai JUDGE_WIRE=responses JUDGE_MODEL=muse-spark-1.3-contributor \\
    JUDGE_BASE_URL=https://opencode.ai/zen/go/v1 JUDGE_API_KEY_FILE=.judge-key \\
    python artifacts/judge-stability.py \\
        --file eval-plain-v6-openai-muse-spark-1-3-contributor.json \\
        --match ingestion --n 3

    --all judges every question in the file (per-question flip rate).

Run (local judge, offline): omit the env, the granite default is used.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import answer as A
import judge as J
from retrieve import INDEX, load_index


def main():
    parser = argparse.ArgumentParser(description="Judge verdict flip-rate probe.")
    parser.add_argument("--file", required=True, help="eval-plain JSON in artifacts/")
    parser.add_argument("--match", default="", help="question substring (single item)")
    parser.add_argument("--all", action="store_true", help="judge every question in the file")
    parser.add_argument("--variant", default="", help="variant name (default: first)")
    parser.add_argument("--n", type=int, default=3)
    args = parser.parse_args()

    rows = json.loads((HERE / args.file).read_text(encoding="utf-8"))
    if args.all:
        targets = rows
    else:
        targets = [r for r in rows if args.match in r["question"]]
        if not targets:
            raise SystemExit(f"no question matches {args.match!r} in {args.file}")
    index = load_index(INDEX)
    print(f"judge {J.judge_name()} | file {args.file} | n {args.n}")
    for row in targets:
        variant = args.variant or next(iter(row["variants"]))
        passages_text = "\n\n".join(
            hit.get("text") or ""
            for hit in A.retrieval_context(index, row["question"])["passages"]
        )
        verdicts = [
            J.judge_book_fidelity(
                row["question"], passages_text, row["variants"][variant]["answer"]
            )
            for _ in range(args.n)
        ]
        supported = sum(1 for v in verdicts if v == "supported")
        print(
            f"{row['question'][:44]:46} {variant:10}"
            f" supported {supported}/{args.n} {verdicts}"
        )


if __name__ == "__main__":
    main()
