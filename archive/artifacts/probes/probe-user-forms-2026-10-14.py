"""Owner-style query surface probe: the classes hand-typed app tests keep
hitting, run through the shipped answer seam (`answer.respond`).

Built from `artifacts/reports/query-coverage-gaps-2026-10-14.md` section 2
(30 items: 15 visible targets + 15 pure probes). The item strings were
screened there against the sealed 21-item fragment suite and against all 1365
asked forms in the finetune files — no duplicates, no near-bench strings on
the target rows.

This probe is EXPLORATORY, not a gate: one draw per item by default, no
pass/fail bar, no rates. Sealed items are never trained on; these items are
new and some are marked `role: target` to become training data later.

Run: python artifacts/probes/probe-user-forms-2026-10-14.py [--model M] [--draws N]
Default model: smallbook_x2d (the app default). Writes
artifacts/evidence/probe-user-forms/probe-user-forms-2026-10-14.model-<M>.{json,log}.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
from retrieve import INDEX, load_index

EVIDENCE = ROOT / "artifacts" / "evidence" / "probe-user-forms"

ITEMS = [
    # statements / shorthands
    {"id": "stmt-storage", "class": "statement", "role": "target",
     "expect": "cited", "q": "storage is the cornerstone of the data engineering lifecycle",
     "gold": ["ch06-001"]},
    {"id": "stmt-kafka", "class": "statement", "role": "target",
     "expect": "cited", "q": "kafka is a message queue.",
     "gold": ["ch03-086", "ch05-022"]},
    {"id": "short-tco", "class": "shorthand", "role": "target",
     "expect": "cited", "q": "tco", "gold": ["ch04-010"]},
    {"id": "short-cdc", "class": "shorthand", "role": "target",
     "expect": "cited", "q": "cdc", "gold": ["ch05-013"]},
    # contractions / possessives
    {"id": "contr-watermark", "class": "contraction", "role": "probe",
     "expect": "cited", "q": "what's a watermark?", "gold": ["ch08-039"]},
    {"id": "contr-kafka", "class": "contraction", "role": "target",
     "expect": "cited", "q": "why's kafka so popular?", "gold": ["ch03-086"]},
    {"id": "poss-watermark", "class": "possessive", "role": "target",
     "expect": "cited", "q": "watermark's purpose", "gold": ["ch08-039"]},
    {"id": "poss-mesh", "class": "possessive", "role": "target",
     "expect": "cited", "q": "the data mesh's core idea", "gold": ["ch03-099"]},
    # punctuation noise
    {"id": "punc-marks", "class": "punctuation", "role": "target",
     "expect": "cited", "q": "watermark???", "gold": ["ch08-039"]},
    {"id": "punc-dots", "class": "punctuation", "role": "target",
     "expect": "cited", "q": "batch processing...", "gold": ["ch02-019"]},
    {"id": "punc-comma", "class": "punctuation", "role": "probe",
     "expect": "cited", "q": "what is a watermark,", "gold": ["ch08-039"]},
    # degenerate input
    {"id": "deg-space", "class": "degenerate", "role": "probe",
     "expect": "record", "q": " ", "gold": []},
    {"id": "deg-symbols", "class": "degenerate", "role": "probe",
     "expect": "record", "q": "???", "gold": []},
    # chapter-level
    {"id": "chap6", "class": "chapter", "role": "probe",
     "expect": "record", "q": "what is chapter 6 about?", "gold": []},
    {"id": "chap8", "class": "chapter", "role": "probe",
     "expect": "record", "q": "what does chapter 8 cover?", "gold": []},
    # meaning-of
    {"id": "mean-mesh", "class": "meaning-of", "role": "target",
     "expect": "cited", "q": "meaning of data mesh", "gold": ["ch03-099"]},
    {"id": "mean-cdc", "class": "meaning-of", "role": "target",
     "expect": "cited", "q": "change data capture means what", "gold": ["ch05-013"]},
    # false premises
    {"id": "fp-hdfs", "class": "false-premise", "role": "probe",
     "expect": "record", "q": "why did HDFS shut down?", "gold": ["ch06-062"]},
    {"id": "fp-lake", "class": "false-premise", "role": "probe",
     "expect": "record", "q": "why did the data lake replace the data warehouse?",
     "gold": []},
    # cross-book contamination against FDE (topics absent from this index)
    {"id": "cont-gptq", "class": "contamination", "role": "probe",
     "expect": "refusal", "q": "What is GPTQ?", "gold": []},
    {"id": "cont-turbo", "class": "contamination", "role": "probe",
     "expect": "refusal", "q": "What is TurboQuant?", "gold": []},
    {"id": "cont-ptq", "class": "contamination", "role": "probe",
     "expect": "refusal", "q": "What is post-training quantization?", "gold": []},
    # vs pairs
    {"id": "vs-lambda", "class": "vs-pair", "role": "target",
     "expect": "cited", "q": "lambda vs kappa", "gold": ["ch03-088"]},
    {"id": "vs-eventual", "class": "vs-pair", "role": "target",
     "expect": "cited", "q": "eventual vs strong consistency", "gold": ["ch06-023"]},
    # polite combos
    {"id": "pol-watermark", "class": "polite-combo", "role": "probe",
     "expect": "cited", "q": "hey can you tell me what a watermark is?",
     "gold": ["ch08-039"]},
    {"id": "pol-cdc", "class": "polite-combo", "role": "probe",
     "expect": "cited", "q": "could you explain change data capture?",
     "gold": ["ch05-013"]},
    # content-word typos
    {"id": "typo-warehouse", "class": "typo", "role": "probe",
     "expect": "cited", "q": "warehosue", "gold": ["ch03-071"]},
    {"id": "typo-serial", "class": "typo", "role": "probe",
     "expect": "cited", "q": "serializaton", "gold": ["ch06-016"]},
    # casing / compound
    {"id": "case-mesh", "class": "casing", "role": "target",
     "expect": "cited", "q": "DATA MESH", "gold": ["ch03-099"]},
    {"id": "comp-cdc", "class": "compound", "role": "target",
     "expect": "cited", "q": "what is change data capture and how is it used?",
     "gold": ["ch05-013"]},
]


def verdict(expect, row):
    if "error" in row:
        return "ERROR"
    if expect == "refusal":
        return "PASS" if row["refused"] and row["refusal_exact"] else "FAIL"
    if expect == "record":
        return "RECORD"
    if row["refused"]:
        return "FAIL"
    return "PASS" if row["gold_cited"] else "PARTIAL"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="smallbook_x2d")
    parser.add_argument("--draws", type=int, default=1)
    args = parser.parse_args()

    index = load_index(INDEX)
    chunk_text = {c["chunk_id"]: c.get("text", "") for c in index["chunks"]}
    rows = []
    lines = [f"# probe-user-forms 2026-10-14 | chunks {len(index['chunks'])} "
             f"| model {args.model} | draws {args.draws} | exploratory, not a gate",
             ""]
    for item in ITEMS:
        for draw in range(1, args.draws + 1):
            started = time.perf_counter()
            try:
                body = A.respond(index, item["q"], model=args.model)
            except Exception as exc:
                rows.append({"id": item["id"], "class": item["class"],
                             "role": item["role"], "expect": item["expect"],
                             "q": item["q"], "draw": draw,
                             "error": f"{type(exc).__name__}: {exc}"})
                print(f"[{item['id']}] ERROR {type(exc).__name__}: {exc}", flush=True)
                continue
            seconds = round(time.perf_counter() - started, 2)
            answer = body["answer"]
            cites = [{"chunk_id": c["chunk_id"], "chapter": c["chapter"],
                      "quote": c["quote"]} for c in body["citations"]]
            gold_cited = sorted({c["chunk_id"] for c in cites} & set(item["gold"]))
            quote_ok = all(
                A._quote_in_passage(c["quote"], chunk_text.get(c["chunk_id"], ""))
                for c in cites
            ) if cites else None
            row = {
                "id": item["id"], "class": item["class"], "role": item["role"],
                "expect": item["expect"], "q": item["q"], "draw": draw,
                "refused": body["refused"],
                "refusal_exact": answer.strip() == A.REFUSAL,
                "cited": [c["chunk_id"] for c in cites][:3],
                "gold": item["gold"], "gold_cited": gold_cited,
                "quote_verbatim": quote_ok,
                "asked_as": "Asked as:" in answer,
                "read_as": "Read as:" in answer,
                "seconds": seconds,
                "verdict": None,
                "answer": " ".join(answer.split())[:400],
            }
            row["verdict"] = verdict(item["expect"], row)
            rows.append(row)
            line = (f"[{item['id']}] ({item['class']}/{item['role']}) "
                    f"{row['verdict']} refused={int(body['refused'])} "
                    f"cited={row['cited']} gold={gold_cited} {seconds}s")
            lines.append(line)
            lines.append(f"    q: {item['q']!r}")
            lines.append(f"    a: {row['answer'][:260]}")
            print(line, flush=True)
            print(f"    {row['answer'][:200]}", flush=True)

    ok = [r for r in rows if "error" not in r]
    summary = {}
    for row in ok:
        summary.setdefault(row["expect"], {}).setdefault(row["verdict"], 0)
        summary[row["expect"]][row["verdict"]] += 1
    lines.append("")
    for expect in ("cited", "refusal", "record"):
        if expect in summary:
            lines.append(f"summary {expect}: {summary[expect]}")
    errors = len(rows) - len(ok)
    if errors:
        lines.append(f"errors: {errors}")

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    stem = f"probe-user-forms-2026-10-14.model-{args.model}"
    (EVIDENCE / f"{stem}.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    (EVIDENCE / f"{stem}.log").write_text("\n".join(lines), encoding="utf-8")
    print()
    for line in lines[-4:]:
        print(line)
    print(f"wrote artifacts/evidence/probe-user-forms/{stem}.{{json,log}}")


if __name__ == "__main__":
    main()
