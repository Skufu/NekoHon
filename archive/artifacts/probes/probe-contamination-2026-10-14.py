"""Train/bench contamination check for the finetune files.

One question, with numbers: does any train question look like a bench
question (the exam)? Exact asked-form overlap, plus fuzzy near-forms by
difflib similarity and word-set (Jaccard) similarity on the raw questions.

Run: python artifacts/probes/probe-contamination-2026-10-14.py
Writes artifacts/evidence/probe-contamination/probe-contamination-2026-10-14.{json,log}.
"""

import difflib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DATA = ROOT / "data" / "finetune"


def rows(name):
    path = DATA / f"quote-refuse-2026-10-13.{name}.jsonl"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        meta = row.get("meta") or {}
        out.append({
            "q": (meta.get("question") or "").strip(),
            "asked": (meta.get("asked") or meta.get("question") or "").strip(),
            "tier": meta.get("tier"),
        })
    return out


def words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def norm(text):
    return re.sub(r"\s+", " ", text.casefold()).strip()


train, bench = rows("train"), rows("bench")
train_asked = {norm(r["asked"]) for r in train}
exact = [r["q"] for r in bench if norm(r["asked"]) in train_asked]

pairs = []
for b in bench:
    best = None
    for t in train:
        d = difflib.SequenceMatcher(None, norm(b["q"]), norm(t["q"])).ratio()
        j = jaccard(words(b["q"]), words(t["q"]))
        score = max(d, j)
        if best is None or score > best[0]:
            best = (score, t)
    if best and best[0] >= 0.8:
        pairs.append({
            "bench": b["q"],
            "train": best[1]["q"],
            "score": round(best[0], 3),
            "tier": best[1]["tier"],
        })

lines = [
    f"rows: train {len(train)} / bench {len(bench)}",
    f"exact asked-form overlap: {len(exact)}",
    f"near-form pairs (score >= 0.8): {len(pairs)}",
]
for item in sorted(pairs, key=lambda x: -x["score"]):
    lines.append(
        f"  {item['score']:.2f}  bench {item['bench']!r} <- train "
        f"{item['train']!r} [{item['tier']}]"
    )
if exact:
    lines.append("exact asked forms in both files:")
    lines.extend(f"  {q!r}" for q in exact)

log = "\n".join(lines)
(ROOT / "artifacts" / "evidence" / "probe-contamination" / "probe-contamination-2026-10-14.log").write_text(log, encoding="utf-8")
(ROOT / "artifacts" / "evidence" / "probe-contamination" / "probe-contamination-2026-10-14.json").write_text(
    json.dumps({"exact": exact, "pairs": pairs}, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
print(log)
