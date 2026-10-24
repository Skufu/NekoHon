"""Generate the 40 pilot answers with the Qwen3.8-27B teacher on Colab.

Same serving recipe as `reports/teacher-capture-colab-2026-10-15.ipynb`: llama.cpp
b11617 CUDA build, Qwen3.8-27B-UD-Q4_K_XL, 4 slots, port 8000, thinking off.
The prompts are already fully built by
`probes/build-pilot-seeds-2026-10-24.py`; this run only answers them.

Input : /content/pilot-seeds.jsonl   (one {"id", "system", "user"} per line)
Output: /content/pilot-answers.jsonl ({"id", "answer", "finish", "seconds"})

Resume-by-id: re-running skips ids already answered, so a dropped session costs
one row, not the batch. Run: python pilot_generate_2026-10-24.py
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BUILD = "b11617"
REPO = "unsloth/Qwen3.8-27B-GGUF"
FILE = "Qwen3.8-27B-UD-Q4_K_XL.gguf"
SEEDS = "/content/pilot-seeds.jsonl"
OUT = "/content/pilot-answers.jsonl"
WORKERS = 4
MAX_TOKENS = 250


def run(cmd, **kwargs):
    print("+", " ".join(cmd) if isinstance(cmd, list) else cmd)
    subprocess.run(cmd, check=True, **kwargs)


def setup_llama():
    os.makedirs("/content/llama", exist_ok=True)
    base = ("https://github.com/ggml-org/llama.cpp/releases/download/"
            f"{BUILD}")
    for name in (f"llama-{BUILD}-bin-ubuntu-cuda-12.8-x64.tar.gz",
                 f"cudart-llama-{BUILD}-bin-ubuntu-cuda-12.8-x64.tar.gz"):
        path = f"/content/{name}"
        if not os.path.isfile(path):
            run(["curl", "-sSL", "--retry", "3", "-o", path, f"{base}/{name}"])
        run(["tar", "-xzf", path, "-C", "/content/llama", "--strip-components=1"])
    print(subprocess.run(["/content/llama/llama-server", "--version"],
                         capture_output=True, text=True).stdout[-200:])


def setup_weights():
    os.makedirs("/content/models", exist_ok=True)
    target = f"/content/models/{FILE}"
    if os.path.isfile(target):
        print("weights present:", target)
        return
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "huggingface_hub"],
                   check=True)
    from huggingface_hub import hf_hub_download
    hf_hub_download(repo_id=REPO, filename=FILE, local_dir="/content/models")


def serve():
    env = dict(os.environ, LD_LIBRARY_PATH="/content/llama:/usr/lib64-nvidia")
    log = open("/content/llama-server.log", "w")
    subprocess.Popen(
        ["/content/llama/llama-server", "-m", f"/content/models/{FILE}",
         "--jinja", "-ngl", "99", "-fa", "on", "-c", "16384",
         "--cache-reuse", "256", "--parallel", str(WORKERS), "--port", "8000"],
        env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(180):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as r:
                if json.loads(r.read()).get("status") == "ok":
                    print("server ready")
                    return
        except Exception:
            time.sleep(2)
    raise SystemExit("server never became healthy; see /content/llama-server.log")


def ask(row):
    payload = {
        "messages": [{"role": "system", "content": row["system"]},
                     {"role": "user", "content": row["user"]}],
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        "http://127.0.0.1:8000/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    started = time.time()
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                body = json.loads(response.read())
            choice = body["choices"][0]
            return {"id": row["id"], "answer": (choice["message"].get("content") or "").strip(),
                    "finish": choice.get("finish_reason"),
                    "seconds": round(time.time() - started, 1)}
        except Exception as exc:
            if attempt == 2:
                return {"id": row["id"], "answer": "", "finish": f"error:{type(exc).__name__}",
                        "seconds": round(time.time() - started, 1)}
            time.sleep(3)


def main():
    print(subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                          "--format=csv,noheader"], capture_output=True, text=True).stdout)
    setup_llama()
    setup_weights()
    serve()

    seeds = [json.loads(line) for line in open(SEEDS, encoding="utf-8") if line.strip()]
    done = {}
    if os.path.isfile(OUT):
        for line in open(OUT, encoding="utf-8"):
            if line.strip():
                record = json.loads(line)
                done[record["id"]] = record
    pending = [row for row in seeds if row["id"] not in done or not done[row["id"]]["answer"]]
    print(f"seeds {len(seeds)}, already answered {len(done) - len(pending)}, pending {len(pending)}")

    with ThreadPoolExecutor(max_workers=WORKERS) as pool, open(OUT, "a", encoding="utf-8") as fh:
        for record in pool.map(ask, pending):
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            print(record["id"], record["finish"], record["seconds"], "s",
                  repr(record["answer"][:70]))

    answers = [json.loads(line) for line in open(OUT, encoding="utf-8") if line.strip()]
    empty = [a["id"] for a in answers if not a["answer"]]
    slow = [a["id"] for a in answers if a["seconds"] > 60]
    print(f"answered {len(answers)}/{len(seeds)}  empty {len(empty)}  slow {len(slow)}")
    if empty:
        print("EMPTY:", empty)
    if slow:
        print("SLOW (CPU fallback? check GPU RAM):", slow)
    print("PILOT DONE")


if __name__ == "__main__":
    main()
