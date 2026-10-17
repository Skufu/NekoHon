"""Limit probe of the shipped query path. Artifact, not engine.

Invented queries, run through the same seam ask and respond use:
canonical_query, then retrieval_context (literal search, difflib reading,
LLM spell fallback, score gate). The answer model is not called. The
question is whether the cleaner keeps a repair, and whether that repair
lands the expected chunk.

Run: python artifacts/probes/probe-query-limit-2026-10-15.py
Writes artifacts/evidence/probe-query-limit/probe-query-limit-2026-10-15.{json,log}
"""

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
from canonical import canonical_query
from retrieve import INDEX, load_index

# expect is the chunk the clean form should reach, or None when the query
# must not be rewritten into an in-book answer.
CASES = [
    {"q": "what is a atermark?", "expect": "ch08-039", "kind": "known-typo"},
    {"q": "what is normilazation", "expect": "ch08-051", "kind": "known-llm"},
    {"q": "what is data ingestoin", "expect": "ch07-002", "kind": "known-llm"},
    {"q": "What does CRU stand for?", "expect": "ch05-019", "kind": "known-acronym"},
    {"q": "watermrak", "expect": "ch08-039", "kind": "bare-swap"},
    {"q": "wa termark", "expect": "ch08-039", "kind": "split-word"},
    {"q": "what is a watremark and a chekpoint", "expect": "ch08-039", "kind": "two-typos"},
    {"q": "normilazatoin of ingestoin", "expect": None, "kind": "two-hard-typos"},
    {"q": "so like whats a watermark thing", "expect": "ch08-039", "kind": "messy-clean-topic"},
    {"q": "Dataa analysts seek to undertstand what business performance", "expect": None, "kind": "sentence-typos"},
    {"q": "Monolith Versus Modular", "expect": None, "kind": "comparison-bare"},
    {"q": "hey", "expect": None, "kind": "greeting"},
    {"q": "asdf qwer zxcv", "expect": None, "kind": "garbage"},
    {"q": "???", "expect": None, "kind": "punct"},
    {"q": "how do", "expect": None, "kind": "fragment"},
    {"q": "what is the opposite of a watermark", "expect": None, "kind": "negation"},
    {"q": "explain watermark in simple words", "expect": "ch08-039", "kind": "clean-control"},
    {"q": "What is the capital of France?", "expect": None, "kind": "out-of-book"},
    {"q": "watermarks watermarks watermarks", "expect": "ch08-039", "kind": "repetition"},
    {"q": "CRUD CRUD CRUD CRUD ingestion streaming watermark", "expect": None, "kind": "keyword-salad"},
]


class CountingGenerate:
    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def __call__(self, system, user, model, *args, **kwargs):
        started = time.perf_counter()
        text = self.inner(system, user, model, *args, **kwargs)
        self.calls.append({
            "seconds": round(time.perf_counter() - started, 2),
            "user": user[:180],
            "out": (text or "")[:180],
        })
        return text


def main():
    index = load_index(INDEX)
    rows = []
    for case in CASES:
        question = case["q"]
        asked_form = canonical_query(question)
        counter = CountingGenerate(A.ollama_generate)
        started = time.perf_counter()
        context = A.retrieval_context(index, asked_form, generate_fn=counter)
        seconds = round(time.perf_counter() - started, 2)
        passages = context["passages"]
        top = passages[0] if passages else {}
        reading = context.get("reading") or {}
        rows.append({
            "kind": case["kind"],
            "q": question,
            "canonical": asked_form if asked_form != question else None,
            "asked": context["asked"],
            "repaired": context["asked"] != asked_form,
            "swaps": reading.get("swaps"),
            "llm_calls": len(counter.calls),
            "llm": counter.calls,
            "top": top.get("chunk_id"),
            "score": round(top.get("score") or 0, 3),
            "expect": case["expect"],
            "hit": (top.get("chunk_id") == case["expect"]) if case["expect"] else None,
            "seconds": seconds,
        })

    lines = [
        f"# query-limit — {A.ANSWER_MODEL} — {len(rows)} invented queries",
        "# repaired = the reading became the searched question",
        "# hit is only set when a chunk was expected",
        "",
    ]
    for row in rows:
        mark = ""
        if row["expect"]:
            mark = " HIT" if row["hit"] else " MISS"
        repair = f' -> "{row["asked"]}"' if row["repaired"] else ""
        canon = f' canon="{row["canonical"]}"' if row["canonical"] else ""
        lines.append(
            f'- [{row["kind"]}] "{row["q"]}"{canon}{repair}'
            f' | top {row["top"]} {row["score"]} | llm {row["llm_calls"]}'
            f' | {row["seconds"]}s{mark}'
        )
    expected = [row for row in rows if row["expect"]]
    hits = [row for row in expected if row["hit"]]
    repaired = [row for row in rows if row["repaired"]]
    lines += [
        "",
        f"# expected-chunk hits {len(hits)}/{len(expected)}",
        f"# repairs kept {len(repaired)}/{len(rows)}",
        f"# llm calls {sum(row['llm_calls'] for row in rows)}",
    ]
    out_dir = ROOT / "artifacts" / "evidence" / "probe-query-limit"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "probe-query-limit-2026-10-15.json"
    log = out.with_suffix(".log")
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
