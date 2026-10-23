"""Second-book portability probe: does quote-or-refuse transfer off FDE?

Book: `books/quantbook.epub` ("Quantization and Fast Inference",
Kalyanarangan; Anna's Archive copy, local only, not redistributed — books/ is
gitignored like the FDE book). No figures in this EPUB (0), so the figure
path is untested here.

The three signatures, pre-registered before the first run (2026-10-14):

- In-book questions PASS across the board -> the behavior transfers; the
  engine is book-agnostic, not just the retrieval.
- In-book questions refuse -> the finetune is FDE-shaped: the student learned
  "answer this corpus", not "answer from these passages".
- Control questions answered -> contamination: FDE question forms drag
  answers out of passages of a different book.

Pass rule (pre-registered):
- control: PASS = refused AND answer is exactly `Not in this book.`
- in_book / bare_form: FAIL = refused; PASS = not refused AND a gold chunk is
  cited; PARTIAL = not refused and no gold chunk cited (retrieval or match
  miss, not a refusal).
- bare_form ("post-training quantization", no question mark) additionally
  measures the known wart surface (bare topics) on a new corpus; recorded,
  not gated.

The questions are visible targets for this book — if this probe is ever used
as an adoption gate for x2d+, the same lesson as the x2-trial applies: the
visible ten cannot be the suite.

Run: python artifacts/probes/probe-second-book-2026-10-14.py [model ...]
Default models: smallbook_x2, qwen2.5:7b. Index: data/index.quantbook.json
(built and embedded on first run; never touches data/index.json).
Writes artifacts/runs/second-book-2026-10-14.{json,log} (promoted to
evidence/ when a report names it).
"""

import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
import ingest
import retrieve

BOOK = ROOT / "books" / "quantbook.epub"
INDEX_OUT = ROOT / "data" / "index.quantbook.json"
RUN_JSON = ROOT / "artifacts" / "runs" / "second-book-2026-10-14.json"
RUN_LOG = ROOT / "artifacts" / "runs" / "second-book-2026-10-14.log"

QUESTIONS = [
    {"id": "ptq", "kind": "in_book", "q": "What is post-training quantization?",
     "gold": ["chapter-4-004", "chapter-4-005"], "key": r"gradient"},
    {"id": "ste", "kind": "in_book", "q": "What is the straight-through estimator?",
     "gold": ["chapter-5-019", "chapter-5-020"], "key": r"rounding"},
    {"id": "cliff", "kind": "in_book", "q": "What is the accuracy cliff?",
     "gold": ["chapter-5-005", "chapter-5-006", "chapter-5-007"], "key": r"bit-width|bit width"},
    {"id": "affine", "kind": "in_book", "q": "What is the affine mapping in quantization?",
     "gold": ["chapter-2-023"], "key": r"zero point"},
    {"id": "zeropoint", "kind": "in_book", "q": "What is the zero point in quantization?",
     "gold": ["chapter-2-036", "chapter-2-037", "chapter-2-038"], "key": r"offset"},
    {"id": "granular", "kind": "in_book", "q": "What is granular error?",
     "gold": ["chapter-2-049", "chapter-2-050"], "key": r"grid"},
    {"id": "gptq", "kind": "in_book", "q": "What is GPTQ?",
     "gold": ["chapter-7-024"], "key": r"hessian"},
    {"id": "awq", "kind": "in_book", "q": "What is AWQ?",
     "gold": ["chapter-7-044"], "key": r"salient|activation-aware"},
    {"id": "turboquant", "kind": "in_book", "q": "What is TurboQuant?",
     "gold": ["chapter-7-066"], "key": r"kv cache"},
    {"id": "kvcache", "kind": "in_book", "q": "What is the KV cache?",
     "gold": ["chapter-1-008", "chapter-3-015", "chapter-3-017"],
     "key": r"key-value|key/value|key value"},
    {"id": "bare-ptq", "kind": "bare_form", "q": "post-training quantization",
     "gold": ["chapter-4-004"], "key": r"gradient"},
    {"id": "ctl-watermark", "kind": "control", "q": "What is a watermark?",
     "gold": [], "key": None},
    {"id": "ctl-france", "kind": "control", "q": "What is the capital of France?",
     "gold": [], "key": None},
    {"id": "ctl-lakehouse", "kind": "control", "q": "What is a data lakehouse?",
     "gold": [], "key": None},
]


