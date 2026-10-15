"""The form canonicalizer: trigger table, the seam, the explain gate.

canonical_query turns a bare topic phrase into "What is <phrase>?" before
retrieval and the prompt; ask/respond use the same string everywhere and
add the visible `Asked as:` line; explain is gated off (its highlight is a
book sentence, not a question). No Ollama: recovery is injected.
"""

import unittest

import answer as A
from canonical import canonical_query
from prompt import SYSTEM, SYSTEM_ANSWER


def hit(chunk_id, chapter, text):
    return {"chunk_id": chunk_id, "chapter": chapter, "text": text, "score": 0.9}


PASSAGES = [
    hit("c1-001", "1",
        "Change data capture (CDC) streams row-level changes from a database "
        "so downstream systems stay in sync."),
    hit("c2-002", "2",
        "Batch processing runs on a schedule and handles large volumes of "
        "records at once."),
]
CDC_QUOTE = PASSAGES[0]["text"]


class TriggerTest(unittest.TestCase):
    def test_bare_phrases_fire(self):
        for question in (
            "MAD data landscape",
            "watermark",
            "CRUD",
            "data ingestion",
            "data mesh in simple words",
        ):
            with self.subTest(question=question):
                self.assertEqual(canonical_query(question), f"What is {question}?")

    def test_casing_is_kept_and_edges_trimmed(self):
        self.assertEqual(canonical_query("  mAd DaTa  "), "What is mAd DaTa?")

    def test_question_forms_do_not_fire(self):
        for question in (
            "What is MAD data landscape",
            "What is MAD data landscape?",
            "what does CRUD stand for?",
            "How does batch processing work",
            "Data engineers need to be pragmatic about?",
        ):
            with self.subTest(question=question):
                self.assertEqual(canonical_query(question), question)

    def test_auxiliary_start_does_not_fire(self):
        for question in (
            "Is data mesh decentralized?",
            "Do watermarks help?",
            "Can you explain CDC",
        ):
            with self.subTest(question=question):
                self.assertEqual(canonical_query(question), question)

    def test_openers_list_markers_and_pronouns_do_not_fire(self):
        for question in (
            "explain data ingestion",
            "describe CDC",
            "types of metadata",
            "compare batch and streaming",
            "list the transformation types",
            "hey can you tell me about data mesh",
            "watermark for me",
        ):
            with self.subTest(question=question):
                self.assertEqual(canonical_query(question), question)

    def test_sentence_punctuation_stops_it(self):
        highlight = "A watermark (Figure 8-8) is a threshold used by a window."
        self.assertEqual(canonical_query(highlight), highlight)
        self.assertEqual(canonical_query("data mesh now!"), "data mesh now!")

    def test_non_firing_is_byte_identical(self):
        untouched = "What is CDC "
        self.assertEqual(canonical_query(untouched), untouched)

    def test_empty_and_none(self):
        self.assertEqual(canonical_query(""), "")
        self.assertEqual(canonical_query(None), "")
        self.assertEqual(canonical_query("   "), "   ")


class _SeamBase(unittest.TestCase):
    """Patches the model/seed seams so the suite never calls Ollama."""

    def setUp(self):
        self.index = {"chunks": PASSAGES, "figures": []}
        self.calls = {}
        self.saved = {
            name: getattr(A, name)
            for name in ("fuse", "caption_seed", "second_reading", "llm_second_reading")
        }

        def fuse(index, question, passages, word_map):
            self.calls["fuse"] = question
            return passages

        def caption_seed(index, question, passages, *a, **kw):
            self.calls["caption"] = question
            return passages

        A.fuse = fuse
        A.caption_seed = caption_seed
        A.second_reading = lambda *a, **kw: None
        A.llm_second_reading = lambda *a, **kw: None

    def tearDown(self):
        for name, fn in self.saved.items():
            setattr(A, name, fn)

    def search_recorder(self):
        def search(index, question, k=10):
            self.calls["search"] = question
            return PASSAGES
        return search


