"""Follow-up retrieval drift probe for 2026-10-29 (read-only, no LLM).

Two subcommands, both capturing the exact `ctx["passages"]` that answer.respond
would hand the model by wrapping answer.retrieval_context. generate_fn is a stub
that returns exactly "Not in this book.", so the answer layer never generates.

    OBSERVE=0 python3 artifacts/probes/followup-drift-2026-10-29.py matrix out/matrix.json
    OBSERVE=0 python3 artifacts/probes/followup-drift-2026-10-29.py set    out/drift.json

`matrix` replays trace 879b5033eedd's question at 0/1/2/3 prior turns, with and
without the reader's pin. `set` takes the wide-net questions whose gold chunk is
in their standalone top-5 and re-runs each after one prior turn.

Embeddings go to local Ollama (127.0.0.1:11434); nothing leaves the machine.
"""
import json
import os
import sys
from pathlib import Path

os.environ["OBSERVE"] = "0"

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import answer  # noqa: E402
import retrieve  # noqa: E402

QUESTION = "what happened in the early 200"
PIN = "ch01-025"

# The two prior turns recorded in trace 879b5033eedd's history_preview. The
# preview truncates each answer at ~140 chars, so turn 2's closing quote is
# restored here: the engine's citation regex needs it to resolve the chunk.
TRACE_HISTORY = [
    {
        "question": "what happened in the 2000's",
        "answer": '[Ch. 1] "Data warehouse and BI engineering were a precursor to '
                  'today’s data engineering and still play a central role in the discipline."\n'
                  "The early stages of da",
    },
    {
        "question": "what happened in the early 2000",
        "answer": '[Ch. 1] "Data maturity is the progression toward higher data utilization, '
                  'capabilities, and integration across the organization, but data maturity '
                  'does not simp"',
    },
]

DATASET = REPO / "artifacts" / "datasets" / "wide-net-2026-10-23.jsonl"

# One plausible prior turn for the 15-question set: the reader's first question
# about the page they are on, answered from ch01-025.
PRIOR = {
    "question": "What is data maturity?",
    "answer": '[Ch. 1] "The level of data engineering complexity within a company '
              'depends a great deal on the company\'s data maturity." Data maturity '
              "sets how much data engineering a company actually needs.",
}
PRIOR_CHUNK = "ch01-025"


def stub_generate(system, user, model=None, **kw):
    return "Not in this book."


def run(index, question, history, pin):
    captured = {"seq": [], "topic_shift": []}
    real_ctx = answer.retrieval_context
    real_rank = answer._rank_seq_chunks
    real_shift = answer._is_topic_shift_followup

    def rank_wrapper(seq_chunks, q, history_subject=None):
        ordered = real_rank(seq_chunks, q, history_subject)
        captured["seq"].append([c.get("chunk_id") for c in ordered])
        return ordered

    def shift_wrapper(*a, **kw):
        value = real_shift(*a, **kw)
        captured["topic_shift"].append(value)
        return value

    def ctx_wrapper(*a, **kw):
        ctx = real_ctx(*a, **kw)
        captured["passages"] = ctx["passages"]
        captured["asked"] = ctx.get("asked")
        return ctx

    answer.retrieval_context = ctx_wrapper
    answer._rank_seq_chunks = rank_wrapper
    answer._is_topic_shift_followup = shift_wrapper
    try:
        body = answer.respond(index, question, generate_fn=stub_generate,
                              history=history, pin_chunk=pin)
    finally:
        answer.retrieval_context = real_ctx
        answer._rank_seq_chunks = real_rank
        answer._is_topic_shift_followup = real_shift
    return {
        "shown": [p["chunk_id"] for p in captured.get("passages", [])],
        "asked": captured.get("asked"),
        "refused": body.get("refused"),
        "seq_injected": [x for x in captured["seq"] if x],
        "topic_shift": any(captured["topic_shift"]) if captured["topic_shift"] else None,
    }


