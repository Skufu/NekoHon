"""A question whose every content word is absent from the book refuses before generating.

Why this test exists: "what is fsm" against AI Engineering was answered with a
finetuning sentence. The book never writes "fsm" or "finite state machine" (0
chunks), but dense search still returned five passages inside a 0.007 score
band, so every passage looked equally good; the lexical channel had nothing to
add, and the acronym guard never fired because the reader typed it lowercase.

The guard is deliberately weak — one content word anywhere in the book keeps
the question — so the tests also pin what must NOT refuse: a paraphrase that
shares a single vocabulary word, a follow-up with history, and the empty string.
"""

import unittest

import answer as A

INDEX = {
    "book_id": "quantization",
    "figures": [],
    "chunks": [
        {"chunk_id": "ch01-001", "chapter": "1", "heading": "Intro",
         "text": "Quantization stores weights in fewer bits, at a measurable cost."},
        {"chunk_id": "ch02-010", "chapter": "2", "heading": "Group size",
         "text": "A smaller group size keeps more scale factors and improves accuracy."},
    ],
}

PASSAGE = {"score": 0.9, "chunk_id": "ch01-001", "chapter": "1",
           "heading": "Intro", "text": INDEX["chunks"][0]["text"], "source": ""}


class VocabularyGuardTest(unittest.TestCase):
    def test_unknown_acronym_is_detected(self):
        self.assertTrue(A.has_no_book_vocabulary(INDEX, "what is fsm"))

    def test_one_shared_word_keeps_the_question(self):
        self.assertFalse(A.has_no_book_vocabulary(INDEX, "what is fsm in quantization"))
        self.assertFalse(A.has_no_book_vocabulary(INDEX, "does group size matter for fsm"))

    def test_stem_match_keeps_the_question(self):
        self.assertFalse(A.has_no_book_vocabulary(INDEX, "how are weights quantized"))

    def test_framing_words_alone_do_not_keep_it(self):
        self.assertTrue(A.has_no_book_vocabulary(INDEX, "what is the difference"))

    def test_empty_question(self):
        self.assertFalse(A.has_no_book_vocabulary(INDEX, ""))
        self.assertFalse(A.has_no_book_vocabulary(INDEX, None))
        self.assertFalse(A.has_no_book_vocabulary({}, "what is fsm"))


class UncoveredSubjectTest(unittest.TestCase):
    """A definitional question about a phrase the book never writes.

    Measured 2026-11-01: "what is data engineering" against the quantization
    book was answered with an invented definition. Both words appear somewhere,
    so the word-level guard passes; the phrase does not appear at all (0 of 473
    chunks).
    """

    def test_absent_two_word_subject_refuses(self):
        self.assertTrue(A.has_uncovered_subject(INDEX, "what is data engineering"))

    def test_absent_three_word_subject_refuses(self):
        self.assertTrue(A.has_uncovered_subject(INDEX, "what is an agent reasoning engine"))

    def test_present_subject_is_kept(self):
        self.assertFalse(A.has_uncovered_subject(INDEX, "what is group size"))
        self.assertFalse(A.has_uncovered_subject(INDEX, "what is a group size"))

    def test_a_single_word_subject_is_not_checked(self):
        # The word-level guard already owns single terms, and one-word topics
        # are the ones most often paraphrased.
        self.assertFalse(A.has_uncovered_subject(INDEX, "what is quantization"))

    def test_a_framed_question_is_never_refused_on_its_phrase(self):
        self.assertFalse(
            A.has_uncovered_subject(INDEX, "what are the stages of the data engineering lifecycle")
        )

    def test_empty_question(self):
        self.assertFalse(A.has_uncovered_subject(INDEX, ""))
        self.assertFalse(A.has_uncovered_subject(INDEX, None))
        self.assertFalse(A.has_uncovered_subject({}, "what is data engineering"))


class RefusesBeforeGeneratingTest(unittest.TestCase):
    def test_ask_refuses_without_an_answer_call(self):
        calls = []

        def record(system, user, model, **kwargs):
            calls.append(user)
            return ""

        result = A.ask(
            INDEX, "what is fsm",
            generate_fn=record,
            search_fn=lambda *args, **kwargs: [dict(PASSAGE)],
        )
        self.assertTrue(result["refused"])
        self.assertEqual(result["answer"], "Not in this book.")
        self.assertFalse(any("Passages:" in call for call in calls), calls)

    def test_respond_refuses_without_an_answer_call(self):
        calls = []

        def record(system, user, model, **kwargs):
            calls.append(user)
            return ""

        result = A.respond(
            INDEX, "what is fsm",
            generate_fn=record,
            search_fn=lambda *args, **kwargs: [dict(PASSAGE)],
        )
        self.assertTrue(result["refused"])
        self.assertEqual(result["answer"], "Not in this book.")
        self.assertFalse(any("Passages:" in call for call in calls), calls)

    def test_follow_up_is_not_gated(self):
        calls = []

        def record(system, user, model, **kwargs):
            calls.append(user)
            return 'Quantization stores weights in fewer bits. [Ch. 1]'

        result = A.respond(
            INDEX, "Why is it risky?",
            history=[{"question": "What is quantization?",
                      "answer": 'Quantization stores weights in fewer bits. [Ch. 1]'}],
            generate_fn=record,
            search_fn=lambda *args, **kwargs: [dict(PASSAGE)],
        )
        self.assertFalse(result["refused"])
        self.assertTrue(any("Passages:" in call for call in calls), calls)


FIGURE_INDEX = {
    "book_id": "fde",
    "chunks": [
        {"chunk_id": "ch02-002", "chapter": "2", "heading": "Lifecycle",
         "text": "We divide the data engineering lifecycle into five stages (Figure 2-1, top):"},
        {"chunk_id": "ch08-017", "chapter": "8", "heading": "Query plans",
         "text": "Use the explain plan to understand how the optimizer runs a query."},
    ],
    "figures": [
        {"id": "figure-2-1", "chapter": "2", "caption": "Components of the lifecycle",
         "referencing_paragraph": "We divide the data engineering lifecycle into five stages (Figure 2-1, top):",
         "file": "figure-2-1.png"},
    ],
}


class FigureQuestionTest(unittest.TestCase):
    """A question naming a figure resolves to the book's words about it.

    The figures were never shipped as image files, so `figures` comes back
    empty; the text that introduces the figure is still in the index and is
    what the answer must quote.
    """

    def test_a_named_figure_resolves_to_its_referencing_chunk(self):
        chunk = A._figure_referencing_chunk(FIGURE_INDEX, "what does figure 2-1 show")
        self.assertEqual(chunk["chunk_id"], "ch02-002")

    def test_a_dotted_number_also_resolves(self):
        self.assertEqual(A._named_figure_id("explain Figure 2.1"), "figure-2-1")

    def test_a_figure_the_book_lacks_is_unknown(self):
        self.assertTrue(A.names_unknown_figure(FIGURE_INDEX, "what does figure 9-9 show"))

    def test_a_question_without_a_figure_is_not_checked(self):
        self.assertFalse(A.names_unknown_figure(FIGURE_INDEX, "what is a watermark"))
        self.assertIsNone(A._figure_referencing_chunk(FIGURE_INDEX, "what is a watermark"))


if __name__ == "__main__":
    unittest.main()
