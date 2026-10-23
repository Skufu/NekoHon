"""One-shot: point the finetune notebook at the x2e build (2026-10-15).

EXPECTED_X2D=328 -> EXPECTED_X2E=475 (from stats-x2e: 395 cited + 81 refusal),
RUNS[0] -> export smallbook_x2e / data quote-refuse-2026-10-15.train-x2e.jsonl,
upload hint + assert message updated, title bumped to v8. Epochs stay derived
(round(1968/475) = 4). Idempotent.

Run: python artifacts/probes/patch-finetune-x2e-2026-10-15.py
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTEBOOK = HERE.parent / "reports" / "finetune-colab-2026-10-13.ipynb"

OLD_BLOCK = """EXPECTED_X2D = 328  # patched 2026-10-14 (x2d: 274 answer + 54 refusal).
                    # Next build (27B capture): patch this number + the RUNS
                    # data filename from the new stats file. Do not patch the
                    # epochs - cell 4 derives them from the row count to hold
                    # total presentations near 1968 (328x6).
assert EXPECTED_X2D, "EXPECTED_X2D not patched from stats-x2d — do not run\""""

NEW_BLOCK = """EXPECTED_X2E = 475  # patched 2026-10-15 from stats-x2e (395 cited + 81 refusal).
                    # Do not patch the epochs - cell 4 derives them from the
                    # row count to hold total presentations near 1968.
assert EXPECTED_X2E, "EXPECTED_X2E not patched from stats-x2e — do not run\""""

OLD_RUN = """     "export": "smallbook_x2d",
     "data": "quote-refuse-2026-10-13.train-x2d.jsonl",
     "expected": EXPECTED_X2D,
     "seed": 3407},  # x2d single slot (2026-10-14): form-augmented set, one run"""

NEW_RUN = """     "export": "smallbook_x2e",
     "data": "quote-refuse-2026-10-15.train-x2e.jsonl",
     "expected": EXPECTED_X2E,
     "seed": 3407},  # x2e single slot (2026-10-15): 27B-captured set, one run"""

REPLACEMENTS = [
    (OLD_BLOCK, NEW_BLOCK),
    (OLD_RUN, NEW_RUN),
    ("files.upload()  # select quote-refuse-2026-10-13.train-x2d.jsonl",
     "files.upload()  # select quote-refuse-2026-10-15.train-x2e.jsonl"),
    ('"upload quote-refuse-2026-10-13.train-x2d.jsonl"',
     '"upload quote-refuse-2026-10-15.train-x2e.jsonl"'),
    ("# Small-book quote-or-refuse — finetune (2026-10-13, v7 — x2d)",
     "# Small-book quote-or-refuse — finetune (2026-10-13, v8 — x2e)"),
    ("One session trains **one candidate** (Qwen2.5-3B base, x2d; pre-registration:\n`x2d-plan-2026-10-14.md`). When the picker opens, upload exactly one file:\n`quote-refuse-2026-10-13.train-x2d.jsonl`.",
     "One session trains **one candidate** (Qwen2.5-3B base, x2e; pre-registration:\n`x2e-plan-2026-10-15.md`, build: `x2e-build-2026-10-15.md`). When the picker\nopens, upload exactly one file: `quote-refuse-2026-10-15.train-x2e.jsonl`."),
    ("EXPECTED_X2D (patched from\n`data/finetune/quote-refuse-2026-10-13.stats-x2d.json` after the build);",
     "EXPECTED_X2E (patched from\n`data/finetune/quote-refuse-2026-10-15.stats-x2e.json` after the build);"),
    ("Training is epoch-based (6 epochs) so per-row exposure\nmatches x2's level; the dataset size changed.",
     "Training is epoch-based, derived in cell 4 to hold ~1968 presentations\n(4 epochs at 475 rows)."),
    ("must\nmatch EXPECTED_X2D.", "must\nmatch EXPECTED_X2E."),
]


def main():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    changed = 0
    for cell in notebook["cells"]:
        text = "".join(cell["source"])
        original = text
        for old, new in REPLACEMENTS:
            text = text.replace(old, new)
        if text != original:
            cell["source"] = text.splitlines(keepends=True)
            changed += 1
    NOTEBOOK.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    joined = "".join("".join(cell["source"]) for cell in notebook["cells"])
    assert "EXPECTED_X2E = 475" in joined
    assert "quote-refuse-2026-10-13.train-x2d.jsonl" not in joined, \
        "the old data file is still referenced"
    assert "EXPECTED_X2D" not in joined, "the old variable is still referenced"
    print("patched", NOTEBOOK, "cells changed:", changed)


if __name__ == "__main__":
    main()
