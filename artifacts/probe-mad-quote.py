"""MAD data landscape in ask mode: the chunk's sentences, the shown passages,
and the live quote+gloss for both phrasings. Artifact, not engine.

Run: python artifacts/probe-mad-quote.py
Writes artifacts/probe-mad-quote.{json,log}.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import answer as A
from retrieve import INDEX, load_index

QUESTIONS = ["MAD data landscape", "what is MAD data landscape"]


def sentences_of(text):
    return [" ".join(s.split()) for s in A._sentences(text or "")]


def main():
    index = load_index(INDEX)
    chunks = {c["chunk_id"]: c for c in index["chunks"]}
    lines = []
    record = {"chunk_sentences": {}, "runs": []}

    for chunk_id in ("ch04-020", "ch04-019"):
        chunk = chunks.get(chunk_id)
        if not chunk:
            continue
        record["chunk_sentences"][chunk_id] = sentences_of(chunk["text"])
        lines.append(f"== {chunk_id} ch{chunk['chapter']} sentences")
        for i, sentence in enumerate(record["chunk_sentences"][chunk_id]):
            lines.append(f"  [{i}] {sentence}")
        lines.append("")

    lines.append("== chunks where MAD is introduced (Ch. 1)")
    for chunk in index["chunks"]:
        if str(chunk.get("chapter")) == "1" and "MAD" in (chunk.get("text") or ""):
            sentences = sentences_of(chunk["text"])
            record.setdefault("mad_ch01", {})[chunk["chunk_id"]] = sentences
            lines.append(f"--- {chunk['chunk_id']}")
            for sentence in sentences:
                lines.append(f"    {sentence}")
    lines.append("")

    for question in QUESTIONS:
        ctx = A.retrieval_context(index, question)
        run = {"question": question, "passages": [
            {"chunk_id": h["chunk_id"], "chapter": h["chapter"],
             "score": None if h.get("score") is None else round(float(h["score"]), 4)}
            for h in ctx["passages"]
        ]}
        calls = []

        def logged(system, user, model, *a, **kw):
            out = A.ollama_generate(system, user, model, *a, **kw)
            calls.append({"system_head": " ".join(system.split())[:60],
                          "out": " ".join(out.split())[:900]})
            return out

        body = A.ask(index, question, generate_fn=logged)
        run["refused"] = body["refused"]
        run["answer"] = body["answer"]
        run["citations"] = [
            {k: c.get(k) for k in ("chunk_id", "chapter", "quote")}
            for c in body["citations"]
        ]
        run["figures"] = [f.get("figure_id") or f.get("id") for f in body["figures"]]
        run["calls"] = calls
        record["runs"].append(run)
        lines.append(f"== ask: {question}")
        for p in run["passages"]:
            lines.append(f"  [{p['chunk_id']} ch{p['chapter']} {p['score']}]")
        for call in calls:
            lines.append(f"  --- {call['system_head']}")
            lines.append(f"      {call['out']}")
        lines.append(f"  ANSWER: {run['answer']}")
        lines.append(f"  citations: {[(c['chunk_id'], c.get('quote')) for c in run['citations']]}")
        lines.append(f"  figures: {run['figures']}")
        lines.append("")

    log = "\n".join(lines)
    (HERE / "probe-mad-quote.log").write_text(log, encoding="utf-8")
    (HERE / "probe-mad-quote.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
