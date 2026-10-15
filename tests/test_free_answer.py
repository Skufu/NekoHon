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

    def test_two_chapter_tag_still_cites(self):
        # The mask clears the period in the tag's second "Ch."; a split inside
        # the mask would drop the claim and empty the citations.
        body = A.parse_answered(
            "The endpoint streams data straight past a database [Ch. 2, Ch. 7].",
            PASSAGES,
        )
        self.assertFalse(body["refused"])
        self.assertEqual([c["chunk_id"] for c in body["citations"]], ["c1-001"])

    def test_mid_sentence_span_expands_to_the_whole_sentence(self):
        # The copied run starts mid-sentence; the quote is the sentence that
        # holds it, never the bare run (a lowercase fragment).
        body = A.parse_answered(
            "The CDC approach focuses on row-level changes from a database "
            "so downstream systems stay in sync. [Ch. 1]",
            PASSAGES,
        )
        self.assertEqual(
            body["citations"][0]["quote"],
            "Change data capture (CDC) streams row-level changes from a "
            "database so downstream systems stay in sync.",
        )

    def test_span_outside_any_sentence_keeps_the_old_run(self):
        # The only sentence holding the run is under KEY_MIN_CHARS, so the
        # sentence list drops it; the run itself is the fallback.
        short = [hit("c9-009", "9", "Sync note\nrow-level changes from a database")]
        body = A.parse_answered(
            "The approach focuses on row-level changes from a database here. [Ch. 9]",
            short,
        )
        self.assertIn("row-level changes from a database", body["citations"][0]["quote"])

    def test_footnote_glue_does_not_merge_into_the_next_sentence(self):
        # "Maxime Beauchemin4" has no sentence end, so the attribution used to
        # run into the next sentence; the split drops the attribution piece
        # and the quote is the definition itself.
        glued = hit(
            "c1-003",
            "1",
            "What Is Data Engineering?\nMaxime Beauchemin4\n\n"
            "Data engineering is all about the movement, manipulation, and "
            "management of data. Lewis Gavin5",
        )
        quote = A._evidence_quote(
            "Data engineering deals with the movement, manipulation, and "
            "management of data.",
            glued,
        )
        self.assertEqual(
            quote,
            "Data engineering is all about the movement, manipulation, and "
            "management of data.",
        )


    def test_a_stray_run_does_not_beat_the_defining_sentence(self):
        # Measured 2026-10-13 on "explain data engineering in simple words":
        # the draft paraphrased ch01-005's definition, but its longest copied
        # run ("by data scientists, analysts, and other", 41 chars) sits in
        # the enumeration sentence, so the quote -- and with it the plain
        # register's rewrite source -- was the enumeration. The quote must be
        # the sentence the claim overlaps most, span or no span.
        chunk = hit(
            "c1-004",
            "1",
            "Data Engineering Defined\n"
            "When we unpack the common threads of how various people define "
            "data engineering, an obvious pattern emerges: a data engineer "
            "gets data, stores it, and prepares it for consumption by data "
            "scientists, analysts, and others. We define data engineering and "
            "data engineer as follows: Data engineering is the development, "
            "implementation, and maintenance of systems and processes that "
            "take in raw data and produce high-quality, consistent "
            "information that supports downstream use cases.",
        )
        quote = A._evidence_quote(
            "Data engineering involves developing, implementing, and "
            "maintaining systems and processes that handle raw data, "
            "transforming it into high-quality, consistent information for "
            "use by data scientists, analysts, and other stakeholders.",
            chunk,
        )
        self.assertTrue(quote.startswith("We define data engineering"), quote)


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
        # 2026-10-15 prompt alignment: answer mode serves the ask-shaped
        # prompt (the student is trained on it); it used to ask for "your
        # own words", which the student followed when not over-memorized.
        self.assertIn("Quote first.", seen["system"])
        self.assertIn("Copy one sentence from a passage", seen["user"])
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

    def test_plain_register_rewrites_the_whole_sentence(self):
        # A citation quote can never be a bare copied run, so the rewriter is
        # never asked to rewrite a fragment into a fragment.
        seen = []

        def fake_search(index, question, k=10):
            return PASSAGES

        def fake_generate(system, user, model):
            if system == A.PARAPHRASE_SYSTEM:
                seen.append(user)
                return "CDC sends changes downstream."
            return (
                "The CDC approach focuses on row-level changes from a "
                "database so downstream systems stay in sync. [Ch. 1]"
            )

        A.respond(
            self._index(),
            "what is CDC in simple words?",
            generate_fn=fake_generate,
            search_fn=fake_search,
        )
        self.assertEqual(
            seen,
            [
                "Sentence: Change data capture (CDC) streams row-level changes "
                "from a database so downstream systems stay in sync."
            ],
        )


    def test_an_uncited_answer_gets_one_prefilled_retry(self):
        calls = []

        def fake_search(index, question, k=10):
            return PASSAGES

        def fake_generate(system, user, model, prefill=""):
            if user.startswith('User query: "'):
                return "keep in sync"  # the spell probe: not a same-count fix
            calls.append(prefill)
            if prefill:
                return '1] "streams row-level changes from a database"'
            return "CDC keeps downstream systems in sync."

        body = A.respond(
            self._index(),
            "What does CDC do?",
            generate_fn=fake_generate,
            search_fn=fake_search,
        )
        self.assertFalse(body["refused"])
        self.assertEqual(calls, ["", "[Ch. "])
        self.assertEqual([c["chunk_id"] for c in body["citations"]], ["c1-001"])
        self.assertTrue(body["answer"].startswith("[Ch. 1]"))

    def test_the_retry_is_kept_only_when_a_quote_validates(self):
        def fake_search(index, question, k=10):
            return PASSAGES

        def fake_generate(system, user, model, prefill=""):
            if prefill:
                return "is complicated."
            return "CDC keeps downstream systems in sync."

        body = A.respond(
            self._index(),
            "What does CDC do?",
            generate_fn=fake_generate,
            search_fn=fake_search,
        )
        self.assertFalse(body["refused"])
        self.assertEqual(body["citations"], [])
        self.assertIn("downstream systems in sync", body["answer"])

    def test_a_refusal_is_not_retried_in_answer_mode(self):
        calls = []

        def fake_search(index, question, k=10):
            return PASSAGES

        def fake_generate(system, user, model, prefill=""):
            if user.startswith('User query: "'):
                return "what does cdc do?"  # the spell probe: no change
            calls.append(prefill)
            return REFUSAL

        body = A.respond(
            self._index(),
            "What does CDC do?",
            generate_fn=fake_generate,
            search_fn=fake_search,
        )
        self.assertTrue(body["refused"])
        self.assertEqual(calls, [""])

    def test_a_generator_without_prefill_support_keeps_the_answer(self):
        def fake_search(index, question, k=10):
            return PASSAGES

        def fake_generate(system, user, model):
            return "CDC keeps downstream systems in sync."

        body = A.respond(
            self._index(),
            "What does CDC do?",
            generate_fn=fake_generate,
            search_fn=fake_search,
        )
        self.assertFalse(body["refused"])
        self.assertEqual(body["citations"], [])


class ModeTest(unittest.TestCase):
    def test_answer_is_a_known_mode(self):
        self.assertIn("answer", MODES)
        self.assertIn("ask", MODES)


if __name__ == "__main__":
    unittest.main()
