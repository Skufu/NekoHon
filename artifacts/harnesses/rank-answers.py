import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from engine.answering import answer as A
import judge as J
from engine.answering.canonical import canonical_query
from engine.retrieval.retrieve import INDEX, load_index

RATER_FIELDS = ("rating", "persona_rating", "checker_rating")

GATE_FLAGS = ("--gate", "--gate-on-defects", "--fail-on-defects")
GATE_REJECTION = (
    "NOT A GATE: judged numbers are a triage dial, not a pass/fail gate.\n"
    "Measured 2026-10-15: two identical method-v2 runs wobbled 3 of 27 rows\n"
    "on single 2-1 vote flips; only rows 25-27 carry owner labels.\n"
    "Adopting a gate needs a new owner decision — a flag is not one."
)

BITS = ("answers_question", "grounded", "clean_form", "no_reask")
GOOD_WHEN_YES = ("answers_question", "grounded", "clean_form")
VOTES = 3
TAG_PATTERN = re.compile(r"\[Ch\.\s*([^\]]+)\]")
QUOTE_PATTERN = re.compile(r'"([^"]{20,})"')
DISCLOSURE_PATTERN = re.compile(r"^(Asked as:|Read as:)", re.I)


def content_text(answer):
    lines = [
        line for line in (answer or "").splitlines()
        if not DISCLOSURE_PATTERN.match(line.strip())
    ]
    return "\n".join(lines).strip()


def slug(name):
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")


def load_rows(path):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    return data["items"] if isinstance(data, dict) else data


def chapter_of(chunk_id):
    head = str(chunk_id).split("-", 1)[0]
    return str(int(head[2:])) if head.startswith("ch") and head[2:].isdigit() else head


def fold(text):
    return re.sub(r"\s+", " ", text or "").lower()


def cited_chapters(row):
    tags = {m.group(1).strip() for m in TAG_PATTERN.finditer(row.get("answer") or "")}
    stored = {str(c).strip() for c in row.get("chapters") or []}
    return tags | stored


def majority(votes):
    values = [v for v in votes if v]
    if not values:
        return "error"
    label, count = Counter(values).most_common(1)[0]
    return label if count >= 2 else "error"


def judge_row(index, row, timeout):
    out = dict(row)
    answer_text = content_text(row.get("answer"))
    asked = canonical_query(row["question"])
    try:
        passages = A.retrieval_context(index, asked)["passages"]
        passages_text = A.passages_block(passages) if passages else ""
    except Exception:
        passages_text = ""

    expect = row.get("expect")
    expect_refuse = expect == "refuse"
    out["refusal_ok"] = (bool(row.get("refused")) == expect_refuse) if expect else None

    gold = row.get("gold_chunks") or []
    if gold and not row.get("refused"):
        out["gold_cited"] = any(chapter_of(cid) in cited_chapters(row) for cid in gold)
    else:
        out["gold_cited"] = None

    key_fact = row.get("key_fact")
    out["key_fact_present"] = (
        bool(re.search(key_fact, answer_text, re.I)) if key_fact else None
    )

    if row.get("refused"):
        out["quote_ok"] = None
    else:
        spans = [m.group(1) for m in QUOTE_PATTERN.finditer(answer_text)]
        shown_texts = [hit.get("text") or "" for hit in passages]
        out["quote_ok"] = (
            all(any(A._quote_in_passage(span, t) for t in shown_texts) for span in spans)
            if spans else None
        )

    out["votes"] = {}
    if not row.get("refused"):
        for bit in BITS:
            votes = [
                J.judge_bit(bit, row["question"], passages_text, answer_text, timeout=timeout)
                for _ in range(VOTES)
            ]
            time.sleep(0.25)
            out["votes"][bit] = votes
            out[bit] = majority(votes)
    else:
        for bit in BITS:
            out[bit] = None

    if row.get("refused"):
        out["defect"] = "none" if out["refusal_ok"] else "false-refusal"
    else:
        good = {bit: (out[bit] == ("yes" if bit in GOOD_WHEN_YES else "no")) for bit in BITS}
        bad = {bit: (out[bit] != "error" and not good[bit]) for bit in BITS}
        if out.get("quote_ok") is False or bad.get("grounded") or out["grounded"] == "error":
            out["defect"] = "invented-claim"
        elif bad.get("answers_question"):
            out["defect"] = "wrong-subject"
        elif bad.get("clean_form"):
            out["defect"] = "format-drift"
        elif bad.get("no_reask") or out.get("key_fact_present") is False or out.get("gold_cited") is False:
            out["defect"] = "incomplete"
        else:
            out["defect"] = "none"
    return out


def flagged(row):
    if row.get("refusal_ok") is False:
        return True
    for field in ("gold_cited", "key_fact_present", "quote_ok"):
        if row.get(field) is False:
            return True
    for bit in BITS:
        value = row.get(bit)
        if value in (None, "error"):
            continue
        if value != ("yes" if bit in GOOD_WHEN_YES else "no"):
            return True
    return row.get("defect") not in (None, "none")


def rank_tier(row):
    if row.get("refusal_ok") is False:
        return 0
    if row.get("defect") in ("false-refusal", "invented-claim"):
        return 0
    if flagged(row):
        return 1
    return 2


