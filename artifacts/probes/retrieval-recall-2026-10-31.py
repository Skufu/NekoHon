#!/usr/bin/env python3
"""Retrieval-only recall probe: where does the gold chunk land in the shown set?

Zero LLM calls. Mirrors the front of `answer.respond`: contextual resolve ->
canonical form -> `retrieval_context`. Reports, per item, the gold chunk's
position in the passages the model would be shown, then top-1 / top-5 totals.

Datasets (answerable items only):
  wide-net-v2  artifacts/runs/wide-net-eval-v2-2026-10-31/wide-net-v2-2026-10-31.jsonl
  trace        artifacts/datasets/trace-interaction-2026-10-29.jsonl (history from
               artifacts/runs/trace-regression-2026-10-29.json turns)

Usage: python artifacts/probes/retrieval-recall-2026-10-31.py --label before
Writes artifacts/runs/retrieval-recall-<label>.json (gitignored scratch).
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A  # noqa: E402
from canonical import canonical_query  # noqa: E402
from retrieve import load_index  # noqa: E402

WIDE = ROOT / "artifacts/runs/wide-net-eval-v2-2026-10-31/wide-net-v2-2026-10-31.jsonl"
TRACE = ROOT / "artifacts/datasets/trace-interaction-2026-10-29.jsonl"
TRACE_RUN = ROOT / "artifacts/runs/trace-regression-2026-10-29.json"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _items():
    books = {b["book_id"]: load_index(str(ROOT / b["index_path"]))
             for b in json.loads((ROOT / "data/books.json").read_text())}
    for line in WIDE.read_text().splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("expect") != "answer":
            continue
        yield ("wide", item["id"], books[item["book_id"]], item["question"],
               item.get("history") or None, item["gold_chunks"])
    rows = {r["id"]: r for r in json.loads(TRACE_RUN.read_text())["rows"]}
    for line in TRACE.read_text().splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("expect") != "answered":
            continue
        row = rows[item["id"]]
        yield ("trace", item["id"], books[item["book_id"]],
               item["turns"][-1]["question"], row["turns"][:-1] or None,
               item["gold_chunk_ids"])


def _prior_pin(index, history):
    if not history:
        return None
    import re
    m = re.search(r"\[Ch\.\s*([^\]]+)\]\s*[\"\u201c](.+?)[\"\u201d]",
                  history[-1].get("answer") or "")
    if not m:
        return None
    pos = A._prior_quote_chunk(index.get("chunks") or [], m.group(1).strip().rstrip("."), m.group(2))
    return None if pos is None else index["chunks"][pos]["chunk_id"]


PIN_PRIOR = False


def measure():
    out = []
    for group, iid, index, question, history, gold in _items():
        resolved = A._resolve_contextual_query(
            index, question, pin_chunk=None, selection="", heading="", history=history)
        asked = canonical_query(resolved)
        pin = _prior_pin(index, history) if PIN_PRIOR else None
        ctx = A.retrieval_context(index, asked, history=history, pin_chunk=pin,
                                  generate_fn=lambda *a, **k: "")
        shown = [p["chunk_id"] for p in ctx["passages"]]
        pos = next((i for i, c in enumerate(shown, 1) if c in gold), None)
        out.append({"group": group, "id": iid, "asked": ctx.get("asked"),
                    "gold": gold, "shown": shown, "gold_pos": pos})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--pin-prior", action="store_true",
                    help="emulate the reader pin: pin the chunk the prior turn quoted")
    ap.add_argument("--no-phrase-boost", action="store_true",
                    help="ablation: disable answer._prioritize_phrase_matches")
    args = ap.parse_args()
    global PIN_PRIOR
    PIN_PRIOR = args.pin_prior
    if args.no_phrase_boost:
        A._prioritize_phrase_matches = lambda passages, question: passages
    rows = measure()
    summary = {}
    for group in ("wide", "trace"):
        g = [r for r in rows if r["group"] == group]
        summary[group] = {
            "items": len(g),
            "top1": sum(1 for r in g if r["gold_pos"] == 1),
            "top5": sum(1 for r in g if r["gold_pos"]),
        }
    payload = {"label": args.label,
               "inputs_sha256": {"wide": _sha(WIDE), "trace": _sha(TRACE)},
               "summary": summary, "rows": rows}
    dest = ROOT / f"artifacts/runs/retrieval-recall-{args.label}.json"
    dest.write_text(json.dumps(payload, indent=1))
    for r in rows:
        print(f"{r['id']:30} pos={r['gold_pos']} shown={r['shown']}")
    print(json.dumps(summary))
    print("wrote", dest)


if __name__ == "__main__":
    main()
