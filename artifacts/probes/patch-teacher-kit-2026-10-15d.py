"""One-shot: add the 'if something looks wrong' block to the kit's cell 0.

Points at the session runbook (reports/colab-capture-session-2026-10-15.md)
so the next session's operator reads the failure symptoms before the capture.
Idempotent.

Run: python artifacts/probes/patch-teacher-kit-2026-10-15d.py
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTEBOOK = HERE.parent / "reports" / "teacher-capture-colab-2026-10-15.ipynb"

ANCHOR = "local-only; the shipped student stays a stock GGUF).\n"

BLOCK = """
**If something looks wrong** (full runbook:
`artifacts/reports/colab-capture-session-2026-10-15.md`):
- GPU RAM stays 0.0 after serve, or rows take ~1 min -> the CUDA plugin fell
  back to CPU; stop and check `LD_LIBRARY_PATH` carries `/usr/lib64-nvidia`.
- `couldn't bind` / 404s -> something else holds the port (8080 is occupied
  in this VM; we serve on 8000).
- Upload-widget error after a reconnect -> re-run the cell; if the files are
  already in `/content`, comment `_files.upload()` out first. Colab re-uploads
  land as `name (1).jsonl` while the cell keeps reading the original path.
"""


def main():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    cell = notebook["cells"][0]
    assert cell["cell_type"] == "markdown"
    source = cell["source"]
    assert not any("If something looks wrong" in line for line in source), \
        "already patched"
    for index, line in enumerate(source):
        if line == ANCHOR:
            source[index] = line + BLOCK
            break
    else:
        raise SystemExit("anchor line not found")
    cell["source"] = source
    NOTEBOOK.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print("patched", NOTEBOOK)


if __name__ == "__main__":
    main()
