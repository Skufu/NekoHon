"""Forced-keyword probe: can the decision model write a reaching keyword query?

The agentic loop's measured failure (artifacts/reports/multihop-report.md) is decision
policy, not tool reach: it chose `semantic` in 26/26 decisions while
hand-written keyword queries reach every missed chunk at rank 1-5. This probe
asks the narrower follow-up: after one semantic step (the loop's default
opener), if the next step is FORCED to keyword, can the model itself write a
query that reaches the chunk dense search missed?

Read-only over data/index.json; one live decision call per question. Ground
truth from the multihop set. Single forced step, single sample, temperature 0.

Run: python artifacts/probes/multihop-forced-keyword.py
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "probes"))

import agentic
from answer import ollama_generate
from prompt import ANSWER_MODEL
from retrieve import INDEX, load_index

FORCE = (
    "The next step must use the keyword tool. Reply with exactly two lines: "
    "line 1: keyword\nline 2: the search query."
)

# (question from artifacts/evidence/multihop/multihop-results.json, chunks single-shot missed)
CASES = [
    (
        "What is change data capture, and which database mechanism does the "
        "book say it relies on?",
        ["ch05-018", "ch02-023"],
    ),
    (
        "What does the book say data engineers must do about personally "
        "identifiable information during transformation, and in access control?",
        ["ch10-011"],
    ),
    (
        "What is master data management, and how does the book connect it to "
        "data governance?",
        ["ch02-013"],
    ),
    (
        "What questions does the book suggest asking before choosing streaming "
        "ingestion, and what does it say streaming ingestion preserves about data?",
        ["ch07-007", "ch02-020"],
    ),
]


def main():
    index = load_index(INDEX)
    tools = agentic.build_tools()
    state = {}
    print(f"answer model {ANSWER_MODEL} | index {len(index['chunks'])} chunks")
    for question, targets in CASES:
        first = tools["semantic"].search(question, index, state)
        attempts = [{
            "step": 1,
            "tool": "semantic",
            "query": question,
            "hits": first,
            "new": [hit["chunk_id"] for hit in first],
        }]
        user = FORCE + "\n\n" + agentic.decide_user_message(question, attempts)
        reply = ollama_generate(agentic.DECIDE_SYSTEM, user, ANSWER_MODEL)
        decision = agentic.parse_decision(reply)
        query = decision.get("query") or ""
        if not query:
            lines = [line.strip() for line in (reply or "").splitlines() if line.strip()]
            query = lines[1] if len(lines) > 1 else ""
        hits = tools["keyword"].search(query, index, state) if query else []
        ranks = {hit["chunk_id"]: position + 1 for position, hit in enumerate(hits)}
        print("=" * 72)
        print(f"Q: {question}")
        print(f"  semantic top-5: {[h['chunk_id'] for h in first[:5]]}")
        print(f"  model reply: {reply.strip()!r}")
        print(f"  forced keyword query: {query!r}")
        print(f"  keyword top-10: {[h['chunk_id'] for h in hits]}")
        for target in targets:
            print(f"  target {target}: rank {ranks.get(target)}")


if __name__ == "__main__":
    main()
