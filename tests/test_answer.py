"""Phase 4 answer checks. Fake generator. No Ollama."""

import unittest

from answer import REFUSAL, ask, parse_completion

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

    def test_quote_from_the_wrong_chapter_is_a_refusal(self):
        body = parse_completion(
            '[Ch. 7] "stands for create, read, update, and delete"',
            PASSAGES,
        )
        self.assertTrue(body["refused"])

    def test_ask_sends_passages_and_keeps_the_quote(self):
        seen = {}

        def generate(system, user, model):
            seen["user"] = user
            seen["model"] = model
            return '[Ch. 5] "create, read, update, and delete"'

        body = ask({}, "What does CRUD stand for?", generate, lambda *args, **kwargs: PASSAGES)
        self.assertFalse(body["refused"])
        self.assertIn("chunk_id=ch05-019", seen["user"])
        self.assertEqual(seen["model"], "qwen2.5:7b")


if __name__ == "__main__":
    unittest.main()
