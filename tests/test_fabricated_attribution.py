"""A question pinned to a person no book names must refuse before generating.

Why this test exists: the bench item "What did Marcus Feld say about
quantization-aware training costs in 2036?" was answered with a real QAT
sentence. The topic is in the book, the attribution is not, and eleven extra
training rows did not change the behaviour, so the rule is mechanical.

The guards matter as much as the refusal: a real author named in the book must
not be refused, and an ordinary question must not match the pattern at all.
"""

import unittest

import answer as A

INDEX = {
    "book_id": "fde",
    "figures": [],
    "chunks": [
        {"chunk_id": "ch01-001", "chapter": "1", "heading": "Intro",
         "text": "Bezos required every team to expose data through service interfaces."},
        {"chunk_id": "ch05-034", "chapter": "5", "heading": "QAT",
         "text": "The cost of QAT is real: every forward pass computes fake quantization."},
    ],
}

PASSAGE = {"score": 0.9, "chunk_id": "ch05-034", "chapter": "5",
           "heading": "QAT", "text": INDEX["chunks"][1]["text"], "source": ""}


class AbsentPersonTest(unittest.TestCase):
    def test_absent_surname_is_detected(self):
        self.assertTrue(A.names_absent_person(
            INDEX, "What did Marcus Feld say about quantization-aware training costs in 2036?"))

    def test_title_prefix_is_skipped(self):
        self.assertTrue(A.names_absent_person(
            INDEX, "What did Dr. Helena Voss say about at-least-once delivery in 2031?"))

    def test_additional_reporting_verbs_detected(self):
        self.assertTrue(A.names_absent_person(
            INDEX, "What did Professor Gregory Vance demonstrate regarding pipeline latency?"))
        self.assertTrue(A.names_absent_person(
            INDEX, "What did Dr. Samuel Stone prove regarding distributed consensus?"))
        self.assertTrue(A.names_absent_person(
            INDEX, "What did Alice Cooper conclude about hardware accelerators?"))

    def test_present_author_is_not_flagged(self):
        self.assertFalse(A.names_absent_person(INDEX, "What did Jeff Bezos say about APIs?"))

    def test_ordinary_question_is_not_flagged(self):
        self.assertFalse(A.names_absent_person(INDEX, "What is quantization-aware training?"))
        self.assertFalse(A.names_absent_person(INDEX, "What did the authors say about QAT?"))

    def test_empty_question(self):
        self.assertFalse(A.names_absent_person(INDEX, ""))
        self.assertFalse(A.names_absent_person(INDEX, None))


class RefusesBeforeGeneratingTest(unittest.TestCase):
    def test_absent_attribution_refuses_without_an_answer_call(self):
        calls = []

        def record(system, user, model):
            calls.append(user)
            return ""

        result = A.ask(
            INDEX, "What did Marcus Feld say about QAT costs in 2036?",
            generate_fn=record,
            search_fn=lambda *args, **kwargs: [dict(PASSAGE)],
        )
        self.assertTrue(result["refused"])
        self.assertEqual(result["answer"], "Not in this book.")
        # The spelling repair may run earlier; the answer prompt must not.
        self.assertFalse(any("Passages:" in call for call in calls), calls)

    def test_respond_also_refuses(self):
        calls = []

        def record(system, user, model):
            calls.append(user)
            return ""

        result = A.respond(
            INDEX, "What did Marcus Feld say about QAT costs in 2036?",
            generate_fn=record,
            search_fn=lambda *args, **kwargs: [dict(PASSAGE)],
        )
        self.assertTrue(result["refused"])
        self.assertEqual(result["answer"], "Not in this book.")
        self.assertFalse(any("Passages:" in call for call in calls), calls)

    def test_real_question_still_reaches_the_model(self):
        seen = {"called": False}

        def generate(system, user, model):
            seen["called"] = True
            return '[Ch. 5] "The cost of QAT is real: every forward pass computes fake quantization."\n' \
                   "QAT costs real compute."

        result = A.ask(
            INDEX, "Why does QAT cost so much?",
            generate_fn=generate,
            search_fn=lambda *args, **kwargs: [dict(PASSAGE)],
        )
        self.assertTrue(seen["called"])
        self.assertFalse(result["refused"])


if __name__ == "__main__":
    unittest.main()
