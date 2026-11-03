"""The quoted-definition note: say when the book borrows its definition.

Measured reason (2026-11-01): "what is ai" on AI Engineering answers with the
Russell and Norvig sentence the book quotes in an aside about agents. The quote
names its source, but on its own it reads as the book's position; the note says
the borrowing out loud. A definition in the author's own voice must not get it.
"""

import unittest

import answer

QUOTED = (
    "The classic book by Stuart Russell and Peter Norvig, Artificial Intelligence: "
    "A Modern Approach (Prentice Hall, 1995) defines the field of artificial "
    "intelligence research as \u201cthe study and design of rational agents.\u201d"
)
OWN = (
    "AI engineering refers to the process of building applications on top of "
    "foundation models."
)


def _body(quote, refused=False):
    return {
        "answer": f'[Ch. 6] "{quote}"\nA gloss line.',
        "citations": [{"chunk_id": "ch06-047", "chapter": "6", "quote": quote}],
        "refused": refused,
    }


class DefinitionNoteTest(unittest.TestCase):
    def test_borrowed_definition_is_named(self):
        note = answer.quoted_definition_note(
            "what is artificial intelligence", _body(QUOTED)
        )
        self.assertEqual(
            note,
            "This book does not define artificial intelligence itself; "
            "the definition above is quoted from another work.",
        )

    def test_own_voice_definition_gets_no_note(self):
        self.assertEqual(answer.quoted_definition_note("what is ai engineering", _body(OWN)), "")

    def test_first_person_definition_gets_no_note(self):
        body = _body("We define a chunk as a contiguous slice of text.")
        self.assertEqual(answer.quoted_definition_note("what is a chunk", body), "")

    def test_a_refusal_gets_no_note(self):
        body = _body(QUOTED, refused=True)
        self.assertEqual(answer.quoted_definition_note("what is artificial intelligence", body), "")

    def test_a_question_that_names_another_term_gets_no_note(self):
        self.assertEqual(answer.quoted_definition_note("what is a watermark", _body(QUOTED)), "")

    def test_a_head_starting_with_a_survives_the_article(self):
        # The old article pattern ate the first letter of a head starting with
        # "a" ("artificial" -> "rtificial"), so the reorder never saw the term.
        match = answer._DEFINITION_Q_RE.match("what is artificial intelligence")
        self.assertEqual(match.group(1), "artificial intelligence")


if __name__ == "__main__":
    unittest.main()
