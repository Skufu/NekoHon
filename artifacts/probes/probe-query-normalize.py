"""Does stripping trailing punctuation change ask mode's behavior? Every
battery question (golden, typos, probes, coherence) asked raw and stripped,
same model, same code. Tracks: pin chunk, refusal, and whether the quote
changed at all.

Run: python artifacts/probes/probe-query-normalize.py
Writes artifacts/evidence/probe-query-normalize/probe-query-normalize.{json,log}.
"""

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "probes"))

EVIDENCE = ROOT / "artifacts" / "evidence" / "probe-query-normalize"
HARNESSES = ROOT / "artifacts" / "harnesses"

import answer as A
from retrieve import INDEX, load_index

EXTRA = [
    ("What is nonrelational database", "ch05-032"),
    ("What is nonrelational database?", "ch05-032"),
]
REFUSAL_QUESTION = "What is the capital of France?"


def battery_lists():
    spec = importlib.util.spec_from_file_location(
        "step2_battery", HARNESSES / "step2-battery.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GOLDEN_PINS, module.TYPOS, module.PROBES, module.COHERENCE


def strip_trailing(question):
    return question.rstrip("?.! ").strip()


def body_of(body):
    first = body["citations"][0] if body["citations"] else {}
    return {
        "refused": body["refused"],
        "chunk": first.get("chunk_id"),
        "quote": (first.get("quote") or "")[:80],
    }


def main():
    index = load_index(INDEX)
    golden, typos, probes, coherence = battery_lists()
    cases = []
    for question, chunk_id in golden:
        cases.append({"question": question, "expect": chunk_id})
    for question, chunk_id, _key in list(typos) + list(probes):
        cases.append({"question": question, "expect": chunk_id})
    for question, chunk_id, _pattern in coherence:
        cases.append({"question": question, "expect": chunk_id})
    for question, chunk_id in EXTRA:
        cases.append({"question": question, "expect": chunk_id})

    records = []
    lines = []
    pin_flips = []
    quote_changes = 0
    for case in cases:
        question = case["question"]
        stripped = strip_trailing(question)
        raw = body_of(A.ask(index, question))
        alt = body_of(A.ask(index, stripped)) if stripped != question else raw
        raw_ok = raw["chunk"] == case["expect"] and not raw["refused"]
        alt_ok = alt["chunk"] == case["expect"] and not alt["refused"]
        changed = (raw["chunk"], raw["quote"]) != (alt["chunk"], alt["quote"])
        if changed:
            quote_changes += 1
        if raw_ok != alt_ok:
            pin_flips.append(question)
        records.append({**case, "raw": raw, "stripped": alt,
                        "raw_ok": raw_ok, "alt_ok": alt_ok, "changed": changed})
        lines.append(
            f"{'ok ' if raw_ok else 'KO '}/{'ok ' if alt_ok else 'KO '}"
            f"{' changed' if changed else '        '} {question[:58]:58} "
            f"raw={raw['chunk']} stripped={alt['chunk']}"
        )

    refusal = body_of(A.ask(index, REFUSAL_QUESTION))
    lines.append("")
    lines.append(f"quote changes: {quote_changes} of {len(cases)}")
    lines.append(f"pin flips raw-vs-stripped: {len(pin_flips)} {pin_flips}")
    lines.append(f"France refusal intact: {refusal['refused']}")

    log = "\n".join(lines)
    (EVIDENCE / "probe-query-normalize.log").write_text(log, encoding="utf-8")
    (EVIDENCE / "probe-query-normalize.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
