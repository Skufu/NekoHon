"""Phase 4 answer checks. Fake generator. No Ollama."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from answer import REFUSAL, ask, explain, parse_completion, quiz

PASSAGES = [
    {
        "chunk_id": "ch05-019",
        "chapter": "5",
        "heading": "CRUD",
        "text": "CRUD, which stands for create, read, update, and delete, is a transactional pattern.",
        "source": "ch05",
        "score": 0.9,
    },
    {
        "chunk_id": "ch07-002",
        "chapter": "7",
        "heading": "What Is Data Ingestion?",
        "text": "Data ingestion is the process of moving data from one place to another.",
        "source": "ch07",
        "score": 0.2,
    },
]


class AnswerTests(unittest.TestCase):
    def test_quote_must_be_in_the_passage(self):
        body = parse_completion(
            '[Ch. 5] "stands for create, read, update, and delete"\nCRUD names four database operations.',
            PASSAGES,
        )
        self.assertFalse(body["refused"])
        self.assertTrue(body["answer"].startswith("[Ch. 5]"))
        self.assertEqual(body["citations"][0]["chunk_id"], "ch05-019")
        self.assertEqual(body["figures"], [])
        self.assertIn("stands for create, read, update, and delete", body["citations"][0]["quote"])

    def test_words_after_the_quote_are_not_part_of_the_quote(self):
        body = parse_completion(
            '[Ch. 5] "stands for create, read, update, and delete" and then some extra words.',
            PASSAGES,
        )
        self.assertFalse(body["refused"])
        self.assertEqual(body["citations"][0]["quote"], "stands for create, read, update, and delete")
        self.assertNotIn("extra words", body["citations"][0]["quote"])

    def test_a_dropped_clause_keeps_the_copied_span(self):
        body = parse_completion(
            "[Ch. 5] CRUD stands for create, read, update, and delete.",
            PASSAGES,
        )
        self.assertFalse(body["refused"])
        self.assertEqual(
            body["citations"][0]["quote"],
            "stands for create, read, update, and delete",
        )
        self.assertNotIn(", which", body["citations"][0]["quote"])
        self.assertEqual(body["citations"][0]["chunk_id"], "ch05-019")

    def test_a_short_overlap_is_still_a_refusal(self):
        body = parse_completion(
            "[Ch. 5] transactional",
            PASSAGES,
        )
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)

    def test_invented_quote_is_a_refusal(self):
        body = parse_completion(
            '[Ch. 5] "CRUD stores data in the cloud and never loses a row."',
            PASSAGES,
        )
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)

    def test_essay_is_a_refusal(self):
        body = parse_completion(
            "CRUD stands for create, read, update, and delete.",
            PASSAGES,
        )
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)

    def test_refusal_must_be_exact(self):
        body = parse_completion("Not in this book. Here is an essay.", PASSAGES)
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)
        exact = parse_completion(REFUSAL, PASSAGES)
        self.assertTrue(exact["refused"])
        self.assertEqual(exact["answer"], REFUSAL)
        self.assertEqual(exact["citations"][0]["chunk_id"], "ch05-019")

    def test_a_wrong_chapter_tag_still_finds_the_real_passage(self):
        body = parse_completion(
            '[Ch. 7] "stands for create, read, update, and delete"',
            PASSAGES,
        )
        self.assertFalse(body["refused"])
        self.assertEqual(body["citations"][0]["chunk_id"], "ch05-019")
        self.assertTrue(body["answer"].startswith("[Ch. 5]"))

    def test_a_wrong_chapter_tag_on_an_unattached_quote_still_refuses(self):
        body = parse_completion(
            '[Ch. 7] "CRUD stores data in the cloud and never loses a row."',
            PASSAGES,
        )
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)

    def test_ask_sends_passages_and_keeps_the_quote(self):
        seen = {}

        def generate(system, user, model):
            seen["user"] = user
            seen["model"] = model
            return '[Ch. 5] "stands for create, read, update, and delete"'

        body = ask({}, "What does CRUD stand for?", generate, lambda *args, **kwargs: PASSAGES)
        self.assertFalse(body["refused"])
        self.assertIn("chunk_id=ch05-019", seen["user"])
        self.assertIn("Do not reword it.", seen["user"])
        self.assertFalse(seen["user"].rstrip().endswith(REFUSAL))
        self.assertEqual(seen["model"], "qwen2.5:7b")

    def test_explain_uses_the_selection_as_the_question(self):
        seen = {}

        def generate(system, user, model):
            seen["user"] = user
            return '[Ch. 5] "stands for create, read, update, and delete"'

        body = explain(
            {},
            "CRUD stands for create, read, update, and delete",
            generate,
            lambda *args, **kwargs: PASSAGES,
        )
        self.assertFalse(body["refused"])
        self.assertIn("CRUD stands for create, read, update, and delete", seen["user"])

    def test_a_refusal_can_still_carry_the_nearby_figure(self):
        passage = {
            "chunk_id": "ch08-040",
            "chapter": "8",
            "heading": "Watermarks",
            "text": "A watermark (Figure 8-8) is a threshold used by a window.",
            "source": "ch08",
            "score": 0.8,
        }
        figure = {
            "id": "figure-8-8",
            "chapter": "8",
            "caption": "A watermark marks late data.",
            "file": "fode_0808.png",
        }
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "fode_0808.png").write_bytes(b"png")
            with mock.patch("figures.FIGURES", Path(tmp)):
                body = parse_completion(REFUSAL, [passage], [figure])
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)
        self.assertEqual([item["id"] for item in body["figures"]], ["figure-8-8"])

    def test_two_quotes_from_one_passage_are_both_kept(self):
        body = parse_completion(
            '[Ch. 5] "stands for create, read, update, and delete"\n'
            '[Ch. 5] "which stands for create, read, update, and delete"',
            PASSAGES,
        )
        self.assertFalse(body["refused"])
        self.assertEqual(len(body["citations"]), 2)
        self.assertEqual({c["chunk_id"] for c in body["citations"]}, {"ch05-019"})
        self.assertEqual(body["answer"].count("[Ch. 5]"), 2)

    def test_a_paragraph_holding_more_anchors_expands(self):
        passage = {
            "chunk_id": "ch04-038",
            "chapter": "4",
            "text": (
                "Multicloud\nprovider services is possible.\n\n"
                "A multicloud methodology has several disadvantages. "
                "Data egress costs and networking bottlenecks are critical. "
                "Multicloud networking can be diabolically complicated.\n\n"
                "A new generation of services follows."
            ),
        }
        body = parse_completion(
            '[Ch. 4] "Data egress costs and networking bottlenecks are critical"',
            [passage],
            [],
            {"disadvantages"},
        )
        self.assertFalse(body["refused"])
        self.assertIn("A multicloud methodology has several disadvantages", body["answer"])
        self.assertIn("diabolically complicated", body["answer"])
        self.assertTrue(
            body["citations"][0]["quote"].startswith("A multicloud methodology")
        )

    def test_a_sentence_that_already_holds_the_anchor_stays(self):
        passage = {
            "chunk_id": "ch04-038",
            "chapter": "4",
            "text": (
                "A multicloud methodology has several disadvantages. "
                "Data egress costs and networking bottlenecks are critical. "
                "Multicloud networking can be diabolically complicated."
            ),
        }
        body = parse_completion(
            '[Ch. 4] "Data egress costs and networking bottlenecks are critical"',
            [passage],
            [],
            {"egress"},
        )
        self.assertFalse(body["refused"])
        self.assertNotIn("diabolically complicated", body["answer"].split("\n")[0])

    def test_a_refusal_stays_a_refusal_with_anchors(self):
        body = parse_completion(REFUSAL, PASSAGES, [], {"disadvantages"})
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)

    def test_quiz_hides_the_key_from_the_question(self):
        chunk = {
            "chunk_id": "ch05-019",
            "chapter": "5",
            "text": PASSAGES[0]["text"],
        }

        def generate(system, user, model):
            return "Which four operations does CRUD name?"

        body = quiz({"chunks": [chunk], "figures": []}, generate, chunk=chunk)
        self.assertFalse(body["refused"])
        self.assertNotIn(body["citations"][0]["quote"].lower(), body["answer"].lower())
        self.assertEqual(body["citations"][0]["chunk_id"], "ch05-019")

    def test_quiz_leaking_the_key_is_a_refusal(self):
        chunk = {
            "chunk_id": "ch05-019",
            "chapter": "5",
            "text": "CRUD, which stands for create, read, update, and delete, is a transactional pattern.",
        }

        def generate(system, user, model):
            return chunk["text"]

        body = quiz({"chunks": [chunk], "figures": []}, generate, chunk=chunk)
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)

    def test_a_dropped_figure_reference_keeps_the_whole_quote(self):
        passage = {
            "chunk_id": "ch06-001",
            "chapter": "6",
            "heading": "Chapter 6. Storage",
            "text": (
                "Chapter 6. Storage\nStorage is the cornerstone of the data "
                "engineering lifecycle (Figure 6-1) and underlies its major "
                "stages\u2014ingestion, transformation, and serving."
            ),
            "source": "ch06",
            "score": 0.9,
        }
        body = parse_completion(
            '[Ch. 6] "Storage is the cornerstone of the data engineering '
            'lifecycle and underlies its major stages\u2014ingestion, '
            'transformation, and serving."',
            [passage],
        )
        self.assertFalse(body["refused"])
        self.assertTrue(
            body["citations"][0]["quote"].startswith("Storage is the cornerstone")
        )
        self.assertIn("underlies its major stages", body["citations"][0]["quote"])

    def test_a_kept_figure_reference_still_matches(self):
        passage = {
            "chunk_id": "ch08-040",
            "chapter": "8",
            "heading": "Watermarks",
            "text": "Watermarks\nA watermark (Figure 8-8) is a threshold used by a window.",
            "source": "ch08",
            "score": 0.9,
        }
        body = parse_completion(
            '[Ch. 8] "A watermark (Figure 8-8) is a threshold used by a window."',
            [passage],
        )
        self.assertFalse(body["refused"])
        self.assertEqual(body["citations"][0]["chunk_id"], "ch08-040")

    def test_a_fabricated_quote_is_still_a_refusal_next_to_a_figure(self):
        passage = {
            "chunk_id": "ch06-001",
            "chapter": "6",
            "heading": "Chapter 6. Storage",
            "text": (
                "Chapter 6. Storage\nStorage is the cornerstone of the data "
                "engineering lifecycle (Figure 6-1) and underlies its major "
                "stages\u2014ingestion, transformation, and serving."
            ),
            "source": "ch06",
            "score": 0.9,
        }
        body = parse_completion(
            '[Ch. 6] "Storage is the least important part of the data '
            'engineering lifecycle."',
            [passage],
        )
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)


if __name__ == "__main__":
    unittest.main()
