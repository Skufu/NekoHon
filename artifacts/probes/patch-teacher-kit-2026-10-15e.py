"""One-shot: copy the weights to local disk instead of symlinking from Drive.

Measured 2026-10-15: with a symlink into /content/drive, llama-server mmaps the
16 GB GGUF through the Drive FUSE mount — the load took 7+ minutes (GPU RAM
stayed 0.4 GB) and inference can touch Drive again after page eviction. One
local copy per session (~2-5 min) buys fast loads and no Drive I/O during the
capture. Idempotent.

Run: python artifacts/probes/patch-teacher-kit-2026-10-15e.py
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTEBOOK = HERE.parent / "reports" / "teacher-capture-colab-2026-10-15.ipynb"

OLD = """if CACHE != "/content/models" and not os.path.isfile(f"/content/models/{FN}"):
    os.symlink(f"{CACHE}/{FN}", f"/content/models/{FN}")"""

NEW = """if CACHE != "/content/models" and not os.path.isfile(f"/content/models/{FN}"):
    # 2026-10-15: copy, do not symlink. A symlink makes llama-server mmap the
    # 16 GB through the Drive FUSE mount (load took 7+ min, GPU RAM stayed
    # 0.4 GB) and inference can touch Drive again after page eviction. One
    # local copy (~2-5 min) buys fast loads and no Drive I/O during capture.
    import shutil
    print("copying weights to local disk (one-time, ~2-5 min)...")
    shutil.copy(f"{CACHE}/{FN}", f"/content/models/{FN}")"""


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
