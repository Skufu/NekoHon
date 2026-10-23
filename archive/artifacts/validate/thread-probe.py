"""Two-turn probe. History sent on turn 2. Quotes checked against this turn's body only."""

import json
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent


def ask(question, history=None):
    payload = {"mode": "answer", "question": question}
    if history:
        payload["history"] = history
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:8000/ask",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    first = ask("What is a watermark?")
    history = [{
        "question": "What is a watermark?",
        "answer": (first.get("answer") or "")[:400],
    }]
    second = ask("what about that", history)
    OUT.joinpath("thread-turn1.json").write_text(json.dumps(first, indent=2), encoding="utf-8")
    OUT.joinpath("thread-turn2.json").write_text(json.dumps(second, indent=2), encoding="utf-8")
    print("turn1 refused", first.get("refused"), "cites", [c.get("chunk_id") for c in first.get("citations") or []])
    print("turn1", (first.get("answer") or "")[:160].replace("\n", " | "))
    print("turn2 refused", second.get("refused"), "cites", [c.get("chunk_id") for c in second.get("citations") or []])
    print("turn2", (second.get("answer") or "")[:200].replace("\n", " | "))
    prior = first.get("answer") or ""
    quotes = [c.get("quote") or "" for c in second.get("citations") or []]
    copied = [q for q in quotes if q and q in prior]
    print("turn2 quotes copied from turn1 answer:", len(copied))


if __name__ == "__main__":
    main()
