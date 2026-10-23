"""Export the teacher-probe prompt file for the Colab kit (2026-10-15).

Freezes, for a fixed 9-item probe list, the exact (system, user) message pair
the shipped answer seam would send (`answer.respond`) — captured locally with
a fake generator, so no model call happens here. The Colab notebook serves a
big teacher (Saluki / Qwen3.8-27B) and runs this file through the OpenAI wire;
the answers are compared against the 7B/x2d ceilings in the repo.

Why these items: `why does` (sealed suite, both students + 7B fail), `what
about` (7B fails, x2d passes), `how do` (7B passes; sanity), the `why's` /
`why is` kafka pair (7B ceiling), the `auto scanning` shorthand (false
refusal class), one order-flip pair (x2d's gap), and two format controls
(cited answer; exact refusal).

Run: python artifacts/probes/export-teacher-probe-2026-10-15.py
Writes: data/finetune/teacher-probe-2026-10-15.jsonl (gitignored).
Upload that file to Colab when the notebook's picker opens.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
from retrieve import INDEX, load_index

OUT = ROOT / "data" / "finetune" / "teacher-probe-2026-10-15.jsonl"

QUESTIONS = [
    ("why-does", "why does"),
    ("what-about", "what about"),
    ("how-do", "how do"),
    ("whys-kafka", "why's kafka so popular?"),
    ("why-is-kafka", "why is kafka so popular?"),
    ("auto-scanning", "what's auto scanning?"),
    ("column-vs-row", "column-oriented vs row-oriented"),
    ("watermark", "What is a watermark?"),
    ("france", "What is the capital of France?"),
]


def main():
    index = load_index(INDEX)
    rows = []
    for item_id, question in QUESTIONS:
        calls = []

        def fake(system, user, model=None, **kw):
            calls.append({"system": system, "user": user,
                          "prefill": kw.get("prefill", "")})
            return A.REFUSAL  # refusal: the retry never fires, one call each

        A.respond(index, question, generate_fn=fake, model="capture")
        if not calls:
            print(f"[{item_id}] NO GENERATE CALL — skipped")
            continue
        last = calls[-1]
        rows.append({
            "id": item_id,
            "q": question,
            "system": last["system"],
            "user": last["user"],
            "calls": len(calls),  # expected 1 (readings/plain paths would add)
        })
        print(f"[{item_id}] calls={len(calls)} "
              f"user_chars={len(last['user'])} system={last['system'][:40]!r}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                   encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(ROOT)} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
