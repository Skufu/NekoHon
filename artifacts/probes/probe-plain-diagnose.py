"""Diagnose the plain register live: what evidence it sees, what the draft
writes, what each rewrite does to a sentence, and the final text — for the cue
question and the same question without the cue. Artifact, not engine.

Run: python artifacts/probes/probe-plain-diagnose.py
Writes artifacts/evidence/probe-plain-diagnose/probe-plain-diagnose.{json,log}.
"""

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "harnesses"))

import answer as A
import groundedness as G
from prompt import PARAPHRASE_SYSTEM, SYSTEM_ANSWER
from retrieve import INDEX, load_index

QUESTIONS = [
    "explain data engineering in simple words",
    "explain data engineering",
]


def plain_text(text):
    return " ".join((text or "").split())


def support_rows(answer, passages):
    passage_grams = set()
    for hit in passages:
        passage_grams |= G.grams(G.content_tokens(hit["text"]))
    rows = []
    for sentence in G.answer_sentences(answer):
        coverage = G.sentence_coverage(sentence, passage_grams)
        rows.append({
            "sentence": plain_text(sentence)[:200],
            "coverage": None if coverage is None else round(coverage, 3),
            "supported": None if coverage is None else coverage >= G.SUPPORT,
        })
    return rows


def run_one(index, question, label):
    record = {"label": label, "question": question}
    calls = []

    def logged(system, user, model, *a, **kw):
        t0 = time.time()
        out = A.ollama_generate(system, user, model, *a, **kw)
        tag = {
            SYSTEM_ANSWER: "draft",
            PARAPHRASE_SYSTEM: "rewrite",
        }.get(system, "other")
        calls.append({
            "tag": tag,
            "system_head": plain_text(system)[:80],
            "user": plain_text(user)[:2000],
            "out": plain_text(out)[:3000],
            "seconds": round(time.time() - t0, 2),
        })
        return out

    ctx = A.retrieval_context(index, question, generate_fn=logged)
    record["asked"] = ctx["asked"]
    record["reading"] = ctx["reading"] and ctx["reading"].get("reading")
    record["passages"] = [
        {
            "chunk_id": h["chunk_id"],
            "chapter": h["chapter"],
            "score": None if h.get("score") is None else round(float(h["score"]), 4),
            "head": plain_text(h["text"])[:140],
        }
        for h in ctx["passages"]
    ]
    t0 = time.time()
    body = A.respond(index, question, generate_fn=logged)
    record["respond_seconds"] = round(time.time() - t0, 2)
    record["calls"] = calls
    record["refused"] = body["refused"]
    record["answer"] = body["answer"]
    record["citations"] = [
        {k: c.get(k) for k in ("chunk_id", "chapter", "quote", "sentence")}
        for c in body["citations"]
    ]
    record["figures"] = body["figures"]
    record["support"] = support_rows(body["answer"], ctx["passages"])
    return record


def main():
    index = load_index(INDEX)
    lines = []
    records = []
    for question in QUESTIONS:
        label = "cue" if A.simple_words(question) else "free"
        record = run_one(index, question, label)
        records.append(record)
        lines.append(f"== {label}: {question}")
        lines.append(f"asked: {record['asked']}  reading: {record['reading']}")
        for p in record["passages"]:
            lines.append(f"  [{p['chunk_id']} ch{p['chapter']} {p['score']}] {p['head']}")
        for c in record["calls"]:
            lines.append(f"  --- {c['tag']} ({c['seconds']}s)")
            lines.append(f"      in : {c['user'][:600]}")
            lines.append(f"      out: {c['out'][:900]}")
        lines.append(f"  RESPOND ({record['respond_seconds']}s)")
        lines.append(f"  ANSWER: {plain_text(record['answer'])[:600]}")
        for row in record["support"]:
            lines.append(f"  support {row['coverage']} {row['supported']} :: {row['sentence'][:180]}")
        lines.append("")
    log = "\n".join(lines)
    (ROOT / "artifacts" / "evidence" / "probe-plain-diagnose" / "probe-plain-diagnose.log").write_text(log, encoding="utf-8")
    (ROOT / "artifacts" / "evidence" / "probe-plain-diagnose" / "probe-plain-diagnose.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
