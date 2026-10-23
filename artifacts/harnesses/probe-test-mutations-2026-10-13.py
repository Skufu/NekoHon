"""Mutation check for tests/test_canonical.py: every plausible break must
turn the suite red. In-memory patches, no file edits, no Ollama.

Mutations:
  M1 no-op canonicalization (trigger never fires)
  M2 over-firing trigger (fires on everything)
  M3 wiring dropped in answer.py (canonical module intact)
  M4 filterless anchors (stopword filter removed)
  M5 explain gate open (explain canonicalizes like ask)

Run: python artifacts/probes/probe-test-mutations-2026-10-13.py
Writes artifacts/runs/probe-test-mutations/probe-test-mutations-2026-10-13.{json,log}.
"""

import io
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

EVIDENCE = ROOT / "artifacts" / "runs" / "probe-test-mutations"

from engine.answering import answer as A
from engine.answering import freeanswer as F
from engine.answering import quoteask as Q
from engine.retrieval import keywords
from engine.retrieval.preprocess import words

import tests.test_canonical as T


def run_suite():
    suite = unittest.TestLoader().loadTestsFromModule(T)
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    names = sorted(
        test.id().split(".")[-1] for test, _ in result.failures + result.errors
    )
    return result, names


def identity(question):
    return question


def fire_all(question):
    text = (question or "").strip()
    return f"What is {text}?" if text else (question or "")


def filterless_anchors(question, word_map, bound=keywords.COVER_DF):
    return {
        word
        for word in set(words(question))
        if 0 < len(word_map.get(word, ())) <= bound
    }


def open_gate_explain(index, selection, generate_fn=None, search_fn=None,
                      model=A.ANSWER_MODEL):
    return A.ask(index, selection.strip(), generate_fn, search_fn, model)


def main():
    baseline_result, baseline_names = run_suite()
    assert baseline_result.wasSuccessful(), baseline_names

    mutations = []
    tq, aq, aw, ex = T.canonical_query, F.canonical_query, F.anchor_words, A.explain
    try:
        T.canonical_query = identity
        for m in (Q, F):
            m.canonical_query = identity
        mutations.append(("M1 no-op canonicalization", run_suite()))
    finally:
        T.canonical_query = tq
        for m in (Q, F):
            m.canonical_query = aq
    try:
        T.canonical_query = fire_all
        for m in (Q, F):
            m.canonical_query = fire_all
        mutations.append(("M2 over-firing trigger", run_suite()))
    finally:
        T.canonical_query = tq
        for m in (Q, F):
            m.canonical_query = aq
    try:
        for m in (Q, F):
            m.canonical_query = identity
        mutations.append(("M3 wiring dropped in answer.py", run_suite()))
    finally:
        for m in (Q, F):
            m.canonical_query = aq
    try:
        for m in (A, Q, F):
            m.anchor_words = filterless_anchors
        mutations.append(("M4 filterless anchors", run_suite()))
    finally:
        for m in (A, Q, F):
            m.anchor_words = aw
    try:
        A.explain = open_gate_explain
        mutations.append(("M5 explain gate open", run_suite()))
    finally:
        A.explain = ex

    restored_result, restored_names = run_suite()

    records = []
    lines = [f"baseline: failures={len(baseline_names)}", ""]
    survived = []
    for name, (result, names) in mutations:
        killed = not result.wasSuccessful()
        if not killed:
            survived.append(name)
        records.append({"mutation": name, "killed": killed,
                        "failed": len(names), "tests": names})
        lines.append(f"{'KILLED' if killed else 'SURVIVED':8} {name}: "
                     f"{len(names)} test(s) red")
        for test in names:
            lines.append(f"    - {test}")
    lines.append("")
    lines.append(f"survived mutations: {len(survived)} {survived}")
    lines.append(f"suite restored green: {restored_result.wasSuccessful()}")

    log = "\n".join(lines)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "probe-test-mutations-2026-10-13.log").write_text(log, encoding="utf-8")
    (EVIDENCE / "probe-test-mutations-2026-10-13.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