def build_index():
    if INDEX_OUT.is_file():
        return retrieve.load_index(INDEX_OUT)
    index = ingest.ingest_epub(BOOK, figures_dir=None, write_images=False)
    index["book_id"] = "quantbook"
    retrieve.embed_index(index, retrieve.DEFAULT_EMBEDDER)
    INDEX_OUT.parent.mkdir(parents=True, exist_ok=True)
    retrieve.save_index(INDEX_OUT, index)
    return index


def verdict(kind, refused, exact, gold_cited):
    if kind == "control":
        return "PASS" if refused and exact else "FAIL"
    if refused:
        return "FAIL"
    return "PASS" if gold_cited else "PARTIAL"


def main():
    models = sys.argv[1:] or ["smallbook_x2", "qwen2.5:7b"]
    index = build_index()
    chunk_text = {c["chunk_id"]: c.get("text", "") for c in index["chunks"]}
    rows = []
    lines = [f"# second-book probe 2026-10-14 | book chunks {len(index['chunks'])} "
             f"figures {len(index['figures'])} | models {', '.join(models)}", ""]
    for model in models:
        for item in QUESTIONS:
            started = time.perf_counter()
            body = A.respond(index, item["q"], model=model)
            seconds = round(time.perf_counter() - started, 2)
            answer = body["answer"]
            cites = [
                {"chunk_id": c["chunk_id"], "chapter": c["chapter"], "quote": c["quote"]}
                for c in body["citations"]
            ]
            gold_cited = sorted(
                {c["chunk_id"] for c in cites} & set(item["gold"])
            )
            quote_ok = all(
                A._quote_in_passage(c["quote"], chunk_text.get(c["chunk_id"], ""))
                for c in cites
            ) if cites else None
            exact = answer.strip() == A.REFUSAL
            key_hit = bool(re.search(item["key"], answer, re.I)) if item["key"] else None
            row = {
                "model": model,
                "id": item["id"],
                "kind": item["kind"],
                "q": item["q"],
                "refused": body["refused"],
                "refusal_exact": exact,
                "cited": [c["chunk_id"] for c in cites][:3],
                "gold": item["gold"],
                "gold_cited": gold_cited,
                "quote_verbatim": quote_ok,
                "key_hit": key_hit,
                "asked_as": "Asked as:" in answer,
                "read_as": "Read as:" in answer,
                "seconds": seconds,
                "verdict": verdict(item["kind"], body["refused"], exact, gold_cited),
                "answer": " ".join(answer.split())[:400],
            }
            rows.append(row)
            line = (
                f"[{model}] {item['id']} ({item['kind']}) {row['verdict']} "
                f"refused={row['refused']} cited={row['cited']} {seconds}s"
            )
            lines.append(line)
            lines.append(f"    q: {item['q']!r}")
            lines.append(f"    a: {row['answer'][:260]}")
            print(line, flush=True)
            print(f"    {row['answer'][:260]}", flush=True)
    summary = {}
    for row in rows:
        key = (row["model"], row["kind"])
        summary.setdefault(key, {"PASS": 0, "PARTIAL": 0, "FAIL": 0})
        summary[key][row["verdict"]] += 1
    lines.append("")
    for (model, kind), counts in sorted(summary.items()):
        lines.append(f"summary {model} {kind}: {counts}")
    RUN_JSON.parent.mkdir(parents=True, exist_ok=True)
    RUN_JSON.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    RUN_LOG.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote {RUN_JSON.relative_to(ROOT)} and {RUN_LOG.relative_to(ROOT)}")
    for (model, kind), counts in sorted(summary.items()):
        print(f"summary {model} {kind}: {counts}")


if __name__ == "__main__":
    main()
