"""Inspect chunks in quantization and ddia to build realistic evaluation scenarios."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

def inspect_book(filename, keywords):
    path = ROOT / "data" / filename
    idx = json.loads(path.read_text(encoding="utf-8"))
    print("=" * 60)
    print("BOOK:", filename, "Chunks:", len(idx.get("chunks", [])), "Figures:", len(idx.get("figures", [])))
    for kw in keywords:
        matches = []
        for c in idx.get("chunks", []):
            t = (c.get("heading", "") + " " + c.get("text", "")).lower()
            if kw.lower() in t:
                matches.append((c.get("chunk_id"), c.get("chapter"), c.get("heading"), c.get("figures", []), c.get("text", "")))
        print(f"\nKeyword: '{kw}' -> {len(matches)} matches")
        for m in matches[:2]:
            print(f"  [{m[0]}] Ch.{m[1]} | {m[2]} | figures: {m[3]}")
            # print first 2 lines
            lines = [l.strip() for l in m[4].splitlines() if l.strip()]
            for l in lines[:3]:
                print(f"    {l[:100]}")

if __name__ == "__main__":
    inspect_book("index.quantization.json", [
        "symmetric", "calibration", "kv cache", "awq", "gptq", "outlier", "int8", "figure-1-1"
    ])
    inspect_book("index.ddia.json", [
        "reliability", "fan-out", "b-tree", "lsm-tree", "replication lag", "linearizability", "two-phase commit", "figure-1-1"
    ])
