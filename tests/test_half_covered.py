import re
import unittest

from engine.answering import answer as A
from engine.answering.prompt import REFUSAL


def hit(chunk_id, chapter, text):
    return {"chunk_id": chunk_id, "chapter": chapter, "text": text, "score": 0.9}


DDR5 = (
    "DDR5 raises the transfer rate of each memory channel well above the "
    "previous generation used in the same servers."
)
BOTH = (
    "Batch processing runs on a schedule. "
    "Streaming processing emits each record as it arrives."
)
KAFKA = (
    "Kafka keeps a durable log of events so downstream jobs can replay them "
    "after a failure."
)


def _search(passages):
    def search(index, question, k=5):
        return passages
    return search


def _refusing(system, user, model):
    return REFUSAL


def _quoted(answer):
    return re.findall(r'["\u201c]([^"\u201c\u201d]+)["\u201d]', answer or "")


class HalfCoveredTests(unittest.TestCase):
    def setUp(self):
        self.index = {"chunks": [], "figures": []}

    def _respond(self, question, passages):
        return A.respond(
            self.index, question,
            generate_fn=_refusing, search_fn=_search(passages), model="m",
        )

    def test_one_covered_side_is_quoted_and_the_other_is_named(self):
        passages = [hit("p-mem", "6", DDR5)]
        body = self._respond("ddr4 vs ddr5", passages)
        self.assertFalse(body["refused"])
        self.assertNotEqual(body["answer"], REFUSAL)
        shown = body["answer"].split("\nAsked as:", 1)[0]
        quotes = _quoted(shown)
        self.assertTrue(quotes, body["answer"])
        folded_passage = " ".join(DDR5.split())
        for quote in quotes:
            self.assertIn(" ".join(quote.split()), folded_passage)
            self.assertNotIn("ddr4", quote.lower())
        self.assertIn("ddr4", body["answer"].lower())
        self.assertRegex(body["answer"], r"The passages do not mention ddr4\.")
        self.assertEqual([item["chunk_id"] for item in body["citations"]], ["p-mem"])
        gloss = [line for line in shown.splitlines() if line.startswith("The passages do not mention")]
        self.assertEqual(len(gloss), 1)
        self.assertNotIn('"', gloss[0])

    def test_ask_path_rescues_the_same_way(self):
        body = A.ask(
            self.index, "ddr4 vs ddr5",
            generate_fn=_refusing,
            search_fn=_search([hit("p-mem", "6", DDR5)]),
            model="m",
        )
        self.assertFalse(body["refused"])
        self.assertNotEqual(body["answer"], REFUSAL)
        self.assertIn(" ".join(_quoted(body["answer"])[0].split()), " ".join(DDR5.split()))

    def test_both_sides_covered_stays_a_refusal(self):
        body = self._respond(
            "What is the difference between batch and streaming?",
            [hit("p-both", "3", BOTH)],
        )
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)

    def test_a_why_question_is_not_a_comparison(self):
        body = self._respond(
            "why is kafka so popular?",
            [hit("p-log", "3", KAFKA)],
        )
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)

    def test_out_of_book_stays_a_refusal(self):
        body = self._respond(
            "What is the capital of France?",
            [hit("p-mem", "6", DDR5)],
        )
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)

    def test_broad_comparison_grammar_rephrasings(self):
        passages = [hit("p-mem", "6", DDR5)]
        queries = [
            "How does DDR5 stack up against DDR4?",
            "Compare DDR5 with DDR4",
            "DDR5 compared to DDR4",
            "Is DDR5 faster than DDR4?",
        ]
        for q in queries:
            with self.subTest(question=q):
                body = self._respond(q, passages)
                self.assertFalse(body["refused"], f"Should not refuse for: {q}")
                self.assertNotEqual(body["answer"], REFUSAL)
                self.assertIn("ddr4", body["answer"].lower())
                self.assertRegex(body["answer"], re.compile(r"The passages do not mention ddr4\.", re.I))


if __name__ == "__main__":
    unittest.main()
