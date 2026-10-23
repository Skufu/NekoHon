"""In-process ask bench: the battery's question lists against one model.

Same check the HTTP battery makes for the ask mode (pinned chunk cited, not
refused), run in-process so a candidate model can be measured without a
server swap. The key_fact regexes are skipped; the pin is the signal.

Run: python artifacts/probes/probe-small-ask-2026-10-13.py [--model smallbook]
Writes artifacts/evidence/probe-small-ask/probe-small-ask-2026-10-13.{json,log}.
"""

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
from retrieve import INDEX, load_index


def battery_lists():
    spec = importlib.util.spec_from_file_location(
        "step2_battery", ROOT / "artifacts" / "harnesses" / "step2-battery.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GOLDEN_PINS, module.TYPOS, module.PROBES, module.COHERENCE


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="smallbook")
    args = parser.parse_args()

    index = load_index(INDEX)
    golden, typos, probes, coherence = battery_lists()
    cases = []
    for question, pin in golden:
        cases.append(("golden", question, pin))
    for question, pin, _key in list(typos) + list(probes):
        cases.append(("typo/probe", question, pin))
    for question, pin, _pattern in coherence:
        cases.append(("coherence", question, pin))

    rows = []
    passed = 0
    for group, question, pin in cases:
        started = time.monotonic()
        body = A.ask(index, question, model=args.model)
        seconds = time.monotonic() - started
        cited = [c["chunk_id"] for c in body["citations"]]
        ok = (not body["refused"]) and pin in cited
        passed += ok
        # Progress line before the row is stored: if a later question dies
        # on the client timeout, the last printed line names it.
        print(
            f"[{len(rows) + 1}/{len(cases)}] {seconds:6.1f}s "
            f"{'PASS' if ok else 'FAIL'} {question[:48]}",
            flush=True,
        )
        rows.append({
            "group": group, "question": question, "pin": pin, "ok": ok,
            "refused": body["refused"], "cited": cited[:3],
            "first_line": body["answer"].split("\n", 1)[0][:160],
            "seconds": round(seconds, 2),
        })

    lines = [f"model {args.model}: {passed}/{len(cases)} pin-pass"]
    for row in rows:
        mark = "PASS" if row["ok"] else "FAIL"
        lines.append(
            f"{mark} [{row['group']:9}] {row['question'][:56]:56} "
            f"pin={row['pin']} cited={row['cited']} refused={row['refused']}"
        )
        if not row["ok"]:
            lines.append(f"     {row['first_line']}")
    log = "\n".join(lines)
    (ROOT / "artifacts" / "evidence" / "probe-small-ask" / "probe-small-ask-2026-10-13.log").write_text(log, encoding="utf-8")
    (ROOT / "artifacts" / "evidence" / "probe-small-ask" / "probe-small-ask-2026-10-13.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
