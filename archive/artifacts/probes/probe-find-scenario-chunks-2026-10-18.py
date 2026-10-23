"""Find exact chunks for the 30 scenarios."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

def find_chunks(book_id, query_terms):
    fname = "index.json" if book_id == "fde" else f"index.{book_id}.json"
    idx = json.loads((ROOT / "data" / fname).read_text(encoding="utf-8"))
    results = {}
    for term in query_terms:
        matches = []
        for c in idx.get("chunks", []):
            full = c.get("heading", "") + "\n" + c.get("text", "")
            if term.lower() in full.lower():
                matches.append(c)
        results[term] = matches
    return results

if __name__ == "__main__":
    q_terms = [
        "Affine quantization", "symmetric", "calibration", "KV cache", "AWQ",
        "Compute is cheap", "outlier", "smoothquant", "FP16"
    ]
    res_q = find_chunks("quantization", q_terms)
    for term, matches in res_q.items():
        print(f"[Quantization] {term}: {len(matches)} matches")
        if matches:
            c = matches[0]
            print(f"  ID: {c.get('chunk_id')}, Ch: {c.get('chapter')}, Heading: {c.get('heading')}, Figs: {c.get('figures')}")
            print(f"  Text snippet: {c.get('text', '')[:120].strip()}")

    ddia_terms = [
        "Reliability", "Faults", "Describing Load", "Twitter", "SSTables and LSM-Trees",
        "B-Trees", "Replication Lag", "Linearizability", "Two-Phase Commit", "leaderless"
    ]
    res_d = find_chunks("ddia", ddia_terms)
    for term, matches in res_d.items():
        print(f"[DDIA] {term}: {len(matches)} matches")
        if matches:
            c = matches[0]
            print(f"  ID: {c.get('chunk_id')}, Ch: {c.get('chapter')}, Heading: {c.get('heading')}, Figs: {c.get('figures')}")
            print(f"  Text snippet: {c.get('text', '')[:120].strip()}")
