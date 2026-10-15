"""One-shot: bake the two Colab runtime fixes into the capture kit (2026-10-15).

Measured live on the A100 session:
1. `libcuda.so.1` lives in /usr/lib64-nvidia in this Colab image and is not on
   the default loader path. Without it, libggml-cuda.so fails to dlopen, the
   CUDA plugin is silently dropped, and llama.cpp runs on CPU (measured:
   1.9 tok/s on an A100; GPU RAM stayed 0.0/40 GB). LD_LIBRARY_PATH must carry
   both /content/llama (bundled cudart 12.8/cublas) and /usr/lib64-nvidia.
2. Port 8080 is already bound in the Colab VM (bind error, then 404s from
   whatever answers); the server runs on 8000.

Run: python artifacts/probes/patch-teacher-kit-2026-10-15b.py
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTEBOOK = HERE.parent / "reports" / "teacher-capture-colab-2026-10-15.ipynb"

OLD_ENV = 'env = dict(os.environ, LD_LIBRARY_PATH="/content/llama")'
NEW_ENV = ('env = dict(os.environ,\n'
           '       LD_LIBRARY_PATH="/content/llama:/usr/lib64-nvidia")\n'
           '       # ^ /usr/lib64-nvidia holds libcuda.so.1 (the NVIDIA driver\n'
           '       #   lib) in this Colab image; without it the CUDA plugin fails\n'
           '       #   to dlopen and llama.cpp silently runs on CPU (measured\n'
           '       #   2026-10-15: 1.9 tok/s, GPU RAM 0.0/40 GB).')

NOTE = (
    "# Colab quirks, measured 2026-10-15: port 8080 is already bound in the VM\n"
    "# (bind error / 404s), hence 8000; and the CUDA plugin needs both\n"
    "# /content/llama and /usr/lib64-nvidia on LD_LIBRARY_PATH (see env below).\n"
)


def main():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        source = cell["source"]
        for index, line in enumerate(source):
            if OLD_ENV in line:
                source[index] = NEW_ENV + "\n"
                continue
            if '"8080"' in line:
                line = line.replace('"8080"', '"8000"')
            if "http://127.0.0.1:8080" in line:
                line = line.replace("http://127.0.0.1:8080", "http://127.0.0.1:8000")
            if line.startswith("# Serve. --jinja"):
                line = NOTE + line
            source[index] = line
        cell["source"] = source
    NOTEBOOK.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    text = NOTEBOOK.read_text(encoding="utf-8")
    assert "8080" not in text, "8080 still present"
    assert "/usr/lib64-nvidia" in text
    print("patched", NOTEBOOK)


if __name__ == "__main__":
    main()
