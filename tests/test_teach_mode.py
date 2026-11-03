"""Mode "teach": explain a stuck paragraph in plain words, with one example.

The reader's use: they are stuck on a section, so they ask for it in simple
words with an example. The quote contract is deliberately not in force here —
the explanation is the model's own prose and the example is its own illustration
— but the honesty rules are: the refusal sentence is exact, the reader is told
the example is not the book's, and nothing the book cannot support is attached
as a citation.
"""

import unittest

import answer as A
import server
from prompt import REFUSAL, SPELL_SYSTEM, TEACH_EXAMPLE_SYSTEM, TEACH_SYSTEM


def chunk(chunk_id, chapter, text, heading=""):
    return {
        "chunk_id": chunk_id,
        "chapter": chapter,
        "heading": heading,
        "text": text,
        "source": f"section-{chapter}",
        "score": 0.9,
    }


PASSAGES = [
    chunk("c1", "3",
          "In a B-tree, every modification is first written to a write-ahead log "
          "so that the index can be restored to a consistent state after a crash. "
          "The log is an append-only sequence of bytes containing all writes."),
    chunk("c2", "3",
          "A log-structured engine keeps data in an append-only file and compacts "
          "segments in the background."),
]


def index_of(chunks=None):
    return {
        "book_id": "a-tech-book",
        "title": "A Technical Book",
        "author": "Someone",
        "chunks": [dict(item) for item in (chunks or PASSAGES)],
        "figures": [],
    }


EXPLANATION = (
    "In plain words, a write-ahead log is a safety record. Every change is "
    "written there before it is applied to the main data. If the machine dies "
    "in between, the record is replayed on startup."
)


class ExplainShapeTest(unittest.TestCase):
    def test_the_explanation_and_the_example_survive(self):
        example = "Before saving a change, you note it in a diary first, then copy it into the ledger."
        explanation = EXPLANATION.replace("In plain words, ", "", 1)
        body, status = A.build_teach_body(
            EXPLANATION, "Example: " + example, PASSAGES, [], question="what is a write-ahead log",
        )
        self.assertEqual(status, "cited")
        self.assertFalse(body["refused"])
        self.assertIn(explanation[1:60], body["answer"])  # the cleaner capitalises
        self.assertIn("Example: " + example, body["answer"])
        self.assertTrue(body["citations"])

    def test_the_example_is_labelled_exactly_once(self):
        body, _ = A.build_teach_body(
            EXPLANATION, "Example: Example: you note the change in a diary first.",
            PASSAGES, [],
        )
        self.assertEqual(body["answer"].count("Example:"), 1)

    def test_an_example_that_repeats_the_explanation_is_dropped(self):
        explanation = "A write-ahead log records each change before it is applied."
        body, status = A.build_teach_body(
            explanation, explanation, PASSAGES, [],
        )
        self.assertEqual(status, "no_example")
        self.assertNotIn("Example:", body["answer"])

    def test_a_figure_number_prefix_is_removed_and_a_fragment_is_rejected(self):
        body, status = A.build_teach_body(
            "In plain words, 1.0 A write-ahead log records each change first.", "", PASSAGES, [],
        )
        self.assertNotIn("1.0", body["answer"])
        self.assertFalse(body["refused"])
        body, status = A.build_teach_body("In plain words, 8-8-8 is a rule here", "", PASSAGES, [])
        self.assertEqual(status, "empty")

    def test_another_script_is_not_an_answer(self):
        body, status = A.build_teach_body(
            "In plain words, 线性可确定性 means a system behaves atomically.", "", PASSAGES, [],
        )
        self.assertEqual(status, "nonlatin")

    def test_the_refusal_sentence_is_still_exact(self):
        body, status = A.build_teach_body(REFUSAL, "", PASSAGES, [])
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], REFUSAL)
        self.assertEqual(status, "refused")


class ExampleCueTest(unittest.TestCase):
    """The reader asks for an example; the engine routes. No button."""

    def test_a_request_for_an_example_is_detected(self):
        for question in (
            "can u give me examples of it",
            "explain write-ahead logging with an example",
            "give me an example of partitioning",
            "and an example?",
            "provide some examples",
            "can you show me an example of that",
            "what is a watermark in simple words. can you give me an example of it",
        ):
            with self.subTest(question=question):
                self.assertTrue(A.asks_for_example(question))

    def test_example_as_content_is_not_a_request(self):
        # Both strings are real bench questions: the word "example" is the
        # book's subject, not the reader's ask.
        for question in (
            "What uptime percentage represents a concrete example of a "
            "service-level objective in contracts?",
            "How does the mechanical odometer analogy explain two's complement "
            "sign representation in hardware?",
            "What is a write-ahead log?",
            "Why does this example matter in the chapter about replication?",
            "What are the five stages of the data engineering lifecycle?",
        ):
            with self.subTest(question=question):
                self.assertFalse(A.asks_for_example(question))

    def test_the_router_switches_only_ask_and_answer(self):
        self.assertEqual(server.effective_mode("answer", "give me an example"), "teach")
        self.assertEqual(server.effective_mode("ask", "give me an example"), "teach")
        self.assertEqual(server.effective_mode("answer", "what is a watermark"), "answer")
        self.assertEqual(server.effective_mode("explain", "and an example?"), "explain")
        self.assertEqual(server.effective_mode("quiz", "an example?"), "quiz")


class TeachModeTest(unittest.TestCase):
    def run_teach(self, replies):
        calls = []
        queue = list(replies)

        def generate(system, user, model, prefill=""):
            if system == SPELL_SYSTEM:
                return ""            # the reading repair, not an answer call
            calls.append((system, prefill))
            return queue[min(len(calls), len(queue)) - 1]

        generate._is_live = True
        body = A.teach(
            index_of(), "explain the write-ahead log in simple words with an example",
            generate_fn=generate,
            search_fn=lambda idx, q, k=5: [dict(c) for c in (idx.get("chunks") or [])][:k],
            model="m",
        )
        return body, calls

    def test_two_calls_one_answer_with_an_example(self):
        body, calls = self.run_teach([
            "In plain words, a write-ahead log records every change before it is applied.",
            "You write the change in a notebook first, then copy it into the ledger.",
        ])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], TEACH_SYSTEM)
        self.assertEqual(calls[1][0], TEACH_EXAMPLE_SYSTEM)
        self.assertIn("Example:", body["answer"])
        self.assertEqual(
            set(body), {"answer", "citations", "figures", "refused", "followups"}
        )

    def test_a_garbage_explanation_degrades_to_the_normal_answer(self):
        body, calls = self.run_teach([
            "8-8-8 is a rule",                        # rejected by the shape check
            "the passage answer",                     # the respond fallback
        ])
        self.assertTrue(calls)
        self.assertIn("answer", body)
        self.assertNotIn("Example:", body["answer"])

    def test_the_mode_is_routed(self):
        self.assertIn("teach", server.MODES)


if __name__ == "__main__":
    unittest.main()
