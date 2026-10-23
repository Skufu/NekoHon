"""Build the ask-seam capture file for the 187 new forms (2026-10-15).

Why: the first capture mixed two seams. Recapture rows were re-used from the
old dataset, whose prompts are ask-shaped ("Copy one sentence from a passage.
Do not reword it." + the ask system prompt) — the 27B answered those
quote-first, 274/274. The new forms were built through `answer.respond`
(answer-shaped: "Answer the question directly, in your own words.") — the 27B
wrote prose with inline tags, 86/96 without any quote. Training targets must
be one consistent shape (quote-first + gloss): the `[Ch. ` retry prefill and
the old 328-row base both assume it.

This builder runs the same 187 v2 forms through `answer.ask` with a fake
generator (no model call) and freezes the exact (system, user) prompts — the
ask seam the recapture rows already used. Row ids stay `new-001..new-187` so
the results join back to the forms' expectations.

Run: python artifacts/probes/build-teacher-capture-ask-2026-10-15.py
Writes: data/finetune/teacher-capture-ask-2026-10-15.jsonl (gitignored).
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
from retrieve import INDEX, load_index

FORMS = ROOT / "data" / "finetune" / "new-forms-v2-2026-10-15.json"
OUT = ROOT / "data" / "finetune" / "teacher-capture-ask-2026-10-15.jsonl"


def main():
    index = load_index(INDEX)
    forms = json.loads(FORMS.read_text(encoding="utf-8"))
    rows, errors = [], []
    for i, form in enumerate(forms, 1):
        calls = []

        def fake(system, user, model=None, **kw):
            calls.append({"system": system, "user": user})
            return A.REFUSAL

        try:
            A.ask(index, form["question"], generate_fn=fake, model="capture")
        except Exception as exc:
            errors.append((form["question"], f"{type(exc).__name__}: {exc}"))
            continue
        if not calls:
            errors.append((form["question"], "no generate call captured"))
            continue
        last = calls[-1]
        rows.append({
            "id": f"new-{i:03d}",
            "part": "new-ask",
            "card": form.get("source_card"),
            "class": form.get("class"),
            "expect": form.get("expect"),
            "pin": form.get("pin"),
            "q": form["question"],
            "system": last["system"],
            "user": last["user"],
            "note": form.get("note"),
        })
    for q, e in errors:
        print(f"  ERROR {q!r}: {e}")
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                   encoding="utf-8")
    by_expect = {}
    for row in rows:
        by_expect[row["expect"]] = by_expect.get(row["expect"], 0) + 1
    print(f"total {len(rows)} rows -> {OUT.relative_to(ROOT)} | by expect: {by_expect}")
    ask_tail = "Copy one sentence from a passage"
    bad = [r["id"] for r in rows if ask_tail not in r["user"]]
    print("rows missing the ask reminder:", len(bad), bad[:5])
    quote_sys = [r["id"] for r in rows if "quote that passage" not in r["system"]]
    print("rows missing the ask system prompt:", len(quote_sys), quote_sys[:5])


if __name__ == "__main__":
    main()