def matrix(index, out_path):
    out = {"trace": "879b5033eedd", "question": QUESTION, "pin": PIN,
           "index_chunks": len(index["chunks"]), "rows": []}
    for n in (0, 1, 2, 3):
        hist = TRACE_HISTORY[:n] if n else None
        for pin in (None, PIN):
            r = run(index, QUESTION, hist, pin)
            out["rows"].append({"prior_turns": n, "pin": pin, **r})
            print(f"N={n} pin={pin!s:<9} shown={' '.join(r['shown'])}")
    Path(out_path).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")


def drift_set(index, out_path):
    book = index.get("book_id")
    items = [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip()]
    scoped = [it for it in items if it.get("book_id") == book]
    print(f"book={book} dataset rows={len(items)} scoped={len(scoped)}")

    screened = []
    for it in scoped:
        gold = set(it.get("gold_chunks") or [])
        if not gold:
            continue
        r = run(index, it["question"], None, None)
        hit = [c for c in r["shown"] if c in gold]
        screened.append({"id": it["id"], "question": it["question"],
                         "gold_chunks": sorted(gold), "standalone": r,
                         "standalone_gold": hit})
        print(f"{'HIT ' if hit else 'miss'} {it['id']:<26} {' '.join(r['shown'])}")

    keep = [r for r in screened if r["standalone_gold"]][:15]
    print(f"\nstandalone gold-in-top5: {len([r for r in screened if r['standalone_gold']])}"
          f" of {len(screened)} scoped rows; kept {len(keep)}")

    rows = []
    for r in keep:
        gold = set(r["gold_chunks"])
        pin_only = run(index, r["question"], None, PRIOR_CHUNK)
        hist = run(index, r["question"], [PRIOR], None)
        trace = run(index, r["question"], [PRIOR], PRIOR_CHUNK)
        rows.append({
            "id": r["id"], "question": r["question"], "gold_chunks": sorted(gold),
            "standalone": r["standalone"], "pin_only": pin_only,
            "followup_history": hist, "followup_trace": trace,
            "lost_history": [c for c in hist["shown"] if c in gold] == [],
            "lost_trace": [c for c in trace["shown"] if c in gold] == [],
        })
        print(f"\n{r['id']}: {r['question']}")
        for name in ("standalone", "pin_only", "followup_history", "followup_trace"):
            d = rows[-1][name]
            mark = "GOLD" if set(d["shown"]) & gold else "    "
            print(f"  {name:<17} {mark} {' '.join(d['shown'])}"
                  f"  shift={d['topic_shift']} seq={d['seq_injected']}")

    def tally(key):
        lost = [r["id"] for r in rows if r[key]]
        return {"lost": len(lost), "of": len(rows), "ids": lost}

    result = {
        "dataset": str(DATASET), "book": book, "index_chunks": len(index["chunks"]),
        "prior_turn": PRIOR, "prior_chunk": PRIOR_CHUNK,
        "screening": {"scoped_rows": len(scoped), "with_gold": len(screened),
                      "gold_in_top5": len([r for r in screened if r["standalone_gold"]]),
                      "kept": len(rows)},
        "lost_history_only": tally("lost_history"),
        "lost_history_plus_pin": tally("lost_trace"),
        "rows": rows,
    }
    Path(out_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nhistory only:  {result['lost_history_only']['lost']}/{len(rows)} lost the gold chunk")
    print(f"history + pin: {result['lost_history_plus_pin']['lost']}/{len(rows)} lost the gold chunk")
    print(f"wrote {out_path}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "set"
    out_path = sys.argv[2] if len(sys.argv) > 2 else f"{mode}.json"
    index = retrieve.load_index(str(REPO / "data" / "index.json"))
    if mode == "matrix":
        matrix(index, out_path)
    elif mode == "set":
        drift_set(index, out_path)
    else:
        raise SystemExit(f"unknown mode {mode!r}; use matrix|set")


if __name__ == "__main__":
    main()
