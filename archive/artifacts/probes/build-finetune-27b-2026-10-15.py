"""Build the x2e training set from the 27B capture (2026-10-15).

Inputs (all local):
- recapture results: data/finetune/teacher-capture-results-qwen38-27b.jsonl
  (first session; ids rec-001..rec-328)
- ask-seam results: data/finetune/teacher-capture-results-ask-qwen38-27b.jsonl
  (second session; ids new-001..new-187)
- prompts: teacher-capture-2026-10-15.jsonl + teacher-capture-ask-2026-10-15.jsonl
- sealed suite: artifacts/datasets/sealed-forms.json (never trained on)
- bench: data/finetune/quote-refuse-2026-10-13.bench-x2d.jsonl (contamination)

Rules:
- keep a cited row only when it starts with [Ch. and carries >= 1 quote that is
  verbatim in a shown passage;
- keep a refusal row only when the answer is exactly `Not in this book.` and
  the row expected a refusal;
- everything else is dropped with a reason (recorded in the stats file);
- owner decision 2026-10-15: half-covered comparisons (`ddr4` asked, the book
  only covers DDR5) keep the cited DDR5 answer and get the boundary sentence
  appended to the gloss — a true statement about the book (DDR4 occurs 0
  times), applied only to questions that mention ddr4;
- refusals are downsampled deterministically (seed 20261015) to ~17% of the
  final set (x2d's working share was 16.5%);
- seal check aborts on any kept question near the sealed 21; contamination
  probe logs near-twins vs the bench.

Run: python artifacts/probes/build-finetune-27b-2026-10-15.py
Writes: data/finetune/quote-refuse-2026-10-15.train-x2e.jsonl + .stats-x2e.json
"""

import difflib
import hashlib
import importlib.util
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
from canonical import canonical_query

DATA = ROOT / "data" / "finetune"
OUT_TRAIN = DATA / "quote-refuse-2026-10-15.train-x2e.jsonl"
OUT_STATS = DATA / "quote-refuse-2026-10-15.stats-x2e.json"
SEALED = ROOT / "artifacts" / "datasets" / "sealed-forms.json"
BENCH = DATA / "quote-refuse-2026-10-13.bench-x2d.jsonl"
SEED = 20261015
REFUSAL_SHARE = 0.17
BOUNDARY = "The book describes DDR5; it does not mention DDR4."

spec = importlib.util.spec_from_file_location(
    "gen_x2d", HERE / "gen-x2d-forms-2026-10-14.py")
x2d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(x2d)

probe_spec = importlib.util.spec_from_file_location(
    "probe_fragment", HERE / "probe-fragment-2026-10-14.py")
probe = importlib.util.module_from_spec(probe_spec)
probe_spec.loader.exec_module(probe)

PASSAGE_SPLIT = re.compile(r"\[Ch\. ([^\]]+)\] chunk_id=([A-Za-z0-9]+-\d+)\n")


def passages_of(user):
    body = user.split("Passages:", 1)[1]
    parts = PASSAGE_SPLIT.split(body)
    out = []
    for i in range(1, len(parts), 3):
        chapter, chunk_id, text = parts[i], parts[i + 1], parts[i + 2]
        out.append({
            "chapter": chapter.strip(),
            "chunk_id": chunk_id,
            "text": text.split("\n\nQuestion:")[0].rstrip(),
        })
    return out


def load_prompts():
    rows = {}
    for name in ("teacher-capture-2026-10-15.jsonl",
                 "teacher-capture-ask-2026-10-15.jsonl"):
        for line in (DATA / name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["id"]] = row
    return rows


def load_results():
    rows = {}
    for name in ("teacher-capture-results-qwen38-27b.jsonl",
                 "teacher-capture-results-ask-qwen38-27b.jsonl"):
        for line in (DATA / name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["id"]] = row
    return rows


