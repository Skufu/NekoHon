"""Assemble the 27B teacher capture file for the next build (2026-10-15).

Part B — recapture: every existing x2d train row's (system, user) pair is
re-used verbatim (same seam prompts the 7B was captured with) so the bigger
teacher can regenerate the whole base at higher quality.

Part A — new forms: `data/finetune/new-forms-v2-2026-10-15.json` (441
candidates → 187 accepted, built by `gen-new-forms-v2-2026-10-15.py`) is run
through the shipped answer seam with a fake generator, capturing the exact
(system, user) prompts — no model call happens here (the fake returns the
refusal, so the retry never fires).

History: v1 of the capture file was built from `new-forms-2026-10-15.json`
(227 forms) on 2026-10-15 morning; an external review measured that 120+ of
those forms concentrated on 7 book passages, so v2 cut the deficit-card
tails (max 3 gold-pinned forms each) and spent the budget on bare topics,
order flips, and causal shapes. This builder now uses the v2 file:
328 recaptures + 187 new = 515 rows.

Run: python artifacts/probes/build-teacher-capture-2026-10-15.py
Writes: data/finetune/teacher-capture-2026-10-15.jsonl (gitignored).
Upload that file to Colab (teacher-capture-colab notebook, cell 6).
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
from retrieve import INDEX, load_index

TRAIN = ROOT / "data" / "finetune" / "quote-refuse-2026-10-13.train-x2d.jsonl"
FORMS = ROOT / "data" / "finetune" / "new-forms-v2-2026-10-15.json"
OUT = ROOT / "data" / "finetune" / "teacher-capture-2026-10-15.jsonl"


def part_b():
    rows = []
    for i, line in enumerate(TRAIN.read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(line)
        meta = row.get("meta", {}).get("meta", {})
        messages = row["messages"]
        target = messages[2]["content"].strip()
        rows.append({
            "id": f"rec-{i:03d}",
            "part": "recapture",
            "card": meta.get("question"),
            "class": "recapture",
            "expect": "refusal" if target.startswith("Not in this book.") else "cited",
            "pin": meta.get("pin"),
            "q": meta.get("asked") or meta.get("question"),
            "system": messages[0]["content"],
            "user": messages[1]["content"],
            "origin": meta.get("source"),
        })
    return rows


def part_a(index):
    forms = json.loads(FORMS.read_text(encoding="utf-8"))
    rows, errors = [], []
    for i, form in enumerate(forms, 1):
        calls = []

        def fake(system, user, model=None, **kw):
            calls.append({"system": system, "user": user})
            return A.REFUSAL

        try:
            A.respond(index, form["question"], generate_fn=fake, model="capture")
        except Exception as exc:
            errors.append((form["question"], f"{type(exc).__name__}: {exc}"))
            continue
        if not calls:
            errors.append((form["question"], "no generate call captured"))
            continue
        last = calls[-1]
        rows.append({
            "id": f"new-{i:03d}",
            "part": "new",
            "card": form.get("source_card"),
            "class": form.get("class"),
            "expect": form.get("expect"),
            "pin": form.get("pin"),
            "q": form["question"],
            "system": last["system"],
            "user": last["user"],
            "note": form.get("note"),
        })
    return rows, errors


def main():
    index = load_index(INDEX)
    rows = part_b()
    print(f"part B (recapture): {len(rows)} rows "
          f"({sum(r['expect'] == 'refusal' for r in rows)} refusal)")
    new_rows, errors = part_a(index)
    print(f"part A (new forms): {len(new_rows)} rows "
          f"({sum(r['expect'] == 'refusal' for r in new_rows)} refusal)")
    for q, e in errors:
        print(f"  ERROR {q!r}: {e}")
    rows.extend(new_rows)

    seen = {}
    for row in rows:
        seen.setdefault(row["user"], []).append(row["id"])
    dupes = {u: ids for u, ids in seen.items() if len(ids) > 1}
    if dupes:
        print(f"WARNING: {len(dupes)} duplicated user prompts "
              f"(first: {list(dupes.values())[0]})")
    else:
        print("no duplicated capture prompt strings")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                   encoding="utf-8")
    by_expect = {}
    for row in rows:
        by_expect[row["expect"]] = by_expect.get(row["expect"], 0) + 1
    print(f"\ntotal {len(rows)} rows -> {OUT.relative_to(ROOT)}")
    print(f"by expect: {by_expect}")


if __name__ == "__main__":
    main()
