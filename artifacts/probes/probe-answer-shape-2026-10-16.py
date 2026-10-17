"""Live answer-shape probe: the three owner findings, over HTTP.

Runs against a server on :8000 (whatever model it serves). Writes
artifacts/evidence/answer-shape/answer-shape-2026-10-16.{json,log}.
Not a gate.
"""

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "evidence" / "answer-shape"
URL = "http://127.0.0.1:8000/ask"
QUESTIONS = [
    ("monolith-vs", "Monolith Versus Modular"),
    ("ddr4-vs-ddr5", "ddr4 vs ddr5"),
    ("oss-factors", "What are the following factors to consider with a "
                    "community-managed OSS project"),
]


def post(question, timeout=180):
    payload = json.dumps({
        "book_id": "fde", "question": question,
        "selection": None, "mode": "answer",
    }).encode("utf-8")
    request = urllib.request.Request(
        URL, data=payload, headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body, round(time.perf_counter() - started, 2)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, question in QUESTIONS:
        body, seconds = post(question)
        rows.append({
            "id": name, "question": question,
            "refused": body.get("refused"),
            "answer": body.get("answer") or "",
            "seconds": seconds,
        })
        print("---", name, "refused", body.get("refused"), f"{seconds}s")
        print((body.get("answer") or "")[:400])
    (OUT / "answer-shape-2026-10-16.json").write_text(
        json.dumps({"rows": rows}, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    lines = ["# answer-shape live probe — three owner findings (2026-10-16)"]
    for row in rows:
        lines.append("")
        lines.append(f"## {row['id']} — {row['question']}")
        lines.append(f"refused: {row['refused']} | {row['seconds']}s")
        lines.append(row["answer"])
    (OUT / "answer-shape-2026-10-16.log").write_text(
        "\n".join(lines) + "\n", encoding="utf-8",
    )
    print("wrote", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
