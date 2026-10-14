"""The plain register: cue detection and the paraphrase path.

A question that asks for simple words routes `respond` through `_plain_body`:
the draft selects evidence sentences (its citations' quotes are passage text
by construction), each is rewritten one-in-one-out, and the citation keeps the
original book sentence as evidence. Nothing is written from scratch, so the
register cannot invent — that is the measured architecture
(artifacts/evidence/eval-plain/eval-plain-v6: 8/10 scorecard pass under the release judge).

Pins and fixtures live only in this test.
"""

import unittest

import answer as A
from prompt import PARAPHRASE_SYSTEM, SYSTEM_ANSWER

REFUSAL = "Not in this book."


def hit(chunk_id, chapter, text):
    return {"chunk_id": chunk_id, "chapter": chapter, "text": text, "score": 0.9}


PASSAGES = [
    hit(
        "c1-001",
        "1",
        "Change data capture\nChange data capture (CDC) streams row-level "
        "changes from a database so downstream systems stay in sync.",
    ),
    hit(
        "c2-002",
        "2",
        "Batch processing\nBatch processing runs on a schedule and handles "
        "large volumes of records at once.",
    ),
]

DRAFT = "CDC streams row-level changes from a database. [Ch. 1]"

SIX = [
    hit("c1-a", "1", "Delta ingestion pushes readings straight to the endpoint layer."),
    hit("c2-b", "2", "Streaming buffers records inside an event platform."),
    hit("c3-c", "3", "Batch pipelines process records on a fixed schedule."),
    hit("c4-d", "4", "Schema evolution tracks columns as producers add them."),
    hit("c5-e", "5", "Lineage traces each record back to its origin system."),
    hit("c6-f", "6", "Contracts keep producers and consumers in agreement."),
]


class SimpleWordsTest(unittest.TestCase):
    def test_the_scorecard_phrasing_routes_plain(self):
        self.assertTrue(A.simple_words("explain data engineering in simple words"))

    def test_each_cue_routes_plain(self):
        for cue in A.SIMPLE_CUES:
            with self.subTest(cue=cue):
                self.assertTrue(A.simple_words(f"what is CDC {cue}"))

    def test_case_is_folded(self):
        self.assertTrue(A.simple_words("What is CDC, IN SIMPLE WORDS?"))

    def test_ordinary_question_is_not_plain(self):
        self.assertFalse(A.simple_words("What does CDC do?"))
        self.assertFalse(A.simple_words("explain data engineering"))

    def test_empty_and_none_are_not_plain(self):
        self.assertFalse(A.simple_words(""))
        self.assertFalse(A.simple_words(None))


class CleanRewriteTest(unittest.TestCase):
    def test_plain_sentence_passes_through(self):
        self.assertEqual(A._clean_rewrite("CDC sends changes."), "CDC sends changes.")

    def test_surrounding_quotes_strip(self):
        self.assertEqual(
            A._clean_rewrite('"CDC sends changes."'), "CDC sends changes."
        )

    def test_list_numbering_strips(self):
        self.assertEqual(A._clean_rewrite("1. CDC sends changes."), "CDC sends changes.")
        self.assertEqual(A._clean_rewrite("2) CDC sends changes."), "CDC sends changes.")

    def test_quotes_then_numbering(self):
        self.assertEqual(
            A._clean_rewrite('"1. CDC sends changes."'), "CDC sends changes."
        )

    def test_whitespace_collapses(self):
        self.assertEqual(
            A._clean_rewrite("CDC sends\n  changes."), "CDC sends changes."
        )

    def test_empty_and_none_strip_to_empty(self):
        self.assertEqual(A._clean_rewrite(""), "")
        self.assertEqual(A._clean_rewrite(None), "")


class PlainRespondTest(unittest.TestCase):
    def _index(self):
        return {
            "chunks": [
                {
                    "chunk_id": "c1-001",
                    "chapter": "1",
                    "heading": "Change data capture",
                    "text": PASSAGES[0]["text"],
                },
                {
                    "chunk_id": "c2-002",
                    "chapter": "2",
                    "heading": "Batch processing",
                    "text": PASSAGES[1]["text"],
                },
            ],
            "figures": [],
        }

    def _run(self, question, draft, rewrite):
        calls = []

        def fake_search(index, question, k=10):
            return PASSAGES

        def fake_generate(system, user, model):
            calls.append({"system": system, "user": user})
            if system == PARAPHRASE_SYSTEM:
                return rewrite
            if system == SYSTEM_ANSWER:
                return draft
            return ""

        body = A.respond(
            self._index(),
            question,
            generate_fn=fake_generate,
            search_fn=fake_search,
        )
        return body, calls

    def test_plain_question_rewrites_each_cited_sentence(self):
        body, calls = self._run(
            "What does CDC do in simple words?",
            DRAFT,
            "CDC sends database changes to other systems.",
        )
        rewrites = [c for c in calls if c["system"] == PARAPHRASE_SYSTEM]
        self.assertEqual(len(rewrites), 1)
        self.assertEqual(
            rewrites[0]["user"], f"Sentence: {body['citations'][0]['quote']}"
        )
        self.assertEqual(
            body["answer"], "CDC sends database changes to other systems. [Ch. 1]"
        )

    def test_citations_keep_the_book_sentence(self):
        body, _ = self._run(
            "What does CDC do in simple words?",
            DRAFT,
            "CDC sends database changes to other systems.",
        )
        self.assertEqual([c["chunk_id"] for c in body["citations"]], ["c1-001"])
        self.assertIn(body["citations"][0]["quote"], PASSAGES[0]["text"])

    def test_ordinary_question_never_calls_the_rewriter(self):
        body, calls = self._run("What does CDC do?", DRAFT, "unused")
        self.assertFalse(any(c["system"] == PARAPHRASE_SYSTEM for c in calls))
        self.assertEqual(body["answer"], DRAFT)

    def test_empty_rewrite_keeps_the_draft(self):
        body, calls = self._run("What does CDC do in simple words?", DRAFT, "   ")
        self.assertTrue(any(c["system"] == PARAPHRASE_SYSTEM for c in calls))
        self.assertFalse(body["refused"])
        self.assertEqual(body["answer"], DRAFT)

    def test_refusal_draft_is_not_rewritten(self):
        body, calls = self._run("What does CDC do in simple words?", REFUSAL, "x")
        self.assertFalse(any(c["system"] == PARAPHRASE_SYSTEM for c in calls))
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)


class PlainCapTest(unittest.TestCase):
    def test_rewrite_budget_caps_at_the_constant(self):
        draft = " ".join(
            f"{p['text']} [Ch. {p['chapter']}]" for p in SIX
        )
        rewrite_calls = []

        def fake_generate(system, user, model):
            if system == PARAPHRASE_SYSTEM:
                rewrite_calls.append(user)
                return "A plain rewritten sentence."
            return draft

        context = {"asked": "explain the pipeline in simple words", "passages": SIX}
        body = A._plain_body({"chunks": [], "figures": []}, context, fake_generate, "m")
        self.assertEqual(len(rewrite_calls), A.PARAPHRASE_LIMIT)
        self.assertEqual(body["answer"].count("[Ch. "), A.PARAPHRASE_LIMIT)
        self.assertEqual(len(body["citations"]), len(SIX))
        self.assertFalse(body["refused"])


if __name__ == "__main__":
    unittest.main()