def rater_summary(rows):
    lines = []
    for field in RATER_FIELDS:
        rated = [r for r in rows if r.get(field)]
        if not rated:
            continue
        agree = sum(1 for r in rated if (r[field] == "good") == (not flagged(r)))
        bads = [r for r in rated if r[field] == "bad"]
        bads_flagged = [r for r in bads if flagged(r)]
        lines.append(
            f"# {field}: agreement {agree}/{len(rated)}"
            f" | bads flagged {len(bads_flagged)}/{len(bads)}"
        )
    return lines


def main():
    parser = argparse.ArgumentParser(description="Rank answers with checkable rules and voted yes/no judge bits. A triage list, not a gate.")
    parser.add_argument("--set", required=True)
    parser.add_argument("--label", default="run")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(*GATE_FLAGS, dest="gate", action="store_true",
                        help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.gate:
        print(GATE_REJECTION, file=sys.stderr)
        sys.exit(2)

    path = Path(args.set)
    if not path.is_absolute():
        path = ROOT / path
    rows = load_rows(path)
    if args.limit:
        rows = rows[: args.limit]

    index = load_index(INDEX)
    judge_name = J.judge_name()
    judged = []
    skipped = []
    for row in rows:
        if not row.get("answer"):
            skipped.append(row.get("id"))
            continue
        started = time.time()
        try:
            out = judge_row(index, row, args.timeout)
        except Exception as exc:
            out = dict(row)
            out["defect"] = "judge_error"
            print(f'{row.get("id"):>3} judge_error: {exc!r}')
        out["seconds"] = round(time.time() - started, 1)
        judged.append(out)
        bits = " ".join(
            f"{'A' if b == 'answers_question' else 'G' if b == 'grounded' else 'F' if b == 'clean_form' else 'R'}"
            f"{'Y' if out.get(b) == ('yes' if b in GOOD_WHEN_YES else 'no') else out.get(b, '-')}"
            for b in BITS
        )
        marks = (
            f"{'ok' if out.get('refusal_ok') else 'REF!'} "
            f"g{'Y' if out.get('gold_cited') else 'N' if out.get('gold_cited') is False else '-'} "
            f"k{'Y' if out.get('key_fact_present') else 'N' if out.get('key_fact_present') is False else '-'} "
            f"q{'Y' if out.get('quote_ok') else 'N' if out.get('quote_ok') is False else '-'} "
            f"| {bits}"
        )
        print(f'{out.get("id"):>3} {out["defect"]:<15} {marks:<30} {str(row.get("question"))[:40]}')

    ordered = sorted(judged, key=lambda r: (rank_tier(r), str(r.get("id"))))

    out_dir = ROOT / "artifacts" / "runs" / "answer-quality"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"answer-quality-{args.label}-{slug(judge_name)}"
    json_path = out_dir / f"{stem}.json"
    log_path = out_dir / f"{stem}.log"

    summary_lines = [
        f"# answer-quality ranking (method v2: checkables + voted bits) — {args.label}"
        f" — {len(judged)} judged | {len(skipped)} skipped — judge {judge_name}",
        "# layer 1 checkables: refusal_ok / gold_cited / key_fact_present / quote_ok"
        " — deterministic; layer 2 bits voted 3x, majority (A answers, G grounded, F clean form, R no-reask)",
        "# defect derived from the first failed check, not asked of the judge",
    ] + rater_summary(judged) + [
        "# UNVALIDATED against human labels — a triage list, not a score.",
        "# NOT A GATE — judged numbers are a triage dial, not a pass/fail gate; --gate is rejected.",
        "# persona/checker stand-in ratings are not owner labels — only rows 25-27 carry owner labels.",
        "",
    ]

    table = ["rank | id | rated | defect | refusal_ok | gold | key | quote | A G F R | question"]
    for position, row in enumerate(ordered, start=1):
        rated = row.get("rating") or row.get("persona_rating") or row.get("checker_rating") or "-"
        bits = " ".join(str(row.get(b) or "-") for b in BITS)
        table.append(
            f'{position:4} | {row.get("id"):>3} | {rated:<5} | {row["defect"]:<14} | '
            f'{str(row.get("refusal_ok")):<10} | '
            f'{"Y" if row.get("gold_cited") else "N" if row.get("gold_cited") is False else "-"} | '
            f'{"Y" if row.get("key_fact_present") else "N" if row.get("key_fact_present") is False else "-"} | '
            f'{"Y" if row.get("quote_ok") else "N" if row.get("quote_ok") is False else "-"} | '
            f'{bits:<11} | {str(row.get("question"))[:44]}'
        )
        pin_note = row.get("pin_note")
        if pin_note:
            table.append(f'     |     | pin: {pin_note}')

    log_path.write_text("\n".join(summary_lines + table) + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {"label": args.label, "judge": judge_name, "set": str(path.name),
             "rows": ordered, "skipped": skipped},
            ensure_ascii=False, indent=1,
        ) + "\n",
        encoding="utf-8",
    )
    print("\n" + "\n".join(summary_lines))
    print(f"wrote {json_path.relative_to(ROOT)}")
    print(f"wrote {log_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
