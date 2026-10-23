import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import answer as A

INDEX = json.loads((ROOT / "data" / "index.json").read_text(encoding="utf-8"))

TEST_MODELS = ["smallbook_x2g", "smallbook_x2g_mobile"]

QUERIES = [
    "Codd introduced the idea of what",
    "What is a watermark?",
    "What does CRUD stand for?",
    "What is the capital of France?",
    "DE Lifecycle",
    "ddr4 vs ddr5",
]

EXPLAIN_TARGET = {
    "selection": "essential characteristics",
    "chunk_id": "ch02-007",
    "heading": "Source Systems",
}


def main():
    report = {}
    for model in TEST_MODELS:
        print(f"\n==================== {model} ====================")
        report[model] = {}

        # 1. Ask & Respond mode on standard queries
        for q in QUERIES:
            print(f"\n--- Query: '{q}' ---")
            ask_res = A.ask(INDEX, q, model=model)
            resp_res = A.respond(INDEX, q, model=model)

            print(f"  [ask] refused={ask_res.get('refused')}, citations={len(ask_res.get('citations', []))}")
            print(f"        answer: {ask_res.get('answer', '')[:160]!r}")
            print(f"  [respond] refused={resp_res.get('refused')}, citations={len(resp_res.get('citations', []))}")
            print(f"            answer: {resp_res.get('answer', '')[:160]!r}")

            report[model][q] = {
                "ask": {
                    "refused": ask_res.get("refused"),
                    "citations": [c.get("chunk_id") for c in ask_res.get("citations", [])],
                    "answer": ask_res.get("answer"),
                },
                "respond": {
                    "refused": resp_res.get("refused"),
                    "citations": [c.get("chunk_id") for c in resp_res.get("citations", [])],
                    "answer": resp_res.get("answer"),
                },
            }

        # 2. Explain
        print(f"\n--- Explain on '{EXPLAIN_TARGET['selection']}' in {EXPLAIN_TARGET['chunk_id']} ---")
        exp_res = A.explain(
            INDEX,
            EXPLAIN_TARGET["selection"],
            model=model,
            chunk_id=EXPLAIN_TARGET["chunk_id"],
            heading=EXPLAIN_TARGET["heading"],
        )
        print(f"  [explain] refused={exp_res.get('refused')}, citations={len(exp_res.get('citations', []))}")
        print(f"            answer: {exp_res.get('answer', '')[:160]!r}")
        report[model]["explain"] = {
            "refused": exp_res.get("refused"),
            "citations": [c.get("chunk_id") for c in exp_res.get("citations", [])],
            "answer": exp_res.get("answer"),
        }

    out_file = ROOT / "artifacts" / "evidence" / "eval-x2g-gates-2026-10-16.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nSaved report to {out_file}")


if __name__ == "__main__":
    main()
