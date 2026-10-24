"""Probe: can Ollama 0.40.3 suppress Qwen3.5 thinking through /api/chat?

Three request shapes, identical prompt. Records wall time, token counts,
whether reasoning arrives in `message.thinking`, and whether  thinking tags
leak into `message.content`. Writes JSON + log to
artifacts/evidence/qwen35-swap-2026-10-24/.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen3.5:2b-q4_K_M"
URL = "http://127.0.0.1:11434/api/chat"
EVIDENCE = Path(__file__).resolve().parents[2] / "artifacts" / "evidence" / "qwen35-swap-2026-10-24"

SYSTEM = (
    "You answer questions about a technical book. Quote the passage first, "
    "then explain it in one sentence. If the passage does not contain the answer, say so."
)
USER = "What is a data pipeline? Quote the passage."

VARIANTS = [
    ("default", {}),
    ("think_false", {"think": False}),
    ("template_kwarg", {"chat_template_kwargs": {"enable_thinking": False}}),
]


def call(extra):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER},
        ],
        "stream": False,
        "options": {"temperature": 0, "num_predict": 256},
    }
    payload.update(extra)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    start = time.time()
    with urllib.request.urlopen(req, timeout=300) as resp:
        return time.time() - start, json.load(resp)


def run(label, extra):
    elapsed, body = call(extra)
    msg = body.get("message") or {}
    content = msg.get("content") or ""
    thinking = msg.get("thinking") or ""
    return {
        "variant": label,
        "wall_sec": round(elapsed, 2),
        "content_chars": len(content),
        "thinking_chars": len(thinking),
        "tag_leak": "think>" in content.lower(),
        "eval_count": body.get("eval_count"),
        "prompt_eval_count": body.get("prompt_eval_count"),
        "eval_sec": round((body.get("eval_duration") or 0) / 1e9, 2),
        "done_reason": body.get("done_reason"),
        "content_head": content[:160].replace("\n", " "),
    }


def main():
    rows = []
    for label, extra in VARIANTS:
        try:
            rows.append(run(label, extra))
        except urllib.error.HTTPError as exc:
            rows.append({
                "variant": label,
                "http_error": exc.code,
                "body": exc.read().decode("utf-8", "replace")[:200],
            })
        except Exception as exc:  # transport failure is a result, report it verbatim
            rows.append({"variant": label, "error": f"{type(exc).__name__}: {exc}"})

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "probe-qwen35-think-2026-10-24.json").write_text(
        json.dumps({"model": MODEL, "ollama": "0.40.3", "rows": rows}, indent=2), encoding="utf-8"
    )
    lines = [f"{r['variant']:<16} {json.dumps({k: v for k, v in r.items() if k != 'variant'})}" for r in rows]
    (EVIDENCE / "probe-qwen35-think-2026-10-24.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
