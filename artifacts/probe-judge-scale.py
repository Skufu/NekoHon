"""Does a 0-3 graded relevance scale beat the binary verdict? Artifact.

One-off A/B for the judge harness. Same 105 (question, passage) pairs the
eval replay judged — shown passages recomputed via answer.retrieval_context
(verified identical 24/24 in the replay) — now judged with a graded prompt
that mirrors the article's wording:

    3: Highly relevant
    2: Relevant
    1: Marginally relevant
    0: Not relevant

Run under whichever judge backend the environment selects, once per judge:

    python artifacts/probe-judge-scale.py
    JUDGE_BACKEND=openai JUDGE_WIRE=responses JUDGE_MODEL=... \\
        JUDGE_BASE_URL=... JUDGE_API_KEY_FILE=.judge-key \\
        python artifacts/probe-judge-scale.py

Then compare two runs (binary files are auto-found as eval-v1-<slug>.json
when they exist):

    python artifacts/probe-judge-scale.py --compare \\
        judge-grade-ollama-granite4-1-8b \\
        judge-grade-openai-muse-spark-1-3-contributor

Writes artifacts/judge-grade-<judge-slug>.json and .log.
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import answer as A
import judge as J
from retrieve import INDEX, load_index

GRADE_SYSTEM = (
    "You are a strict retrieval judge for a book question-answering system. "
    "You see one question and one passage from the book. "
    "Rate how relevant the passage is to the question on this scale: "
    "3: Highly relevant; 2: Relevant; 1: Marginally relevant; 0: Not relevant. "
    "Reply with exactly one digit, 0 to 3. No other words."
)
PASSAGE_CHARS = 2000
MAPPING_A = {"3": "relevant", "2": "relevant", "1": "not_relevant", "0": "not_relevant"}
MAPPING_B = {"3": "relevant", "2": "relevant", "1": "relevant", "0": "not_relevant"}


def slug(name):
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")


def grade(question, passage):
    user = f"Question: {question}\n\nPassage:\n{passage[:PASSAGE_CHARS]}"
    text = J._complete(GRADE_SYSTEM, user, J.JUDGE_MODEL, 60.0)
    match = re.search(r"\b([0-3])\b", text)
    return match.group(1) if match else "judge_error"


def pairs():
    """The same pairs judge_phase judged: expect answer, gold, not refused."""
    rows = json.loads((HERE / "eval-v1.json").read_text(encoding="utf-8"))
    index = load_index(INDEX)
    out = []
    for row in rows:
        if row["expect"] != "answer" or not row["gold"] or row["refused"]:
            continue
        passages = A.retrieval_context(index, row["question"])["passages"]
        ids = [hit["chunk_id"] for hit in passages]
        if ids != row["shown"]:
            print("WARNING: shown mismatch for", row["question"])
        for hit in passages:
            out.append((row["question"], hit["chunk_id"], hit.get("text") or ""))
    return out


def run_judge():
    judge_name = J.judge_name()
    judge_slug = slug(judge_name)
    work = pairs()
    print(f"judge {judge_name} | pairs {len(work)}")
    results = []
    for position, (question, chunk_id, text) in enumerate(work, start=1):
        verdict = grade(question, text)
        results.append({
            "question": question,
            "chunk_id": chunk_id,
            "grade": verdict,
        })
        if position % 25 == 0:
            print(f"  {position}/{len(work)}")
    counts = {}
    for row in results:
        counts[row["grade"]] = counts.get(row["grade"], 0) + 1
    out = HERE / f"judge-grade-{judge_slug}.json"
    log = out.with_suffix(".log")
    lines = [
        f"# graded judge — {judge_name} — {len(results)} pairs",
        "# scale: 3 highly relevant, 2 relevant, 1 marginally, 0 not",
        f"# distribution: {json.dumps(counts, sort_keys=True)}",
    ]
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:3]))
    print("wrote", out.name, "and", log.name)


def load_grades(stem):
    path = HERE / stem
    if not path.suffix:
        path = path.with_suffix(".json")
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {(row["question"], row["chunk_id"]): row["grade"] for row in rows}, stem


def load_binary(grade_stem):
    slug_part = grade_stem.replace("judge-grade-", "")
    path = HERE / f"eval-v1-{slug_part}.json"
    if not path.is_file():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    table = {}
    for row in rows:
        for item in row.get("relevance") or []:
            table[(row["question"], item["chunk_id"])] = item["verdict"]
    return table


def compare(stem_a, stem_b):
    grades_a, label_a = load_grades(stem_a)
    grades_b, label_b = load_grades(stem_b)
    binary_a = load_binary(label_a)
    binary_b = load_binary(label_b)
    shared = sorted(set(grades_a) & set(grades_b))
    exact = [k for k in shared if grades_a[k] == grades_b[k]]
    near = [k for k in shared if abs(int(grades_a[k]) - int(grades_b[k])) <= 1
            and grades_a[k] != "judge_error" and grades_b[k] != "judge_error"]
    mapped_a = {k: MAPPING_A.get(grades_a[k], "judge_error") for k in shared}
    mapped_b = {k: MAPPING_A.get(grades_b[k], "judge_error") for k in shared}
    mapped_agree_a = [k for k in shared if mapped_a[k] == mapped_b[k]]
    mapped_b_map = {k: MAPPING_B.get(grades_a[k], "judge_error") for k in shared}
    mapped_b_map_b = {k: MAPPING_B.get(grades_b[k], "judge_error") for k in shared}
    mapped_agree_b = [k for k in shared if mapped_b_map[k] == mapped_b_map_b[k]]
    errors = [k for k in shared if grades_a[k] == "judge_error" or grades_b[k] == "judge_error"]

    lines = [
        f"# graded vs binary — {label_a} vs {label_b} — {len(shared)} shared pairs",
        f"# exact grade agreement: {len(exact)}/{len(shared)}"
        f" | within +/-1: {len(near)}/{len(shared)} | judge errors: {len(errors)}",
        f"# mapped(3,2=rel) agreement: {len(mapped_agree_a)}/{len(shared)}",
        f"# mapped(3,2,1=rel) agreement: {len(mapped_agree_b)}/{len(shared)}",
    ]
    for name, table, binary in (("A", grades_a, binary_a), ("B", grades_b, binary_b)):
        if not binary:
            lines.append(f"# judge {name}: no binary eval file found for self-consistency")
            continue
        pairs_shared = [
            k for k in shared if k in binary and table[k] in MAPPING_A
        ]
        consistent_a = [k for k in pairs_shared if MAPPING_A[table[k]] == binary[k]]
        consistent_b = [k for k in pairs_shared if MAPPING_B[table[k]] == binary[k]]
        lines.append(
            f"# judge {name} self-consistency: mapped(3,2=rel) vs own binary"
            f" {len(consistent_a)}/{len(pairs_shared)}"
            f" | mapped(3,2,1=rel) {len(consistent_b)}/{len(pairs_shared)}"
        )
    lines.append("")
    lines.append("## disagreements (exact grades differ)")
    for key in shared:
        if grades_a[key] != grades_b[key]:
            lines.append(
                f"- {key[0]} | {key[1]}: {label_a}={grades_a[key]}"
                f" {label_b}={grades_b[key]}"
            )
    lines.append("")
    lines.append("## grade cross-tab (rows: " + label_a + " -> cols: " + label_b + ")")
    for ga in ("0", "1", "2", "3", "judge_error"):
        row = [sum(1 for k in shared if grades_a[k] == ga and grades_b[k] == gb)
               for gb in ("0", "1", "2", "3", "judge_error")]
        if any(row):
            shown = "E" if ga == "judge_error" else ga
            lines.append(f"- {shown}: {row}")
    log = HERE / f"judge-scale-{label_a}-vs-{label_b}.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:7]))
    print("wrote", log.name)


def main():
    parser = argparse.ArgumentParser(description="Graded relevance judge probe.")
    parser.add_argument("--compare", nargs=2, default=None)
    args = parser.parse_args()
    if args.compare:
        compare(args.compare[0], args.compare[1])
    else:
        run_judge()


if __name__ == "__main__":
    main()
