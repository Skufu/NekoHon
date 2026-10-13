"""Trial observation repro: the user's live fragment-pattern queries through
the shipped answer seam (`answer.respond`, the app's "answer" mode), per
model. The pattern under test: fragments ("what is", "Location"), greetings
("hey", "warrup"), bare topics ("DE Lifecycle"), comparisons with order
flips ("DDR5 vs ddr4" / "ddr4 vs ddr5"), trailing letters ("speed of ddr5s").

Run: python artifacts/probe-trial-queries-2026-10-14.py [model ...]
Default models: smallbook_x2, qwen2.5:7b
Writes artifacts/probe-trial-queries-2026-10-14.{json,log}.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import answer as A
from retrieve import INDEX, load_index

QUERIES = [
    "what is",
    "hey",
    "warrup",
    "Location",
    "Our Advice",
    "DE Lifecycle",
    "DDR5 vs ddr4",
    "ddr4 vs ddr5",
    "speed of ddr5",
    "speed of ddr5s",
]


def main():
    models = sys.argv[1:] or ["smallbook_x2", "qwen2.5:7b"]
    index = load_index(INDEX)
    rows = []
    lines = []
    for model in models:
        for question in QUERIES:
            body = A.respond(index, question, model=model)
            row = {
                "model": model,
                "q": question,
                "refused": body["refused"],
                "cited": [c["chunk_id"] for c in body["citations"]][:3],
                "answer": " ".join(body["answer"].split())[:400],
            }
            rows.append(row)
            line = (
                f"[{model}] {question!r} refused={row['refused']} "
                f"cited={row['cited']}"
            )
            lines.append(line)
            lines.append(f"    {row['answer'][:260]}")
            print(line, flush=True)
            print(f"    {row['answer'][:260]}", flush=True)
    (HERE / "probe-trial-queries-2026-10-14.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (HERE / "probe-trial-queries-2026-10-14.log").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print("wrote artifacts/probe-trial-queries-2026-10-14.{json,log}")


if __name__ == "__main__":
    main()
