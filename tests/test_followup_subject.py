"""A follow-up must find the chunk the previous answer quoted.

The bug this guards: the index stores hard line breaks ("consistency\\r\\n
refers") and prior quotes arrive collapsed ("consistency refers"). A raw
substring test therefore missed every wrapped phrase, the prior chunk was never
seeded into the passages, and an elided follow-up ("Give me the gist.") was
answered from an unrelated chapter.

`_prior_quote_chunk` is the single lookup both seeding paths use.
"""

import unittest
from unittest import mock

import answer as A

ACID_TEXT = ("In the context of ACID, consistency\r\n refers to an "
             "application-specific notion of the database being in a “good state.”")
COMPACTION_TEXT = ("Compaction means throwing away duplicate keys in the log, "
                   "and keeping only the most recent update for each key.")
ACID_QUOTE = ("In the context of ACID, consistency refers to an "
              "application-specific notion of the database being in a “good state.”")


def index():
    return {
        "book_id": "ddia",
        "figures": [],
        "chunks": [
            {"chunk_id": "text00008-009", "chapter": "3", "heading": "Compaction",
             "text": COMPACTION_TEXT},
            {"chunk_id": "text00013-010", "chapter": "7", "heading": "Consistency",
             "text": ACID_TEXT},
        ],
    }


def history():
    return [{"question": "What does consistency mean inside ACID?",
             "answer": f'[Ch. 7] "{ACID_QUOTE}"\nIt means the data obeys the app rules.'}]


class PriorQuoteChunkTest(unittest.TestCase):
    def test_line_break_in_stored_text_still_matches(self):
        chunks = index()["chunks"]
        self.assertEqual(A._prior_quote_chunk(chunks, "7", ACID_QUOTE), 1)

    def test_chapter_match_wins_over_first_hit(self):
        chunks = [
            {"chunk_id": "a", "chapter": "3", "text": ACID_TEXT},
            {"chunk_id": "b", "chapter": "7", "text": ACID_TEXT},
        ]
        self.assertEqual(A._prior_quote_chunk(chunks, "7", ACID_QUOTE), 1)

    def test_quote_from_another_chapter_still_found(self):
        chunks = [{"chunk_id": "a", "chapter": "9", "text": ACID_TEXT}]
        self.assertEqual(A._prior_quote_chunk(chunks, "7", ACID_QUOTE), 0)

    def test_unknown_quote_returns_none(self):
        chunks = index()["chunks"]
        self.assertIsNone(A._prior_quote_chunk(chunks, "7", "a sentence no book contains"))

    def test_empty_quote_returns_none(self):
        self.assertIsNone(A._prior_quote_chunk(index()["chunks"], "7", "  "))


class ElidedFollowupSeedsTheChunkTest(unittest.TestCase):
    def test_gist_followup_puts_the_prior_chunk_first(self):
        hits = [{"score": 0.9, "chunk_id": "text00008-009", "chapter": "3",
                 "heading": "Compaction", "text": COMPACTION_TEXT, "source": ""}]
        with mock.patch.object(A, "rare", return_value=False), \
             mock.patch.object(A, "second_reading", return_value=None), \
             mock.patch.object(A, "llm_second_reading", return_value=None):
            context = A.retrieval_context(
                index(), "Give me the gist.", history=history(),
                search_fn=lambda *args, **kwargs: [dict(hit) for hit in hits])
        self.assertEqual(context["passages"][0]["chunk_id"], "text00013-010")

    def test_topic_shift_is_not_pulled_back(self):
        """A real shift must not be overridden by the prior quote."""
        hits = [{"score": 0.9, "chunk_id": "text00008-009", "chapter": "3",
                 "heading": "Compaction", "text": COMPACTION_TEXT, "source": ""}]
        with mock.patch.object(A, "rare", return_value=False), \
             mock.patch.object(A, "second_reading", return_value=None), \
             mock.patch.object(A, "llm_second_reading", return_value=None):
            context = A.retrieval_context(
                index(), "What is compaction?", history=history(),
                search_fn=lambda *args, **kwargs: [dict(hit) for hit in hits])
        self.assertEqual(context["passages"][0]["chunk_id"], "text00008-009")


if __name__ == "__main__":
    unittest.main()