def classify(prompt, result):
    """(kind, detail) where kind in keep-cited / keep-refusal / drop."""
    answer = (result.get("answer") or "").strip()
    expect = prompt["expect"]
    if answer == "Not in this book.":
        if expect == "refusal":
            return "keep-refusal", None
        return "drop", "expected cited, teacher refused"
    if not answer:
        return "drop", "empty answer"
    if not answer.lstrip().startswith("[Ch."):
        return "drop", "does not start with [Ch."
    passages = passages_of(prompt["user"])
    quotes = A.QUOTE_PATTERN.findall(answer)
    hits = [p for p in passages
            if any(A._quote_in_passage(q, p["text"]) for q in quotes)]
    if not hits:
        return "drop", "no quote verbatim in the shown passages"
    if expect == "refusal":
        return "drop", "expected refusal, teacher answered"
    return "keep-cited", hits[0]["chunk_id"]


def main():
    prompts = load_prompts()
    results = load_results()
    missing = [i for i in prompts if i not in results]
    if missing:
        raise SystemExit(f"missing results for {len(missing)} prompts: {missing[:5]}")

    kept_cited, kept_refusal, drops = [], [], []
    pin_mismatch = 0
    for row_id, prompt in prompts.items():
        result = results[row_id]
        kind, detail = classify(prompt, result)
        if kind == "drop":
            drops.append({"id": row_id, "reason": detail,
                          "q": prompt.get("q"), "class": prompt.get("class")})
            continue
        if kind == "keep-refusal":
            kept_refusal.append((row_id, prompt, result))
            continue
        cited = detail
        if prompt.get("pin") and cited != prompt["pin"]:
            pin_mismatch += 1
        answer = (result.get("answer") or "").strip()
        if prompt.get("card") == "ddr4 vs ddr5" and "ddr4" in (prompt.get("q") or "").lower():
            answer = answer + "\n" + BOUNDARY
        kept_cited.append((row_id, prompt, result, cited, answer))

    # Deterministic refusal downsampling to ~REFUSAL_SHARE of the final set.
    wanted = round(len(kept_cited) * REFUSAL_SHARE / (1 - REFUSAL_SHARE))
    rng = random.Random(SEED)
    pool = list(kept_refusal)
    rng.shuffle(pool)
    pool.sort(key=lambda item: (item[1]["part"] != "recapture",
                                item[1].get("class") or ""))
    kept_refusal_final = pool[:wanted]

    # Seal check on the kept questions (raw + canonical, both sides).
    sealed = json.loads(SEALED.read_text(encoding="utf-8"))
    sealed_forms = list(sealed["items"])
    violations, seal_notes = [], []
    for row_id, prompt, *_ in kept_cited + kept_refusal_final:
        question = prompt.get("q") or ""
        for form in {question, canonical_query(question)}:
            for sealed_form in sealed_forms:
                ratio, jaccard = x2d.similarity(form, sealed_form)
                if ratio >= 0.8 or jaccard >= 0.6:
                    hit = {"id": row_id, "form": form,
                           "sealed": sealed_form,
                           "ratio": round(ratio, 3),
                           "jaccard": round(jaccard, 3)}
                    # Declared template twins (same interrogative template,
                    # zero content overlap) are notes, not violations — the
                    # same list probe-fragment uses (SEAL_TEMPLATE_TWINS).
                    if (sealed_form, form) in probe.SEAL_TEMPLATE_TWINS:
                        seal_notes.append(hit)
                    else:
                        violations.append(hit)
    if violations:
        print("SEALED VIOLATION — aborting:")
        for v in violations[:10]:
            print(" ", v)
        sys.exit(1)
    for note in seal_notes:
        print("sealed-note (declared template twin):", note)

    # Contamination probe vs the bench.
    bench = [json.loads(l) for l in BENCH.read_text(encoding="utf-8").splitlines()
             if l.strip()]
    bench_questions = [b.get("meta", {}).get("asked")
                       or b.get("meta", {}).get("question")
                       or b["messages"][1]["content"].splitlines()[0][10:]
                       for b in bench]
    twins = []
    for row_id, prompt, *_ in kept_cited + kept_refusal_final:
        question = prompt.get("q") or ""
        for bq in bench_questions:
            ratio, _ = x2d.similarity(question, bq)
            if ratio >= 0.8:
                twins.append({"id": row_id, "q": question, "bench": bq,
                              "ratio": round(ratio, 3)})

    rows_out = []
    for row_id, prompt, result, cited, answer in kept_cited:
        rows_out.append({
            "messages": [
                {"role": "system", "content": prompt["system"]},
                {"role": "user", "content": prompt["user"]},
                {"role": "assistant", "content": answer},
            ],
            "meta": {
                "question": prompt.get("card") or prompt.get("q"),
                "asked": prompt.get("q"),
                "source": f"27b-capture-2026-10-15:{prompt.get('class')}",
                "split": "train",
                "tier": "silver",
                "pin": prompt.get("pin"),
                "cited": [cited],
                "canonical_fired": False,
                "synthesized_gloss": False,
                "note": None,
                "capture_id": row_id,
                "part": prompt["part"],
            },
        })
    for row_id, prompt, result in kept_refusal_final:
        rows_out.append({
            "messages": [
                {"role": "system", "content": prompt["system"]},
                {"role": "user", "content": prompt["user"]},
                {"role": "assistant", "content": "Not in this book."},
            ],
            "meta": {
                "question": prompt.get("card") or prompt.get("q"),
                "asked": prompt.get("q"),
                "source": f"27b-capture-2026-10-15:{prompt.get('class')}",
                "split": "train",
                "tier": "silver",
                "pin": None,
                "cited": [],
                "canonical_fired": False,
                "synthesized_gloss": False,
                "note": None,
                "capture_id": row_id,
                "part": prompt["part"],
            },
        })

    seen, dupes = {}, []
    deduped = []
    for row in rows_out:
        user = row["messages"][1]["content"]
        if user in seen:
            dupes.append({"kept": seen[user],
                          "dropped": row["meta"]["capture_id"]})
            continue
        seen[user] = row["meta"]["capture_id"]
        deduped.append(row)
    rows_out = deduped
    if dupes:
        print("duplicate prompts dropped:", dupes)

    OUT_TRAIN.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows_out),
        encoding="utf-8")
    sha = hashlib.sha256(OUT_TRAIN.read_bytes()).hexdigest()

    def class_counts(rows):
        out = {}
        for _, prompt, *_ in rows:
            out[prompt.get("class") or "recapture"] = \
                out.get(prompt.get("class") or "recapture", 0) + 1
        return dict(sorted(out.items()))

    stats = {
        "built": "2026-10-15",
        "teacher": "Qwen3.8-27B UD-Q4_K_XL (Colab A100, ask seam)",
        "rows": len(rows_out),
        "cited": len(kept_cited),
        "refusals": len(kept_refusal_final),
        "refusal_share": round(len(kept_refusal_final) / len(rows_out), 4),
        "refusals_before_downsample": len(kept_refusal),
        "drops": drops,
        "drop_count": len(drops),
        "pin_mismatches": pin_mismatch,
        "pin_mismatches_by_part": {
            part: sum(1 for r in rows_out if r["meta"]["part"] == part
                      and r["meta"]["pin"] and r["meta"]["cited"]
                      and r["meta"]["cited"][0] != r["meta"]["pin"])
            for part in ("recapture", "new-ask")
        },
        "seal_violations": 0,
        "seal_notes": seal_notes,
        "bench_twins": twins,
        "bench_twins_exact_case_sensitive": [
            t for t in twins if t["q"] == t["bench"]],
        "bench_twins_by_part": {
            part: sum(1 for t in twins
                      for r in rows_out
                      if r["meta"]["capture_id"] == t["id"]
                      and r["meta"]["part"] == part)
            for part in ("recapture", "new-ask")
        },
        "duplicate_prompts": dupes,
        "cited_by_class": class_counts(kept_cited),
        "refusals_by_class": class_counts(kept_refusal_final),
        "sha256": sha,
    }
    OUT_STATS.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    print(f"rows {len(rows_out)} = cited {len(kept_cited)} + refusal "
          f"{len(kept_refusal_final)} (from {len(kept_refusal)}, share "
          f"{stats['refusal_share']:.1%})")
    print(f"drops {len(drops)}: "
          f"{ {d['reason']: sum(1 for x in drops if x['reason'] == d['reason']) for d in drops} }")
    print(f"pin mismatches {pin_mismatch} | bench twins {len(twins)} | "
          f"dupes {len(dupes)}")
    print(f"sha256 {sha}")
    print(f"wrote {OUT_TRAIN.relative_to(ROOT)} + {OUT_STATS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
