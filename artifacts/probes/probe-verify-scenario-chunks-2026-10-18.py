"""Find exact chunks for needed phrases."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

def find_exact(book_id, needle):
    fname = f"index.{book_id}.json"
    idx = json.loads((ROOT / "data" / fname).read_text(encoding="utf-8"))
    for c in idx.get("chunks", []):
        t = c.get("text", "")
        if needle.lower() in t.lower():
            idx_pos = t.lower().find(needle.lower())
            start = max(0, idx_pos - 40)
            end = min(len(t), idx_pos + 80)
            print(f"[{book_id}] {c.get('chunk_id')}, Ch.{c.get('chapter')}, heading={c.get('heading')}")
            print(f"   ... {t[start:end].replace(chr(10), ' ')} ...")
            return c
    print(f"[{book_id}] needle '{needle}' NOT FOUND")
    return None

if __name__ == "__main__":
    find_exact("quantization", "Affine quantization")
    find_exact("quantization", "outlier")
    find_exact("quantization", "symmetric quantization")
    find_exact("ddia", "fault")
    find_exact("ddia", "failure")
    find_exact("ddia", "two-phase commit")
    find_exact("ddia", "linearizability")
