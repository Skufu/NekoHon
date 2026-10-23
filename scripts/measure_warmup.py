import json
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

OLLAMA = "http://127.0.0.1:11434"
ENGINE = "http://127.0.0.1:8000"


def evict_models():
    for model in ["nekohon_x3", "nomic-embed-text"]:
        req = urllib.request.Request(
            f"{OLLAMA}/api/generate",
            data=json.dumps({"model": model, "keep_alive": 0}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass
    time.sleep(2.0)


def get_resident_models():
    req = urllib.request.Request(f"{OLLAMA}/api/ps")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [m.get("name") for m in data.get("models", [])]
    except Exception:
        return []


def ask_question(q="What is a watermark?"):
    t0 = time.time()
    req = urllib.request.Request(
        f"{ENGINE}/ask",
        data=json.dumps({"book_id": "fde", "question": q, "mode": "ask"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    elapsed = time.time() - t0
    return elapsed, body


def main():
    print("=" * 76)
    print(" Experiment 1: Cold-start first ask (models evicted from Ollama memory)")
    print("=" * 76)
    print("Evicting models from memory...")
    evict_models()
    resident = get_resident_models()
    print(f"Resident models in Ollama: {resident}")

    print("Sending first user ask on cold models ('What is a watermark?')...")
    cold_t, cold_res = ask_question()
    print(f"COLD FIRST ASK LATENCY : {cold_t:.3f} s")
    print(f"Citation               : {cold_res.get('citations')}")
    print(f"Answer snippet         : {cold_res.get('answer', '')[:80]}...")

    print("\n" * 1)
    print("=" * 76)
    print(" Experiment 2: Restart engine with warm-up, then first ask")
    print("=" * 76)
    print("Evicting models from memory again...")
    evict_models()
    print(f"Resident models before engine warmup: {get_resident_models()}")

    from engine.server import warm_engine
    print("Running engine warmup (warm_engine)...")
    t_w0 = time.time()
    warm_engine(block=True)
    t_warm = time.time() - t_w0
    print(f"Warmup completed in {t_warm:.3f} s")

    resident_after_warm = get_resident_models()
    print(f"Resident models in Ollama BEFORE first ask: {resident_after_warm}")

    print("Sending first user ask on warmed models ('What is a watermark?')...")
    warm_t1, warm_res1 = ask_question()
    print(f"WARMED FIRST ASK LATENCY : {warm_t1:.3f} s")
    print(f"Citation                 : {warm_res1.get('citations')}")
    print(f"Answer snippet           : {warm_res1.get('answer', '')[:80]}...")

    print("\nSending second ask ('What is data ingestion?')...")
    warm_t2, warm_res2 = ask_question("What is data ingestion?")
    print(f"SECOND ASK LATENCY       : {warm_t2:.3f} s")

    speedup = cold_t / warm_t1 if warm_t1 > 0 else 0
    delta = cold_t - warm_t1
    print("\n" + "=" * 76)
    print(f" SUMMARY MEASUREMENT:")
    print(f"   Cold-start first ask : {cold_t:.3f} s")
    print(f"   Warmed first ask     : {warm_t1:.3f} s")
    print(f"   Subsequent ask       : {warm_t2:.3f} s")
    print(f"   Absolute reduction   : -{delta:.3f} s ({speedup:.2f}x faster)")
    print("=" * 76)


if __name__ == "__main__":
    main()
