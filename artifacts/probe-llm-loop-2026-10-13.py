"""Capped single-question draw probe: how often does a model's answer run
long (done_reason=length) instead of stopping?

The finetuned smallbook checkpoints can enter repetition loops on some
questions; this probe draws one battery question N times through the app's
seam with a num_predict cap, so a runaway still returns instead of hitting
the client timeout, and reports the loop count. Motivation, matrix, and the
decision it drove: artifacts/finetune-loop-eval-2026-10-13.md.

Run: python artifacts/probe-llm-loop-2026-10-13.py [model] [question] [cap] [options-json] [repeat]
Prints to stdout; redirect for a log. Writes nothing itself.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from prompt import SYSTEM
from retrieve import INDEX, load_index
import answer as A

model = sys.argv[1] if len(sys.argv) > 1 else "smallbook"
question = sys.argv[2] if len(sys.argv) > 2 else "What does CRUD stand for?"
cap = int(sys.argv[3]) if len(sys.argv) > 3 else 300
extra = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
repeat = int(sys.argv[5]) if len(sys.argv) > 5 else 1

index = load_index(INDEX)
context = A.retrieval_context(index, question)
user = A.user_message(context["asked"], context["passages"])

options = {"temperature": 0, "num_predict": cap}
options.update(extra)
payload = {
    "model": model,
    "stream": False,
    "think": False,
    "options": options,
    "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ],
}
print(f"model={model} cap={cap} options={options} repeat={repeat}")
print(f"asked={context['asked']!r}")

looped = 0
for draw in range(1, repeat + 1):
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=900) as response:
        body = json.loads(response.read().decode("utf-8"))
    seconds = time.monotonic() - started
    message = (body.get("message") or {}).get("content", "")
    looped += body.get("done_reason") == "length"
    print(
        f"draw {draw}: {seconds:5.1f}s chars={len(message):5} "
        f"done={body.get('done_reason')}"
    )
    if repeat == 1:
        print(repr(message[:1200]))
print(f"length-stops (loops): {looped}/{repeat}")
