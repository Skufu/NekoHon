"""The answer mode: free generation from the retrieved passages.

parse_answered turns the model's prose and [Ch. tags into the contract body.
The quote check is a meter here, not a gate: unbacked quotation marks are
stripped, a zero-overlap sentence is left uncited rather than pinned to a
guess, and a refusal is prompted, never fabricated from a failed check.

Pins and fixtures live only in this test.
"""

import unittest

import answer as A
from server import MODES

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


class ParseAnsweredTest(unittest.TestCase):
    def test_refusal_exact(self):
        body = A.parse_answered(REFUSAL, PASSAGES)
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)

    def test_refusal_first_line_then_more_is_still_a_refusal(self):
        body = A.parse_answered(REFUSAL + "\nAnyway, here is a guess.", PASSAGES)
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)

    def test_empty_completion_refuses(self):
        body = A.parse_answered("   \n ", PASSAGES)
        self.assertTrue(body["refused"])

    def test_tagged_sentence_cites_its_chapter(self):
        body = A.parse_answered(
            "CDC streams row-level changes from a database. [Ch. 1]", PASSAGES
        )
        self.assertFalse(body["refused"])
        self.assertEqual([c["chunk_id"] for c in body["citations"]], ["c1-001"])
        quote = body["citations"][0]["quote"]
        self.assertIn(quote, PASSAGES[0]["text"])

    def test_tag_on_the_next_line_cites_the_sentence_before_it(self):
        body = A.parse_answered(
            "CDC streams row-level changes.\n[Ch. 1]", PASSAGES
        )
        self.assertEqual([c["chunk_id"] for c in body["citations"]], ["c1-001"])

    def test_free_prose_without_tags_is_still_answered(self):
        body = A.parse_answered(
            "CDC keeps downstream systems in sync.", PASSAGES
        )
        self.assertFalse(body["refused"])
        self.assertEqual(body["answer"], "CDC keeps downstream systems in sync.")
        self.assertEqual(body["citations"], [])

    def test_fake_quote_marks_are_stripped(self):
        body = A.parse_answered(
            'CDC "streams pink unicorns from the database" each night. [Ch. 1]',
            PASSAGES,
        )
        self.assertNotIn('"', body["answer"])
        self.assertIn("pink unicorns", body["answer"])

    def test_real_quote_marks_are_kept(self):
        body = A.parse_answered(
            'The passage says "row-level changes from a database". [Ch. 1]',
            PASSAGES,
        )
        self.assertIn('"row-level changes from a database"', body["answer"])

    def test_wrong_chapter_tag_falls_back_to_overlap(self):
        body = A.parse_answered(
            "CDC streams row-level changes from a database. [Ch. 9]", PASSAGES
        )
        self.assertEqual([c["chunk_id"] for c in body["citations"]], ["c1-001"])

    def test_zero_overlap_sentence_is_uncited(self):
        body = A.parse_answered(
            "Strong chromodynamic forcefields bind quarks. [Ch. 1]", PASSAGES
        )
        self.assertFalse(body["refused"])
        self.assertEqual(body["citations"], [])

    def test_same_chunk_cited_once(self):
        body = A.parse_answered(
            "CDC streams changes. [Ch. 1] CDC keeps systems in sync. [Ch. 1]",
            PASSAGES,
        )
        self.assertEqual(len(body["citations"]), 1)


class RespondTest(unittest.TestCase):
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

    def test_answer_mode_uses_the_free_prompt_and_cites(self):
        seen = {}

        def fake_search(index, question, k=10):
            return PASSAGES

        def fake_generate(system, user, model):
            seen["system"] = system
            seen["user"] = user
            return "CDC streams row-level changes from a database. [Ch. 1]"

        body = A.respond(
            self._index(),
            "What does CDC do?",
            generate_fn=fake_generate,
            search_fn=fake_search,
        )
        self.assertFalse(body["refused"])
        self.assertIn("Not in this book.", seen["system"])
        self.assertIn("your own words", seen["system"])
        self.assertIn("chunk_id=c1-001", seen["user"])
        self.assertEqual([c["chunk_id"] for c in body["citations"]], ["c1-001"])
        self.assertIn("[Ch. 1]", body["answer"])

    def test_no_passages_refuses_without_generating(self):
        called = []

        def fake_search(index, question, k=10):
            return []

        def fake_generate(system, user, model):
            called.append(1)
            return ""

        body = A.respond(
            self._index(),
            "anything",
            generate_fn=fake_generate,
            search_fn=fake_search,
        )
        self.assertTrue(body["refused"])
        self.assertEqual(called, [])


class ModeTest(unittest.TestCase):
    def test_answer_is_a_known_mode(self):
        self.assertIn("answer", MODES)
        self.assertIn("ask", MODES)


if __name__ == "__main__":
    unittest.main()
