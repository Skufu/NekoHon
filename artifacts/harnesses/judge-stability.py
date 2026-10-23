import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from engine.answering import answer as A
import judge as J
from engine.retrieval.retrieve import INDEX, load_index


def main():
    parser = argparse.ArgumentParser(description="Judge verdict flip-rate probe.")
    parser.add_argument("--file", required=True, help="eval-plain JSON in artifacts/")
    parser.add_argument("--match", default="", help="question substring (single item)")
    parser.add_argument("--all", action="store_true", help="judge every question in the file")
    parser.add_argument("--variant", default="", help="variant name (default: first)")
    parser.add_argument("--n", type=int, default=3)
    args = parser.parse_args()

    target = Path(args.file)
    if not target.is_absolute():
        target = ROOT / "artifacts" / args.file
    if not target.is_file():
        hits = sorted((ROOT / "archive" / "artifacts" / "evidence").glob(f"*/{Path(args.file).name}"))
        if hits:
            target = hits[0]
    rows = json.loads(target.read_text(encoding="utf-8"))
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
