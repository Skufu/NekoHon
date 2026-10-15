"""One-shot: make the pre-gate print tolerate a missing `q` label (2026-10-15).

The uploaded capture file's recapture rows had q=None (builder read the wrong
meta nesting; fixed the same day and the file rebuilt). The pre-gate print
crashed on `row['q'][:38]` for those rows. The label is cosmetic; the print
now falls back to the row id. Idempotent.

Run: python artifacts/probes/patch-teacher-kit-2026-10-15c.py
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTEBOOK = HERE.parent / "reports" / "teacher-capture-colab-2026-10-15.ipynb"

OLD = """    print(f"{row['id']:14} q={row['q'][:38]!r:40} finish={finish} "
          f"~{len(content)//4:3d}tok {repr(content[:100])}")"""

NEW = """    label = (row.get("q") or row["id"])[:38]
    print(f"{row['id']:14} q={label!r:40} finish={finish} "
          f"~{len(content)//4:3d}tok {repr(content[:100])}")"""


def main():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    patched = 0
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        text = "".join(cell["source"])
        if OLD in text:
            cell["source"] = text.replace(OLD, NEW).splitlines(keepends=True)
            patched += 1
    assert patched == 1, f"expected 1 patched cell, got {patched}"
    NOTEBOOK.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print("patched", NOTEBOOK)


if __name__ == "__main__":
    main()
