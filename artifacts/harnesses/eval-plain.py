import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "harnesses"))
sys.path.insert(0, str(ROOT / "artifacts" / "harnesses"))

from engine.answering import answer as A, answermode, context as context_mod, messages
import groundedness as G
import judge as J
from engine.answering.prompt import ANSWER_MODEL, REFUSAL, SYSTEM_ANSWER
from engine.retrieval.retrieve import INDEX, load_index

FK_GATE = 11.0
COVERAGE_TARGET = 0.2


def load_probe():
    spec = importlib.util.spec_from_file_location(
        "probe_plain", ROOT / "artifacts" / "harnesses" / "probe-plain.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load_probe()
PLAIN_SYSTEM = probe.PLAIN_SYSTEM
SYSTEMS = {
    "current": {"system": SYSTEM_ANSWER},
    "plain": {"system": PLAIN_SYSTEM},
    "plain3": {"system": probe.PLAIN3_SYSTEM},
    "plain3-rv": {
        "system": probe.PLAIN3_SYSTEM,
        "revise": probe.REVISE_SYSTEM,
    },
    "paraphrase": {
        "system": SYSTEM_ANSWER,
        "paraphrase": probe.PARAPHRASE_SYSTEM,
    },
    "wired": {"wired": True},
}


def selected_variants(spec):
    names = [name.strip() for name in spec.split(",") if name.strip()]
    unknown = [name for name in names if name not in SYSTEMS]
    if unknown:
        raise SystemExit(f"unknown variants {unknown}; have {sorted(SYSTEMS)}")
    return [(name, SYSTEMS[name]) for name in names]


def slug(name):
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")


def unmatched_tags(answer, passages):
    count = 0
    for claim, chapters in answermode.sentence_claims(answer):
        if answermode.best_passage(claim, chapters, passages) is None:
            count += 1
    return count


def clean_rewrite(text):
    text = (text or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    text = re.sub(r"^\s*[\d]+[.)]\s*", "", text)
    return " ".join(text.split())


def score(question, answer, fake_source, body, passages, started):
    shown = [hit["chunk_id"] for hit in passages]
    passages_text = "\n\n".join(hit.get("text") or "" for hit in passages)
    readability = probe.stats(answer)
    grounding = probe.grounding(answer, passages)
    fake = G.fake_quotes(fake_source, passages)
    fidelity = J.judge_book_fidelity(question, passages_text, answer)
    fidelity_raw = J.LAST_REPLY["text"][:200]
    example = J.judge_plain_example(question, passages_text, answer)
    example_raw = J.LAST_REPLY["text"][:200]
    return {
        "answer": answer,
        "refused": body["refused"],
        "citations": [c["chunk_id"] for c in body["citations"]],
        "cited_share": round(len(body["citations"]) / len(shown), 3) if shown else None,
        "readability": readability,
        "grounding": grounding,
        "fake_quotes": fake,
        "fidelity": fidelity,
        "fidelity_raw": fidelity_raw,
        "example": example,
        "example_raw": example_raw,
        "unmatched_tags": unmatched_tags(answer, passages),
        "seconds": round(time.perf_counter() - started, 2),
        "gates": {
            "answered": not body["refused"],
            "no_fake_quotes": len(fake) == 0,
            "book_supported": fidelity == "supported",
            "grade_ok": readability["fk_grade"] <= FK_GATE,
        },
    }


def measure(index, question, spec, passages):
    started = time.perf_counter()
    completion = A.ollama_generate(
        spec["system"], messages.answer_user_message(question, passages), ANSWER_MODEL
    )
    if spec.get("revise"):
        passages_text = "\n\n".join(hit.get("text") or "" for hit in passages)
        revise_user = (
            f"Question: {question}\n\nPassages:\n{passages_text[:5000]}\n\n"
            f"Draft answer:\n{completion}"
        )
        completion = A.ollama_generate(spec["revise"], revise_user, ANSWER_MODEL)
    if spec.get("paraphrase"):
        draft = answermode.parse_answered(completion, passages, index.get("figures") or [])
        if draft["refused"]:
            completion = REFUSAL
        else:
            assembled = []
            for citation in draft["citations"][:5]:
                rewritten = A.ollama_generate(
                    spec["paraphrase"],
                    f"Sentence: {citation['quote']}",
                    ANSWER_MODEL,
                )
                if rewritten.strip():
                    assembled.append(
                        f"{clean_rewrite(rewritten)} [Ch. {citation['chapter']}]"
                    )
            completion = " ".join(assembled) if assembled else REFUSAL
    body = answermode.parse_answered(completion, passages, index.get("figures") or [])
    return score(question, body["answer"], completion, body, passages, started)


def measure_wired(index, question, passages):
    started = time.perf_counter()

    def stub_search(idx, query, k=10):
        return passages

    context = context_mod.retrieval_context(index, question, search_fn=stub_search)
    body = A.respond(index, question, search_fn=stub_search)
    shown = context["passages"]
    result = score(question, body["answer"], body["answer"], body, shown, started)
    result["same_shown"] = (
        [h["chunk_id"] for h in shown] == [h["chunk_id"] for h in passages]
    )
    result["reading"] = None if context["reading"] is None else context["reading"]["reading"]
    return result


def main():
    parser = argparse.ArgumentParser(description="Plain-register scorecard.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--variants", default="current,plain")
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    variants = selected_variants(args.variants)

    items = json.loads(
        (ROOT / "artifacts" / "datasets" / "eval-set-plain.json").read_text(encoding="utf-8")
    )["items"]
    if args.limit:
        items = items[:args.limit]
    index = load_index(INDEX)

    rows = []
    for position, item in enumerate(items, start=1):
        question = item["question"]
        passages = context_mod.retrieval_context(index, question)["passages"]
        row = {"question": question, "gold": item["gold_chunks"], "variants": {}}
        for name, spec in variants:
            if spec.get("wired"):
                row["variants"][name] = measure_wired(index, question, passages)
            else:
                row["variants"][name] = measure(index, question, spec, passages)
        rows.append(row)
        print(f"{position:2}/{len(items)} {question}")

    def variant_rows(name):
        return [row["variants"][name] for row in rows]

    lines = [f"# plain scorecard — {J.judge_name()} — {len(rows)} questions"
             f" — variants {','.join(name for name, _ in variants)}"
             f" — fk gate <= {FK_GATE}, coverage target >= {COVERAGE_TARGET}"]
    for name, _ in variants:
        values = variant_rows(name)
        passes = sum(1 for v in values if all(v["gates"].values()))
        gate_failures = {
            key: sum(1 for v in values if not v["gates"][key])
            for key in ("answered", "no_fake_quotes", "book_supported", "grade_ok")
        }
        def mean_of(getter):
            vals = [getter(v) for v in values if getter(v) is not None]
            return round(sum(vals) / len(vals), 3) if vals else None

        fk = mean_of(lambda v: v["readability"]["fk_grade"])
        sentence = mean_of(lambda v: v["readability"]["mean_sentence"])
        coverage = mean_of(lambda v: v["grounding"]["mean_coverage"])
        words = mean_of(lambda v: v["readability"]["words"])
        cited_share = mean_of(lambda v: v["cited_share"])
        examples = sum(1 for v in values if v["example"] == "example")
        judge_errors = sum(
            1 for v in values if v["fidelity"] == "judge_error" or v["example"] == "judge_error"
        )
        lines.append(
            f"# {name}: pass {passes}/{len(values)} | gate fails {gate_failures}"
            f" | fk {fk} | words/sentence {sentence}"
            f" | coverage {coverage} | words {words}"
            f" | cited share {cited_share}"
            f" | example {examples}/{len(values)}"
            f" | unmatched tags {sum(v['unmatched_tags'] for v in values)}"
            f" | fake quotes {sum(len(v['fake_quotes']) for v in values)}"
            f" | judge errors {judge_errors}"
        )
    lines.append("")
    for row in rows:
        lines.append(f"## {row['question']}")
        for name, _ in variants:
            v = row["variants"][name]
            gates = "".join(
                "P" if v["gates"][key] else "F"
                for key in ("answered", "no_fake_quotes", "book_supported", "grade_ok")
            )
            lines.append(
                f"- {name}: gates {gates}"
                f" | fk {v['readability']['fk_grade']}"
                f" | cov {v['grounding']['mean_coverage']}"
                f" | fidelity {v['fidelity']} | example {v['example']}"
                f" | unmatched {v['unmatched_tags']}"
                f" | {v['answer'].splitlines()[0][:100]}"
            )

    parts = ["eval-plain"] + ([args.label] if args.label else []) + [slug(J.judge_name())]
    out = ROOT / "artifacts" / "runs" / "eval-plain" / ("-".join(parts) + ".json")
    log = out.with_suffix(".log")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:4]))
    print("wrote", out.name, "and", log.name)


if __name__ == "__main__":
    main()
