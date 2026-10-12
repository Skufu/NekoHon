"""Post-v1 step 2 typo repair, with the retry amendment. No Ollama."""

import unittest

from answer import ask
from spelling import book_repair, correct_question

INDEX_TEXTS = (
    "CRUD, which stands for create, read, update, and delete.",
    "You stand and read a book.",
)
PASSAGE = {
    "chunk_id": "ch05-019",
    "chapter": "5",
    "heading": "CRUD",
    "text": "CRUD, which stands for create, read, update, and delete.",
    "source": "ch05",
    "score": 0.9,
}


def index_with(*texts):
    chunks = [
        {"chunk_id": f"ch{i:02d}", "chapter": "1", "text": text}
        for i, text in enumerate(texts)
    ]
    return {"chunks": chunks, "figures": []}


class CorrectQuestionTests(unittest.TestCase):
    def test_cru_repairs_to_the_top_passage_word(self):
        fixed = correct_question(
            "What does CRU stand for?", index_with(*INDEX_TEXTS), [PASSAGE]
        )
        self.assertEqual(fixed, "What does CRUD stand for?")

    def test_a_book_word_is_never_corrected(self):
        question = "What does CRUD stand for?"
        fixed = correct_question(question, index_with(*INDEX_TEXTS), [PASSAGE])
        self.assertEqual(fixed, question)

    def test_two_close_words_correct_nothing(self):
        text = "The streams and the streama sit here."
        passage = {"chunk_id": "ch01", "chapter": "1", "text": text}
        question = "Where is the streamx?"
        fixed = correct_question(
            question, index_with(text, "Where is the door?"), [passage]
        )
        self.assertEqual(fixed, question)

    def test_france_stays_below_the_cutoff(self):
        text = "The capital of Franchise is nowhere."
        passage = {"chunk_id": "ch01", "chapter": "1", "text": text}
        question = "What is the capital of France?"
        fixed = correct_question(question, index_with(text), [passage])
        self.assertEqual(fixed, question)

    def test_a_close_word_outside_the_top_passage_is_not_used(self):
        index = index_with("Find the cornerstone on some other page.")
        passage = {"chunk_id": "ch02", "chapter": "2", "text": "A house has a door."}
        question = "Find the cornerstonx"
        fixed = correct_question(question, index, [passage])
        self.assertEqual(fixed, question)


class BookRepairTests(unittest.TestCase):
    def test_book_repair_finds_the_whole_book_word(self):
        index = index_with(
            "The capital of Franchise is nowhere.",
            "A watermark marks progress in a stream.",
            "Many watermarks exist.",
        )
        fixed = book_repair("what is a atermark?", index)
        self.assertEqual(fixed, "what is a watermark?")

    def test_book_repair_leaves_ties_and_the_france_margin(self):
        tie = index_with("The streams and the streama sit here.", "Where is the door?")
        self.assertEqual(
            book_repair("where is the streamx?", tie), "where is the streamx?"
        )
        france = index_with("Speak the lingua franca of the land.")
        self.assertEqual(
            book_repair("what is the capital of france?", france),
            "what is the capital of france?",
        )


class RetryAskTests(unittest.TestCase):
    def test_retry_search_wins_when_it_is_better(self):
        weak = [
            {
                "chunk_id": "ch09-001",
                "chapter": "9",
                "text": "unrelated junk",
                "score": 0.4,
            }
        ]
        seen = {}

        def search_fn(index, question, k=5):
            if question == "What does CRU stand for?":
                return weak
            return [dict(PASSAGE, score=0.8)]

        def generate(system, user, model):
            seen["user"] = user
            return '[Ch. 5] "stands for create, read, update, and delete"'

        body = ask(
            index_with(*INDEX_TEXTS), "What does CRU stand for?", generate, search_fn
        )
        self.assertFalse(body["refused"])
        self.assertEqual(body["citations"][0]["chunk_id"], "ch05-019")
        self.assertIn("Question: What does CRUD stand for?", seen["user"])

    def test_retry_search_loses_when_it_is_not_better(self):
        def search_fn(index, question, k=5):
            if question == "What does CRU stand for?":
                return [dict(PASSAGE, score=0.9)]
            return [
                {
                    "chunk_id": "ch09-001",
                    "chapter": "9",
                    "text": "unrelated junk",
                    "score": 0.5,
                }
            ]

        def generate(system, user, model):
            return '[Ch. 5] "stands for create, read, update, and delete"'

        body = ask(
            index_with(*INDEX_TEXTS), "What does CRU stand for?", generate, search_fn
        )
        self.assertFalse(body["refused"])
        self.assertEqual(body["citations"][0]["chunk_id"], "ch05-019")

    def test_ask_searches_raw_and_prompts_corrected(self):
        seen = {"questions": []}

        def search_fn(index, question, k=5):
            seen["questions"].append(question)
            return [dict(PASSAGE, score=0.9)]

        def generate(system, user, model):
            seen["user"] = user
            return '[Ch. 5] "stands for create, read, update, and delete"'

        body = ask(
            index_with(*INDEX_TEXTS), "What does CRU stand for?", generate, search_fn
        )
        self.assertFalse(body["refused"])
        self.assertEqual(
            seen["questions"],
            ["What does CRU stand for?", "What does CRUD stand for?"],
        )
        self.assertIn("Question: What does CRUD stand for?", seen["user"])


if __name__ == "__main__":
    unittest.main()
