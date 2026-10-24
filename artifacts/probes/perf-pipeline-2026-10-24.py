"""End-to-end pipeline cost per mode, for one answer model.

Separates retrieval from generation and covers the three generation paths the
server exposes: ask (quote first), answer (free prose, grounded), explain
(highlight). Quiz is not measured here because no harness scores it yet.

Run: python artifacts/probes/perf-pipeline-2026-10-24.py <model>
Writes artifacts/evidence/perf/perf-pipeline-2026-10-24.model-<model>.json
"""

import json
import os
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import answer as A
from retrieve import INDEX, load_index

OUT = ROOT / "artifacts" / "evidence" / "perf"
QUESTIONS = [
    "What is a watermark?",
    "What is data ingestion?",
    "What does CRUD stand for?",
    "What is the difference between batch and streaming?",
    "Where does storage sit in the data engineering lifecycle?",
    "How does data architecture relate to enterprise architecture?",
]
EXPLAIN = [
    {"selection": "Data maturity is the progression toward higher data utilization,", "chunk_id": "ch01-025", "heading": "Data Maturity and the Data Engineer"},
    {"selection": "Change data capture (CDC) is a method for extracting each change event", "chunk_id": "ch05-013", "heading": "Change Data Capture"},
    {"selection": "Storage is the cornerstone of the data engineering lifecycle", "chunk_id": "ch06-001", "heading": "Storage"},
    {"selection": "A source system is the origin of the data used in the data engineering lifecycle.", "chunk_id": "ch02-005", "heading": "Generation: Source Systems"},
]


def p(method, *args, **kwargs):
    started = time.perf_counter()
    result = method(*args, **kwargs)
    return result, round((time.perf_counter() - started) * 1000.0)


def resident(model):
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=3) as response:
            for entry in json.loads(response.read().decode("utf-8")).get("models", []):
                if entry.get("name", "").startswith(model.split(":")[0]):
                    return entry.get("size", 0)
    except Exception:
        return None
    return None


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ANSWER_MODEL") or "nekohon_q35_2b"
    index = load_index(INDEX)

    # Warm the model so the first measured call is not a load.
    A.ask(index, "What is a watermark?", model=model)

    rows = {"ask": [], "answer": [], "explain": [], "retrieval": []}
    for question in QUESTIONS:
        _, retrieval_ms = p(A.retrieval_context, index, question)
        _, ask_ms = p(A.ask, index, question, model=model)
        _, answer_ms = p(A.respond, index, question, model=model)
        rows["retrieval"].append(retrieval_ms)
        rows["ask"].append(ask_ms)
        rows["answer"].append(answer_ms)
    for item in EXPLAIN:
        _, explain_ms = p(
            A.explain, index, item["selection"],
            chunk_id=item["chunk_id"], heading=item["heading"], model=model,
        )
        rows["explain"].append(explain_ms)

    summary = {}
    for key, values in rows.items():
        summary[key] = {
            "mean_ms": round(statistics.mean(values), 1),
            "median_ms": round(statistics.median(values), 1),
            "min_ms": round(min(values), 1),
            "max_ms": round(max(values), 1),
            "n": len(values),
        }
    generation = {
        "ask": round(summary["ask"]["mean_ms"] - summary["retrieval"]["mean_ms"], 1),
        "answer": round(summary["answer"]["mean_ms"] - summary["retrieval"]["mean_ms"], 1),
        "explain": round(summary["explain"]["mean_ms"], 1),
    }

    print(f"model {model}")
    print(f"{'stage':22} {'mean':>8} {'median':>8} {'min':>8} {'max':>8}  n")
    for key in ("retrieval", "ask", "answer", "explain"):
        s = summary[key]
        print(f"{key:22} {s['mean_ms']:7.0f}ms {s['median_ms']:7.0f}ms "
              f"{s['min_ms']:7.0f}ms {s['max_ms']:7.0f}ms  {s['n']}")
    print(f"{'generation only (ask)':22} {generation['ask']:7.0f}ms  (ask minus retrieval)")
    print(f"{'generation only (answer)':22} {generation['answer']:7.0f}ms  (answer minus retrieval; may be 2 calls)")
    memory = resident(model)
    print(f"{'resident':22} {(memory or 0) / 2**20:7.0f} MiB")

    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": "2026-10-24",
        "model": model,
        "questions": QUESTIONS,
        "explain_items": EXPLAIN,
        "stages": summary,
        "generation_ms": generation,
        "resident_bytes": memory,
    }
    slug = model.replace("/", "_").replace(":", "_")
    (OUT / f"perf-pipeline-2026-10-24.model-{slug}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
