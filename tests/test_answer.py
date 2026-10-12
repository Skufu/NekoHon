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

    def test_a_quote_the_paragraph_extends_expands(self):
        # Pinned to the old rule until 2026-10-12 (“quote already holds the
        # anchor, leave it”). The bake-off showed the cost: the model names
        # the question’s word and stops mid-paragraph. The paragraph wins now.
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
        self.assertIn("diabolically complicated", body["answer"].split("\n")[0])
        self.assertTrue(
            body["citations"][0]["quote"].startswith("A multicloud")
        )

    def test_a_paragraph_over_the_cap_keeps_the_quote(self):
        filler = "Filler sentence with padding words for size. " * 30
        passage = {
            "chunk_id": "ch04-001",
            "chapter": "4",
            "text": (
                "A multicloud methodology has several disadvantages. "
                "Data egress costs and networking bottlenecks are critical. "
                + filler
            ),
        }
        body = parse_completion(
            '[Ch. 4] "Data egress costs and networking bottlenecks are critical"',
            [passage],
            [],
            {"disadvantages"},
        )
        self.assertFalse(body["refused"])
        self.assertEqual(
            body["citations"][0]["quote"],
            "Data egress costs and networking bottlenecks are critical",
        )

    def test_a_paragraph_without_an_anchor_keeps_the_quote(self):
        passage = {
            "chunk_id": "ch04-002",
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
            {"watermark"},
        )
        self.assertFalse(body["refused"])
        self.assertEqual(
            body["citations"][0]["quote"],
            "Data egress costs and networking bottlenecks are critical",
        )

    def test_a_quote_missing_the_rare_word_swaps_to_the_anchor_sentence(self):
        passages = [
            {
                "chunk_id": "ch08-051",
                "chapter": "8",
                "text": (
                    "Normalization\nNormalization is a database data modeling "
                    "practice that enforces strict control over the "
                    "relationships of tables and columns."
                ),
            },
            {
                "chunk_id": "ch08-052",
                "chapter": "8",
                "text": (
                    "Normal forms\nCodd introduced the idea of normal forms. "
                    "The normal forms are sequential, each form incorporating "
                    "the conditions of prior forms."
                ),
            },
        ]
        body = parse_completion(
            '[Ch. 8] "Normalization is a database data modeling practice that '
            'enforces strict control over the relationships of tables and columns"\n'
            "Normalization = making sure tables stay consistent.",
            passages,
            [],
            None,
            "codd",
        )
        self.assertFalse(body["refused"])
        self.assertEqual(body["citations"][0]["chunk_id"], "ch08-052")
        self.assertEqual(
            body["citations"][0]["quote"],
            "Codd introduced the idea of normal forms.",
        )
        self.assertIn("Codd introduced the idea of normal forms.", body["answer"])
        self.assertNotIn("making sure", body["answer"])

    def test_the_swap_picks_the_tightest_sentence_with_the_word(self):
        passage = {
            "chunk_id": "ch08-051",
            "chapter": "8",
            "text": (
                "Normalization\nNormalization is a database practice that every "
                "engineer meets. It was first introduced by relational database "
                "pioneer Edgar Codd in the early 1970s. Codd introduced the idea "
                "of normal forms. Codd outlined four main objectives of "
                "normalization to free the collection of relations from "
                "undesirable insertion, update, and deletion dependencies."
            ),
        }
        body = parse_completion(
            '[Ch. 8] "Normalization is a database practice that every engineer meets"',
            [passage],
            [],
            None,
            "codd",
        )
        self.assertFalse(body["refused"])
        self.assertEqual(
            body["citations"][0]["quote"],
            "Codd introduced the idea of normal forms.",
        )

    def test_a_quote_holding_the_rare_word_stays(self):
        passage = {
            "chunk_id": "ch08-052",
            "chapter": "8",
            "text": (
                "Normal forms\nCodd introduced the idea of normal forms. "
                "The normal forms are sequential, each form incorporating "
                "the conditions of prior forms."
            ),
        }
        body = parse_completion(
            '[Ch. 8] "Codd introduced the idea of normal forms."',
            [passage],
            [],
            None,
            "codd",
        )
        self.assertFalse(body["refused"])
        self.assertEqual(
            body["citations"][0]["quote"],
            "Codd introduced the idea of normal forms",
        )

    def test_no_shown_passage_holding_the_rare_word_keeps_the_quote(self):
        passage = {
            "chunk_id": "ch08-051",
            "chapter": "8",
            "text": (
                "Normalization\nNormalization is a database data modeling "
                "practice that enforces strict control over the "
                "relationships of tables and columns."
            ),
        }
        body = parse_completion(
            '[Ch. 8] "Normalization is a database data modeling practice that '
            'enforces strict control over the relationships of tables and columns"',
            [passage],
            [],
            None,
            "codd",
        )
        self.assertFalse(body["refused"])
        self.assertEqual(
            body["citations"][0]["quote"],
            "Normalization is a database data modeling practice that enforces "
            "strict control over the relationships of tables and columns",
        )

    def test_a_refusal_stays_a_refusal_with_anchors(self):
        body = parse_completion(REFUSAL, PASSAGES, [], {"disadvantages"})
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)

    def test_a_disclosed_reading_skips_the_coherence_guard(self):
        padding = " ".join(
            f"Padding sentence number {n} keeps the paragraph over the cap."
            for n in range(1, 21)
        )
        chunk = {
            "chunk_id": "ch05-019",
            "chapter": "5",
            "heading": "CRUD",
            "text": (
                "CRUD, which stands for create, read, update, and delete, is a "
                "transactional pattern used in programming. " + padding
            ),
            "source": "ch05",
            "score": 0.9,
        }
        index = {"chunks": [chunk], "figures": []}
        reading = {"reading": "what does crud stand for?", "chunk": chunk}

        def fake_search(index_, question, k=5):
            return [dict(chunk)]

        def fake_generate(system, user, model):
            return '[Ch. 5] "stands for create, read, update, and delete"'

        with mock.patch("answer.second_reading", return_value=reading), \
                mock.patch("answer.fuse", side_effect=lambda *a, **k: a[2]):
            body = ask(index, "What does CRU stand for?", fake_generate, fake_search)
        self.assertFalse(body["refused"])
        self.assertEqual(
            body["citations"][0]["quote"],
            "stands for create, read, update, and delete",
        )
        self.assertIn("Read as:", body["answer"])
        self.assertNotIn("Padding", body["answer"])

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

    def test_a_question_without_a_swap_is_passed_through_verbatim(self):
        seen = {}

        def generate(system, user, model):
            seen["user"] = user
            return '[Ch. 5] "stands for create, read, update, and delete"'

        ask({}, "What does CRU stand for?", generate, lambda *args, **kwargs: PASSAGES)
        self.assertEqual(
            seen["user"].splitlines()[0], "Question: What does CRU stand for?"
        )

    def test_the_gloss_line_rides_beside_the_quote(self):
        body = parse_completion(
            '[Ch. 5] "stands for create, read, update, and delete"\n'
            'In plain words: CRUD names the four basic things you can do to data.',
            PASSAGES,
        )
        self.assertFalse(body["refused"])
        lines = body["answer"].splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith("In plain words:"))
        self.assertNotIn("In plain words", body["citations"][0]["quote"])

    def test_a_quote_that_opens_with_the_heading_line_drops_it(self):
        passage = {
            "chunk_id": "ch02-027",
            "chapter": "2",
            "heading": "Key considerations for the transformation phase",
            "text": (
                "Key considerations for the transformation phase\n"
                "Logically, we treat transformation as a standalone area of the "
                "data engineering lifecycle, but the reality is more complex."
            ),
            "source": "ch02",
            "score": 0.9,
        }
        body = parse_completion(
            '[Ch. 2] "Key considerations for the transformation phase Logically, '
            'we treat transformation as a standalone area of the data '
            'engineering lifecycle, but the reality is more complex."',
            [passage],
        )
        self.assertFalse(body["refused"])
        self.assertTrue(body["citations"][0]["quote"].startswith("Logically,"))

    def test_a_one_word_heading_stays_because_it_is_the_subject(self):
        passage = {
            "chunk_id": "ch04-069",
            "chapter": "4",
            "heading": "Modularity",
            "text": (
                "Modularity\nModularity (Figure 4-5) is an old concept in "
                "software engineering, but modular distributed systems came "
                "into vogue with the rise of microservices."
            ),
            "source": "ch04",
            "score": 0.9,
        }
        body = parse_completion(
            '[Ch. 4] "Modularity (Figure 4-5) is an old concept in software '
            'engineering, but modular distributed systems came into vogue with '
            'the rise of microservices."',
            [passage],
        )
        self.assertFalse(body["refused"])
        self.assertTrue(body["citations"][0]["quote"].startswith("Modularity"))

    def test_a_figure_from_an_uncited_passage_is_not_attached(self):
        cited = {
            "chunk_id": "ch04-020",
            "chapter": "4",
            "heading": "Today Versus the Future",
            "text": (
                "Today Versus the Future\nJust consider the number of "
                "technologies in the MAD landscape (Figure 4-1)."
            ),
            "source": "ch04",
            "score": 0.9,
        }
        rider = {
            "chunk_id": "ch03-102",
            "chapter": "3",
            "heading": "Data Mesh",
            "text": "Data Mesh\nThe data mesh is a recent response (Figure 3-18).",
            "source": "ch03",
            "score": 0.6,
        }
        figures = [
            {"id": "figure-4-1", "chapter": "4", "caption": "MAD", "file": "fode_0401.png"},
            {"id": "figure-3-18", "chapter": "3", "caption": "Mesh", "file": "fode_0318.png"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "fode_0401.png").write_bytes(b"png")
            Path(tmp, "fode_0318.png").write_bytes(b"png")
            with mock.patch("figures.FIGURES", Path(tmp)):
                body = parse_completion(
                    '[Ch. 4] "Just consider the number of technologies in the '
                    'MAD landscape (Figure 4-1)."',
                    [cited, rider],
                    figures,
                )
        self.assertFalse(body["refused"])
        self.assertEqual([item["id"] for item in body["figures"]], ["figure-4-1"])


if __name__ == "__main__":
    unittest.main()
