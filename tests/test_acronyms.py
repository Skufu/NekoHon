"""Acronym spelling: a short head term is asked with the book's own words.

Measured reason (2026-11-01): "what is ai" ranked its whole top five inside
0.006 and answered from an SEO content-farm passage; "what is artificial
intelligence" leads with the chunk that defines the term.
"""

import unittest

import acronyms


def _index(*texts):
    return {"chunks": [{"text": text} for text in texts]}


class SpellingsTest(unittest.TestCase):
    def test_capitalised_run_names_the_acronym(self):
        index = _index("Artificial Intelligence: A Modern Approach defines the field.")
        self.assertEqual(acronyms.spellings(index)["ai"], "artificial intelligence")

    def test_parenthetical_names_the_acronym(self):
        index = _index("Customer relationship management (CRM) apps hold the record.")
        self.assertEqual(
            acronyms.spellings(index)["crm"], "customer relationship management"
        )

    def test_function_words_are_not_a_spelling(self):
        index = _index("And I went home. An Introduction follows.")
        self.assertNotIn("ai", acronyms.spellings(index))

    def test_most_repeated_spelling_wins(self):
        index = _index(
            "Artificial Intelligence is broad.",
            "Artificial Intelligence is old.",
            "Agents Incubate.",
        )
        self.assertEqual(acronyms.spellings(index)["ai"], "artificial intelligence")


class ExpandTest(unittest.TestCase):
    def test_definitional_ask_is_spelled_out(self):
        index = _index("Artificial Intelligence: A Modern Approach.")
        self.assertEqual(
            acronyms.expand(index, "what is ai"), "what is artificial intelligence"
        )

    def test_question_mark_survives(self):
        index = _index("Customer relationship management (CRM) apps hold the record.")
        self.assertEqual(
            acronyms.expand(index, "what is crm?"),
            "what is customer relationship management?",
        )

    def test_a_longer_ask_is_left_alone(self):
        index = _index("Artificial Intelligence: A Modern Approach.")
        self.assertIsNone(acronyms.expand(index, "what is ai engineering"))

    def test_an_unknown_head_is_left_alone(self):
        index = _index("Artificial Intelligence: A Modern Approach.")
        self.assertIsNone(acronyms.expand(index, "what is a watermark"))


if __name__ == "__main__":
    unittest.main()
