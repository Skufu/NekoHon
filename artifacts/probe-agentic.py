"""Live probe: the agentic tool loop over Ollama on five real questions.

Read-only over data/index.json. Uses the same localhost model as the answer
path (prompt.ANSWER_MODEL, temperature 0 via answer.ollama_generate). One
single-shot ask runs first as the latency reference; it also warms the model,
so the five agentic traces below it are warm.

Run: python artifacts/probe-agentic.py
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentic import TOOL_NAMES, agentic_search
from answer import ask as single_shot_ask
from answer import ollama_generate
from prompt import ANSWER_MODEL
from retrieve import search as dense_search

QUESTIONS = [
    "Codd introduced the idea of what",
    "what is an endpoint in streaming ingestion",
    "MAD data landscape",
    "What does CRUD stand for?",
    "dark matter data",
]

REFERENCE_QUESTION = "Codd introduced the idea of what"


def main():
    index_path = ROOT / "data" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    print(f"index {index_path.name}: {len(index['chunks'])} chunks, "
          f"embedder {index.get('embedder')}, answer model {ANSWER_MODEL}")
    print("tools: " + ", ".join(TOOL_NAMES))
    print()

    calls = {"n": 0}

    def counting_generate(system, user, model):
        calls["n"] += 1
        return ollama_generate(system, user, model)

    started = time.perf_counter()
    baseline = dense_search(index, REFERENCE_QUESTION, k=5)
    print(f"one dense search (retrieve.search, k=5): {time.perf_counter() - started:.1f}s, "
          f"{len(baseline)} hits")

    started = time.perf_counter()
    body = single_shot_ask(index, REFERENCE_QUESTION)
    seconds = time.perf_counter() - started
    flat = " ".join(body["answer"].split())
    print(f"single-shot reference (answer.ask on the first question): "
          f"{seconds:.1f}s, refused={body['refused']}, first 90 chars: {flat[:90]!r}")
    print()

    rows = []
    for question in QUESTIONS:
        calls["n"] = 0
        started = time.perf_counter()
        result = agentic_search(index, question, generate_fn=counting_generate)
        seconds = time.perf_counter() - started
        rows.append((question, seconds, calls["n"]))
        print("=" * 72)
        print(f"Q: {question}")
        for item in result["attempts"]:
            print(f'  step {item["step"]}  tool: {item["tool"]}  chosen by: {item["chosen_by"]}')
            print(f'    query: {item["query"]}')
            print(f'    model said: {item["reply"]}')
            if item["hits"]:
                for hit in item["hits"]:
                    print(f'      hit {hit["chunk_id"]}  ch{hit["chapter"]}  '
                          f'score {hit["score"]:.3f}')
            else:
                print("      hits: none")
            print(f'    new: {item["new"] if item["new"] else "none"}')
        ids = [hit["chunk_id"] for hit in result["passages"]]
        print(f'  merged passages: {len(result["passages"])} {ids}')
        print(f'  stopped: {result["stopped"]}  |  model calls: {calls["n"]}  '
              f'|  wall: {seconds:.1f}s')
    print("=" * 72)
    print("summary")
    for question, seconds, count in rows:
        print(f"  {seconds:5.1f}s  {count} decision call(s)  {question}")
    print(f"  total {sum(r[1] for r in rows):.1f}s, "
          f"{sum(r[2] for r in rows)} decision calls over {len(rows)} questions")


if __name__ == "__main__":
    main()
