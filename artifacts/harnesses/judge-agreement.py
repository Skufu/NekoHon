"""Agreement between two judged eval runs. Artifact, not engine.

The calibration step for judges: replay the same answers under a second
judge and compare verdicts. A local judge is good enough for the routine
loop only where it agrees with the stronger judge; disagreements are printed
for inspection, never averaged away.

Run: python artifacts/harnesses/judge-agreement.py eval-v1 eval-v1-openai-<model>
Writes artifacts/runs/judge-agreement/judge-agreement-<a>-vs-<b>.log.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def load(label):
    return json.loads(
        (ROOT / "archive" / "artifacts" / "evidence" / "eval-v1" / f"{label}.json").read_text(encoding="utf-8")
    )


def relevance_map(rows):
    table = {}
    for row in rows:
        for item in row.get("relevance") or []:
            table[(row["question"], item["chunk_id"])] = item["verdict"]
    return table


def key_map(rows):
    return {
        row["question"]: row["key_fact_judge"]
        for row in rows
        if row.get("key_fact_judge")
    }


def section(lines, title, table_a, table_b, name_a, name_b):
    shared = sorted(set(table_a) & set(table_b))
    agree = [key for key in shared if table_a[key] == table_b[key]]
    disagree = [key for key in shared if table_a[key] != table_b[key]]
    pct = round(100 * len(agree) / len(shared), 1) if shared else None
    lines.append(
        f"# {title}: {len(agree)}/{len(shared)} agree ({pct}%)"
        f" | disagreements {len(disagree)}"
    )
    for key in disagree:
        shown = " | ".join(str(part) for part in key)
        lines.append(f"- {shown}: {name_a}={table_a[key]} {name_b}={table_b[key]}")


def main():
    label_a, label_b = sys.argv[1], sys.argv[2]
    rows_a, rows_b = load(label_a), load(label_b)
    name_a = next((row.get("judge") for row in rows_a if row.get("judge")), "unknown")
    name_b = next((row.get("judge") for row in rows_b if row.get("judge")), "unknown")

    lines = [f"# judge agreement — {label_a} ({name_a}) vs {label_b} ({name_b})"]
    section(lines, "relevance", relevance_map(rows_a), relevance_map(rows_b), name_a, name_b)
    section(lines, "key facts", key_map(rows_a), key_map(rows_b), name_a, name_b)
    lines.append("")
    lines.append(
        "# zero shared rows means the two runs judged different items; check the labels."
    )

    log = ROOT / "artifacts" / "runs" / "judge-agreement" / f"judge-agreement-{label_a}-vs-{label_b}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:4]))
    print("wrote", log.name)


if __name__ == "__main__":
    main()
