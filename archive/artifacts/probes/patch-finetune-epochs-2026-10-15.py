"""One-shot: patch the finetune notebook for the epochs rule (2026-10-15).

External review point: when the dataset grows, a fixed 6 epochs silently
raises total gradient steps (328x6 = 1968 presentations was the x2d budget).
Cell 4 now derives epochs from the row count to hold that budget, and saves
per-epoch checkpoints in-session (the review's checkpoints-at-3/4 point,
without extra downloads). Cell 3's EXPECTED_X2D comment records the patch
procedure for the next data build.

Run: python artifacts/probes/patch-finetune-epochs-2026-10-15.py
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTEBOOK = HERE.parent / "reports" / "finetune-colab-2026-10-13.ipynb"


def main():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    cells = notebook["cells"]

    # Cell 3: EXPECTED_X2D comment (patch procedure for the next build).
    src = cells[3]["source"]
    for index, line in enumerate(src):
        if "patched 2026-10-14 from stats-x2d" in line:
            src[index] = (
                "EXPECTED_X2D = 328  # patched 2026-10-14 (x2d: 274 answer + 54 refusal).\n"
                "                    # Next build (27B capture): patch this number + the RUNS\n"
                "                    # data filename from the new stats file. Do not patch the\n"
                "                    # epochs - cell 4 derives them from the row count to hold\n"
                "                    # total presentations near 1968 (328x6).\n"
            )
    cells[3]["source"] = src

    # Cell 4: derived epochs + checkpoint saving.
    src = cells[4]["source"]
    out = []
    for line in src:
        if "num_train_epochs=6," in line:
            out.append("            num_train_epochs=epochs,  # derived below: hold total presentations ~1968\n")
            continue
        if line.strip().startswith('print("rows over max_length:'):
            out.append(line)
            out.append("    # 2026-10-15 external review: hold total presentations near x2d's\n")
            out.append("    # 328x6 = 1968; a bigger dataset at fixed 6 epochs raises total\n")
            out.append("    # gradient steps ~50% (weight saturation -> loops).\n")
            out.append("    epochs = max(3, round(1968 / len(raw)))\n")
            out.append("    print(\"epochs:\", epochs, \"for\", len(raw), \"rows (total ~\", epochs * len(raw), \")\")\n")
            continue
        if 'output_dir="outputs",' in line:
            out.append(line)
            out.append("            save_strategy=\"epoch\",  # in-session checkpoints (not downloaded)\n")
            out.append("            save_total_limit=4,\n")
            continue
        out.append(line)
    cells[4]["source"] = out

    NOTEBOOK.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print("patched", NOTEBOOK)


if __name__ == "__main__":
    main()
