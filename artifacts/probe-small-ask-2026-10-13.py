"""In-process ask bench: the battery's question lists against one model.

Same check the HTTP battery makes for the ask mode (pinned chunk cited, not
refused), run in-process so a candidate model can be measured without a
server swap. The key_fact regexes are skipped; the pin is the signal.

Run: python artifacts/probe-small-ask-2026-10-13.py [--model smallbook]
Writes artifacts/probe-small-ask-2026-10-13.{json,log}.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import answer as A
from retrieve import INDEX, load_index


def battery_lists():
    spec = importlib.util.spec_from_file_location(
        "step2_battery", HERE / "step2-battery.py"
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
        body = A.ask(index, question, model=args.model)
        cited = [c["chunk_id"] for c in body["citations"]]
        ok = (not body["refused"]) and pin in cited
        passed += ok
        rows.append({
            "group": group, "question": question, "pin": pin, "ok": ok,
            "refused": body["refused"], "cited": cited[:3],
            "first_line": body["answer"].split("\n", 1)[0][:160],
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
    (HERE / "probe-small-ask-2026-10-13.log").write_text(log, encoding="utf-8")
    (HERE / "probe-small-ask-2026-10-13.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
