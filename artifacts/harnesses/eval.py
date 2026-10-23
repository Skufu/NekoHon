"""Answer-engine evaluation over the labeled set. Artifact, not engine.

The metrics are deliberately separate — one blended F1 number would hide
which side failed:

- dense recall@10: a gold chunk in the raw dense top 10. The retrieval net.
- shown recall@5: a gold chunk among the passages the model is shown (after
  the reading, fusion, and caption seeding). The fatal false negative: if the
  gold is absent here, the model cannot answer it.
- MRR@10: mean 1/rank of the best-placed gold in the dense list (0 if absent).
- gold precision@5: gold shown / shown. Strict: only labeled gold counts;
  unlabeled-but-relevant passages count as misses, so read it as a floor.
- cited share: cited chunks / shown — how much of the shown context the answer
  actually used.
- refusal behavior: expect=refuse but answered (false answer) and
  expect=answer but refused (false refusal) counted separately — the error
  classes from the user's review.
- key fact: regex hit first; misses go to the cross-family judge (granite)
  for a paraphrase check.
- relevance judge (--judge): every shown passage judged relevant/not by
  the configured judge (`muse-spark-1.3-contributor` by default since
  2026-10-15; `JUDGE_BACKEND=ollama` = granite4.1:8b). The direct precision
  reading. Verdicts are UNVALIDATED
  against human labels; the gold-not-relevant list is the judge-vs-pin
  disagreement, the strongest calibration signal this run can show.

Run: python artifacts/harnesses/eval.py --label v1 [--judge] [--limit N]
Judge-only replay under another judge (same answers, new verdicts):
  JUDGE_BACKEND=openai JUDGE_MODEL=<m> JUDGE_BASE_URL=<u> JUDGE_API_KEY=<k> \
    python artifacts/harnesses/eval.py --judge-only --label v1
Agreement between two judged runs: python artifacts/harnesses/judge-agreement.py <a> <b>
Writes artifacts/runs/eval-v1/eval-<label>[-<judge-slug>].{json,log}.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "harnesses"))

from engine.answering import answer as A
import groundedness as G
from engine.answering.prompt import ANSWER_MODEL, SYSTEM_ANSWER
from engine.retrieval.retrieve import INDEX, load_index, search

SET_PATH = ROOT / "artifacts" / "datasets" / "eval-set.json"


def run_generate(system, user, model, timeout):
    return A.ollama_generate(system, user, model, timeout=timeout)


def best_rank(ids, wanted):
    ranks = [ids.index(wanted_id) + 1 for wanted_id in wanted if wanted_id in ids]
    return min(ranks) if ranks else None


def eval_item(index, item, timeout):
    question = item["question"]
    dense = search(index, question, k=10)
    dense_ids = [hit["chunk_id"] for hit in dense]
    # Not the server path. respond/ask serve SYSTEM + user_message.
    # This harness still measures SYSTEM_ANSWER unless you pass another prompt.
    measured = G.measure(index, question, run_generate, timeout, SYSTEM_ANSWER)
    passages = A.retrieval_context(index, question)["passages"]
    shown = [hit["chunk_id"] for hit in passages]
    gold = item["gold_chunks"]
    rank = best_rank(dense_ids, gold)
    shown_hits = [chunk_id for chunk_id in gold if chunk_id in shown]
    expected_answer = item["expect"] == "answer"
    key_fact = item.get("key_fact")
    row = {
        "question": question,
        "source": item["source"],
        "expect": item["expect"],
        "known_issue": bool(item.get("known_issue")),
        "gold": gold,
        "key_fact": key_fact,
        "dense10": dense_ids,
        "gold_dense_rank": rank,
        "mrr": round(1.0 / rank, 3) if rank else 0.0,
        "shown": shown,
        "shown_gold_hits": shown_hits,
        "gold_precision": round(len(shown_hits) / len(shown), 3) if shown else None,
        "refused": measured["refused"],
        "answer": measured["answer"],
        "citations": measured["citations"],
        "cited_share": (
            round(len(measured["citations"]) / len(shown), 3) if shown else None
        ),
        "support": measured.get("supported"),
        "sentences": measured.get("sentences"),
        "fake_quotes": measured.get("fake_quotes") or [],
        "key_fact_ok": (
            re.search(key_fact, measured["answer"], re.I) is not None
            if key_fact else None
        ),
        "key_fact_judge": None,
        "relevance": None,
        "judge_errors": 0,
        "refusal_ok": measured["refused"] != expected_answer,
        "seconds": None,
        "shown_texts": [(hit["chunk_id"], hit.get("text") or "") for hit in passages],
    }
    return row


def judge_phase(rows, timeout):
    """The judge phase: relevance for every shown passage, key-fact rescue.

    Runs after all answering is done, so the two model families load once each
    (this box holds one of them in 8 GB at a time). Rows carry the judge's
    identity so an agreement run can tell two verdict sets apart.
    """
    import judge as J

    for row in rows:
        passages = row.pop("shown_texts", [])
        if (
            not row["refused"]
            and row["key_fact"] is not None
            and row["key_fact_ok"] is False
        ):
            row["key_fact_judge"] = J.judge_key_fact(
                row["question"], row["key_fact"], row["answer"], timeout=timeout
            )
        verdicts = []
        if row["expect"] == "answer" and row["gold"] and not row["refused"]:
            for chunk_id, text in passages:
                verdict = J.judge_relevance(row["question"], text, timeout=timeout)
                if verdict == "judge_error":
                    row["judge_errors"] += 1
                verdicts.append({"chunk_id": chunk_id, "verdict": verdict})
        row["relevance"] = verdicts
        row["judge"] = J.judge_name()
    return rows


def J_judge_name():
    import judge as J

    return J.judge_name()


def summarize(rows, judge_used):
    answered_expect = [r for r in rows if r["expect"] == "answer"]
    refused_expect = [r for r in rows if r["expect"] == "refuse"]
    with_gold = [r for r in answered_expect if r["gold"]]
    dense_recall = sum(1 for r in with_gold if r["gold_dense_rank"])
    shown_recall = sum(1 for r in with_gold if r["shown_gold_hits"])
    mrr = sum(r["mrr"] for r in with_gold) / len(with_gold) if with_gold else 0.0
    precisions = [
        r["gold_precision"] for r in with_gold if r["gold_precision"] is not None
    ]
    precision_mean = (
        round(sum(precisions) / len(precisions), 3) if precisions else None
    )
    cited = [r["cited_share"] for r in with_gold if r["cited_share"] is not None]
    cited_mean = round(sum(cited) / len(cited), 3) if cited else None
    false_refusals = [r for r in answered_expect if r["refused"]]
    false_answers = [r for r in refused_expect if not r["refused"]]
    key_rows = [r for r in answered_expect if r["key_fact_ok"] is not None]
    key_hits = [r for r in key_rows if r["key_fact_ok"]]
    key_rescued = [
        r for r in key_rows
        if not r["key_fact_ok"] and r["key_fact_judge"] == "states"
    ]
    key_missing = [r for r in key_rows if not r["key_fact_ok"] and r not in key_rescued]
    verdicts = [v for r in rows for v in (r["relevance"] or [])]
    rel_positive = sum(1 for v in verdicts if v["verdict"] == "relevant")
    judge_errors = sum(r["judge_errors"] for r in rows)
    gold_not_relevant = [
        (r["question"], v["chunk_id"])
        for r in rows for v in (r["relevance"] or [])
        if v["verdict"] == "not_relevant" and v["chunk_id"] in r["gold"]
    ]

    lines = [
        f"# eval — {len(rows)} items — answerer {ANSWER_MODEL}"
        + (
            f" — judge {J_judge_name()} (UNVALIDATED vs human labels)"
            if judge_used else ""
        ),
        f"# recall@10 dense {dense_recall}/{len(with_gold)}"
        f" | shown recall@5 {shown_recall}/{len(with_gold)}"
        f" | MRR@10 {mrr:.3f}"
        f" | gold precision@5 floor {precision_mean if precision_mean is not None else 'n/a'}",
        f"# cited share {cited_mean if cited_mean is not None else 'n/a'}"
        f" | false answers {len(false_answers)}/{len(refused_expect)}"
        f" | false refusals {len(false_refusals)}/{len(answered_expect)}",
        f"# key facts: regex {len(key_hits)}/{len(key_rows)}"
        f" | judge rescued {len(key_rescued)}"
        f" | still missing {len(key_missing)}",
    ]
    if judge_used:
        rel_line = f"# judged relevance {rel_positive}/{len(verdicts)}"
        if verdicts:
            rel_line += f" ({rel_positive / len(verdicts):.3f})"
        lines.append(rel_line + f" | judge errors {judge_errors}")
    lines.append("")
    lines.append("## dense misses (gold not in the dense top-10)")
    lines.append(
        "# Shown-recall recovery of these rows is the reading/fusion/caption work;"
        " a row missing from BOTH lists is a true false negative."
    )
    for row in with_gold:
        if row["gold_dense_rank"] is None:
            lines.append(
                f"- {row['question']} | gold {row['gold']}"
                f" | shown {row['shown']} | recovered={bool(row['shown_gold_hits'])}"
            )
    lines.append("")
    lines.append("## false negatives (expected answer, no gold among the shown 5)")
    for row in answered_expect:
        if row["gold"] and not row["shown_gold_hits"]:
            lines.append(f"- {row['question']} | gold {row['gold']} | shown {row['shown']}")
    lines.append("")
    lines.append("## false refusals")
    for row in false_refusals:
        lines.append(f"- {row['question']} | gold {row['gold'] or '-'}")
    lines.append("")
    lines.append("## false answers (refused expected)")
    for row in false_answers:
        lines.append(f"- {row['question']} | {row['answer'][:100]}")
    lines.append("")
    lines.append("## key-fact misses still missing after the judge")
    for row in key_missing:
        lines.append(
            f"- {row['question']} | key {row['key_fact']!r}"
            f" | answer {row['answer'][:100]!r}"
        )
    lines.append("")
    lines.append("## known issues")
    for row in rows:
        if row["known_issue"]:
            lines.append(f"- {row['question']} | refused={row['refused']}")
    if judge_used:
        lines.append("")
        lines.append("## gold judged not relevant (judge vs pin disagreement)")
        for question, chunk_id in gold_not_relevant:
            lines.append(f"- {question} | {chunk_id}")
    return lines


def main():
    parser = argparse.ArgumentParser(description="Evaluate the engine over the labeled set.")
    parser.add_argument("--label", default="v1")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--judge", action="store_true")
    parser.add_argument(
        "--judge-only", action="store_true",
        help="replay a judged run under the configured judge; answers are not regenerated",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    index = load_index(INDEX)
    replay_note = ""
    if args.judge_only:
        base = ROOT / "archive" / "artifacts" / "evidence" / "eval-v1" / f"eval-{args.label}.json"
        rows = json.loads(base.read_text(encoding="utf-8"))
        mismatches = 0
        for row in rows:
            passages = A.retrieval_context(index, row["question"])["passages"]
            ids = [hit["chunk_id"] for hit in passages]
            if ids != row["shown"]:
                mismatches += 1
            row["shown_texts"] = [
                (hit["chunk_id"], hit.get("text") or "") for hit in passages
            ]
        rows = judge_phase(rows, args.timeout)
        replay_note = (
            f"# judge-only replay of {base.name}; shown passages recomputed",
            f" identical for {len(rows) - mismatches}/{len(rows)} items",
        )
        slug = re.sub(r"[^a-z0-9-]+", "-", J_judge_name().lower()).strip("-")
        out = ROOT / "artifacts" / "runs" / "eval-v1" / f"eval-{args.label}-{slug}.json"
        log = out.with_suffix(".log")
        lines = summarize(rows, True)
        lines.insert(1, "".join(replay_note))
        for row in rows:
            row.pop("shown_texts", None)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines[:6]))
        print("wrote", out.name, "and", log.name)
        return

    items = json.loads(SET_PATH.read_text(encoding="utf-8"))["items"]
    if args.limit:
        items = items[:args.limit]

    out = ROOT / "artifacts" / "runs" / "eval-v1" / f"eval-{args.label}.json"
    log = out.with_suffix(".log")

    rows = []
    for position, item in enumerate(items, start=1):
        started = time.perf_counter()
        row = eval_item(index, item, args.timeout)
        row["seconds"] = round(time.perf_counter() - started, 2)
        rows.append(row)
        print(
            f"{position:3}/{len(items)} refused={int(row['refused'])} "
            f"rank={row['gold_dense_rank']} {row['question'][:60]}"
        )
    if args.judge:
        rows = judge_phase(rows, args.timeout)

    lines = summarize(rows, args.judge)
    for row in rows:
        row.pop("shown_texts", None)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:5]))
    print("wrote", out.name, "and", log.name)


if __name__ == "__main__":
    main()
