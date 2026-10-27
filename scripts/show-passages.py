"""Show what retrieval hands the model: the passages, their ranks, and why.

    python scripts/show-passages.py "what is an api" --book fde
    python scripts/show-passages.py "API" --book ddia --mode explain --heading "Human Errors"

Read-only. Prints the raw `search` order and the `retrieval_context` order
(which can differ: pins, history seeding, sentence alignment).
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import answer as A  # noqa: E402
from retrieve import load_index, search  # noqa: E402

INDEXES = {
    "fde": ROOT / "data" / "index.json",
    "quantization": ROOT / "data" / "index.quantization.json",
    "ddia": ROOT / "data" / "index.ddia.json",
}


def preview(text, width=140):
    return " ".join((text or "").split())[:width]


def main():
    parser = argparse.ArgumentParser(description="Show retrieved passages for a question.")
    parser.add_argument("question")
    parser.add_argument("--book", default="fde", choices=sorted(INDEXES))
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--mode", default="ask", choices=["ask", "explain", "answer"])
    parser.add_argument("--selection", default="")
    parser.add_argument("--heading", default="")
    parser.add_argument("--chunk-id", default="")
    args = parser.parse_args()

    index = load_index(INDEXES[args.book])
    query = A.highlight_query(args.selection, args.heading) if args.mode == "explain" else args.question
    print(f"book={args.book} mode={args.mode} query={query!r}\n")

    print(f"raw search, top {args.k}")
    for rank, hit in enumerate(search(index, query, k=args.k), 1):
        print(f"  {rank}. {hit['chunk_id']:<16} {hit.get('score', 0):.3f}  {hit.get('heading', '')[:36]:<36} {preview(hit['text'])}")

    context = A.retrieval_context(
        index, query,
        pin_chunk=(args.chunk_id or None),
        history=None,
        selection=args.selection,
    )
    print(f"\npassages the model actually sees ({len(context['passages'])})")
    for rank, hit in enumerate(context["passages"], 1):
        print(f"  {rank}. {hit['chunk_id']:<16} {hit.get('score', 0):.3f}  {hit.get('heading', '')[:36]:<36} {preview(hit['text'])}")


if __name__ == "__main__":
    main()
