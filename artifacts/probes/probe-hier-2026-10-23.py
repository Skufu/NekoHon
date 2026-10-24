"""Does section routing beat whole-book dense search on the wide net? Read-only.

Two stages: score the question against every section heading, take the top-k
headings, then rank only the chunks inside those chapters. Compare with the
baseline whole-book ranking. Also reports the union (baseline top 5 plus the
routed chunks) so a routing miss cannot lose an easy hit.

Run: python artifacts/probes/probe-hier-2026-10-23.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import retrieve  # noqa: E402

DATASET = ROOT / "artifacts" / "datasets" / "wide-net-2026-10-23.jsonl"
INDEXES = {
    "fde": ROOT / "data" / "index.json",
    "quantization": ROOT / "data" / "index.quantization.json",
    "ddia": ROOT / "data" / "index.ddia.json",
}
ROUTES = (1, 2, 3, 5)
KS = (5, 10, 20)


def unit(vector):
    norm = (sum(value * value for value in vector)) ** 0.5
    return [value / norm for value in vector] if norm else vector


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def build(index):
    chunks = [chunk for chunk in index.get("chunks") or [] if chunk.get("embedding")]
    for chunk in chunks:
        chunk["_uvec"] = chunk.get("_uvec") or unit(chunk["embedding"])
    sections = {}
    for chunk in chunks:
        heading = (chunk.get("heading") or "").strip()
        if heading:
            sections.setdefault((str(chunk.get("chapter")), heading), []).append(chunk)
    keys = list(sections)
    texts = [heading[:200] for _chapter, heading in keys]
    vectors = []
    for start in range(0, len(texts), 16):
        vectors.extend(retrieve.embed_texts(
            texts[start:start + 16], index["embedder"],
            retrieve.ollama_embed, "document"))
    section_units = {key: unit(vector) for key, vector in zip(keys, vectors)}
    return chunks, sections, section_units


def ranks_for(ranked, gold):
    for position, chunk in enumerate(ranked, 1):
        if chunk["chunk_id"] in gold:
            return position
    return None


def main():
    rows = [json.loads(line) for line in
            DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    indexes = {name: retrieve.load_index(path) for name, path in INDEXES.items()}
    prepared = {name: build(index) for name, index in indexes.items()}

    results = []
    for row in rows:
        chunks, sections, section_units = prepared[row["book_id"]]
        index = indexes[row["book_id"]]
        query = unit(retrieve.embed_texts(
            [row["question"]], index["embedder"], retrieve.ollama_embed, "query")[0])
        gold = set(row["gold_chunks"])
        gold_chapter = {str(chunk.get("chapter")) for chunk in chunks
                        if chunk["chunk_id"] in gold}

        base = sorted(chunks, key=lambda c: dot(query, c["_uvec"]), reverse=True)
        heading_order = sorted(
            section_units, key=lambda key: dot(query, section_units[key]), reverse=True)

        routed = {}
        for k in ROUTES:
            chapters = {chapter for chapter, _heading in heading_order[:k]}
            pool = [chunk for chunk in chunks if str(chunk.get("chapter")) in chapters]
            pool.sort(key=lambda c: dot(query, c["_uvec"]), reverse=True)
            routed[k] = pool
        union5 = None
        for k in ROUTES:
            pool = list({c["chunk_id"]: c for c in routed[k][:25] + base[:5]}.values())
            pool.sort(key=lambda c: dot(query, c["_uvec"]), reverse=True)
            if k == 3:
                union5 = pool

        top1_chapter = heading_order[0][0] if heading_order else None
        results.append({
            "row": row,
            "base": ranks_for(base, gold),
            "routed": {k: ranks_for(pool, gold) for k, pool in routed.items()},
            "union": ranks_for(union5, gold),
            "route_hit": top1_chapter in gold_chapter,
        })

    def report(label, getter):
        parts = []
        for register in ("literal", "conversational", "vague", "all"):
            subset = [item for item in results
                      if register == "all" or item["row"]["register"] == register]
            hits = " ".join(
                f"@{k}:{sum(1 for item in subset if (getter(item) or 999) <= k)}/{len(subset)}"
                for k in KS)
            parts.append(f"{register[:4]} {hits}")
        print(f"  {label:14s} " + "  |  ".join(parts))

    print("== chapter routing ==")
    print(f"  top-1 routed chapter contains the gold chunk: "
          f"{sum(1 for item in results if item['route_hit'])}/{len(results)}")
    print("\n== source-chunk recall by strategy ==")
    report("baseline", lambda item: item["base"])
    for k in ROUTES:
        report(f"route top {k}", lambda item, k=k: item["routed"][k])
    report("route3+base5", lambda item: item["union"])

    print("\n== per-question, vague register ==")
    for item in results:
        if item["row"]["register"] != "vague":
            continue
        routed = item["routed"][3]
        print(f"  {item['row']['id']:22s} base={item['base'] or 'absent':>6} "
              f"route3={routed or 'absent':>6} union={item['union'] or 'absent':>6} "
              f"route_hit={item['route_hit']}")


if __name__ == "__main__":
    main()
