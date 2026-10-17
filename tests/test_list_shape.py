"""A list question must quote the items, not only the lead-in. No Ollama.

The model's quote is the colon sentence that introduces the list. The repair
moves the shown passage's own following text into that quote. A question that
is not a list ask leaves a colon sentence alone.
"""

import unittest

import answer as A
from prompt import REFUSAL


def hit(chunk_id, chapter, text):
    return {"chunk_id": chunk_id, "chapter": chapter, "text": text, "score": 0.9}


LEAD = "The following are factors to consider with a community-managed project:"
ITEMS = (
    "Traction shows whether other teams already depend on it. "
    "Public contributors show who maintains the code. "
    "A published roadmap shows where the project is going."
)
PASSAGE = f"{LEAD}\n{ITEMS}"
LEAD_ONLY = "The following are factors to consider with a community-managed project:"
COLON = "The signal name is written as follows: Northline gate seven, yard office."


def _search(passages):
    def search(index, question, k=5):
        return passages
    return search


def _quoting(quote, chapter="4"):
    def generate(system, user, model):
        return f'[Ch. {chapter}] "{quote}"\nA short gloss that does not list them.'
    return generate


class ListShapeTests(unittest.TestCase):
    def setUp(self):
        self.index = {"chunks": [], "figures": []}

    def _body(self, question, passages, quote, chapter="4", mode="respond"):
        fn = A.respond if mode == "respond" else A.ask
        return fn(
            self.index, question,
            generate_fn=_quoting(quote, chapter),
            search_fn=_search(passages),
            model="m",
        )

    def test_list_question_quotes_the_items_not_only_the_lead_in(self):
        passages = [hit("p-list", "4", PASSAGE)]
        question = "What are the following factors to consider with a community-managed project"
        for mode in ("respond", "ask"):
            with self.subTest(mode=mode):
                body = self._body(question, passages, LEAD, mode=mode)
                self.assertFalse(body["refused"])
                self.assertNotEqual(body["answer"], REFUSAL)
                folded = " ".join(body["answer"].split())
                self.assertIn("Traction shows whether other teams already depend on it.", folded)
                self.assertIn("Public contributors show who maintains the code.", folded)
                self.assertIn("A published roadmap shows where the project is going.", folded)
                self.assertIn(" ".join(body["citations"][0]["quote"].split()), " ".join(PASSAGE.split()))

    def test_a_non_list_colon_sentence_is_not_expanded(self):
        passages = [hit("p-colon", "2", COLON + " It marks the boundary of the yard.")]
        body = self._body(
            "When was the signal name written down?",
            passages,
            COLON,
            chapter="2",
        )
        self.assertFalse(body["refused"])
        self.assertIn(COLON, body["answer"])
        self.assertNotIn("It marks the boundary of the yard.", body["answer"])

    def test_items_after_a_blank_line_replace_the_lead_in(self):
        passage = f"{LEAD}\n\n{ITEMS}"
        body = self._body(
            "What are the following factors to consider with a community-managed project",
            [hit("p-blank", "4", passage)],
            LEAD,
        )
        folded = " ".join(body["answer"].split())
        self.assertIn("Traction shows whether other teams already depend on it.", folded)
        self.assertNotIn(LEAD, body["answer"])

    def test_a_list_question_with_no_continuation_keeps_the_lead_in(self):
        passages = [hit("p-bare", "4", LEAD_ONLY)]
        body = self._body(
            "What are the following factors to consider with a community-managed project",
            passages,
            LEAD_ONLY,
        )
        self.assertFalse(body["refused"])
        self.assertIn(LEAD_ONLY, body["answer"])
        self.assertEqual(body["citations"][0]["quote"], LEAD_ONLY)


if __name__ == "__main__":
    unittest.main()