class SeamTest(_SeamBase):
    def test_ask_sees_one_canonical_string_everywhere(self):
        def generate(system, user, model):
            self.calls["system"] = system
            self.calls["user"] = user
            return f'[Ch. 1] "{CDC_QUOTE}"\nA change feed for databases.'

        body = A.ask(
            self.index, "CDC",
            generate_fn=generate, search_fn=self.search_recorder(), model="m",
        )
        self.assertEqual(self.calls["search"], "What is CDC?")
        self.assertEqual(self.calls["fuse"], "What is CDC?")
        self.assertEqual(self.calls["caption"], "What is CDC?")
        self.assertEqual(self.calls["system"], SYSTEM)
        self.assertIn("What is CDC?", self.calls["user"])
        self.assertIn('Asked as: "What is CDC?"', body["answer"])
        self.assertFalse(body["refused"])

    def test_refusal_keeps_the_exact_sentence(self):
        def generate(system, user, model):
            return "Not in this book."

        body = A.ask(
            self.index, "CDC",
            generate_fn=generate, search_fn=self.search_recorder(), model="m",
        )
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], "Not in this book.")
        self.assertNotIn("Asked as:", body["answer"])

    def test_answer_mode_uses_the_canonical_string(self):
        def generate(system, user, model):
            self.calls["system"] = system
            self.calls["user"] = user
            return "CDC streams database changes. [Ch. 1]"

        body = A.respond(
            self.index, "CDC",
            generate_fn=generate, search_fn=self.search_recorder(), model="m",
        )
        self.assertEqual(self.calls["search"], "What is CDC?")
        # 2026-10-15 prompt alignment: answer mode serves SYSTEM (ask-shaped),
        # the prompt the student is trained on.
        self.assertEqual(self.calls["system"], SYSTEM)
        self.assertIn("What is CDC?", self.calls["user"])
        self.assertIn('Asked as: "What is CDC?"', body["answer"])

    def test_canonical_off_leaves_the_question_alone(self):
        def generate(system, user, model):
            self.calls["user"] = user
            return f'[Ch. 1] "{CDC_QUOTE}"\nA change feed.'

        body = A.ask(
            self.index, "CDC", generate_fn=generate,
            search_fn=self.search_recorder(), model="m", canonical=False,
        )
        self.assertEqual(self.calls["search"], "CDC")
        self.assertNotIn("Asked as:", body["answer"])


    def test_question_form_passes_through_untouched(self):
        def generate(system, user, model):
            self.calls["user"] = user
            return f'[Ch. 1] "{CDC_QUOTE}"\nA change feed.'

        body = A.ask(
            self.index, "What is CDC?", generate_fn=generate,
            search_fn=self.search_recorder(), model="m",
        )
        self.assertEqual(self.calls["search"], "What is CDC?")
        self.assertNotIn("Asked as:", body["answer"])


class ExplainGateTest(unittest.TestCase):
    def test_a_bare_highlight_is_not_canonicalized(self):
        index = {"chunks": PASSAGES, "figures": []}
        calls = {}
        saved = (A.second_reading, A.llm_second_reading)
        A.second_reading = lambda *a, **kw: None
        A.llm_second_reading = lambda *a, **kw: None
        highlight = CDC_QUOTE.rstrip(".")
        # The highlight must be trigger-eligible, or this test proves nothing:
        # if a future trigger stops matching it, the gate would go untested.
        self.assertNotEqual(canonical_query(highlight), highlight)
        try:
            def search(index, question, k=10):
                calls["search"] = question
                return PASSAGES

            def generate(system, user, model):
                calls["user"] = user
                return f'[Ch. 1] "{CDC_QUOTE}"\nA change feed.'

            body = A.explain(
                index, highlight, generate_fn=generate, search_fn=search, model="m"
            )
        finally:
            A.second_reading, A.llm_second_reading = saved
        self.assertEqual(calls["search"], highlight)
        self.assertNotIn("Asked as:", body["answer"])
        self.assertNotIn("What is", calls["user"])


class AnchorEquivalenceTest(unittest.TestCase):
    def test_prefix_stopwords_add_no_anchors(self):
        from preprocess import STOPWORDS

        # "what"/"is" carry in-bound df here, so only the STOPWORDS filter
        # can keep them out of the anchor set; a broken filter fails this.
        self.assertIn("what", STOPWORDS)
        self.assertIn("is", STOPWORDS)
        word_map = {"watermark": [0], "what": [0], "is": [0]}
        self.assertEqual(
            A.anchor_words("What is watermark?", word_map),
            A.anchor_words("watermark", word_map),
        )


class CueTest(unittest.TestCase):
    def test_cue_survives_canonicalization(self):
        self.assertTrue(A.simple_words(canonical_query("data mesh in simple words")))


if __name__ == "__main__":
    unittest.main()
