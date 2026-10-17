"""One live ask against a running engine. Writes the JSON. No suite."""

import json
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent


def post(payload):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:8000/ask",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    try:
        urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2)
    except Exception as exc:
        print(f"engine down: {exc}")
        return
    cases = {
        "out-of-book": {"mode": "ask", "question": "What is the capital of Mars?"},
        "in-book": {"mode": "answer", "question": "What is a watermark?"},
    }
    for name, payload in cases.items():
        body = post(payload)
        path = OUT / f"live-{name}.json"
        path.write_text(json.dumps(body, indent=2), encoding="utf-8")
        print(name, "refused", body.get("refused"), "citations", len(body.get("citations") or []))
        print("answer", (body.get("answer") or "")[:180])


if __name__ == "__main__":
    main()
