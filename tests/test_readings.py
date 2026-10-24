"""Second-reading checks. Fake embedder. No Ollama."""

import re
import unittest

from readings import llm_second_reading, resolved_reading, second_reading
from retrieve import DEFAULT_EMBEDDER


def fake_embed(texts, model):
    vectors = []
    for text in texts:
        lowered = text.lower()
        if re.search(r"\bwatermark\b", lowered):     # the book word
            vectors.append([1.0, 0.0])
        elif re.search(r"\bwaremark\b", lowered):    # a typo the literal read wins
            vectors.append([1.0, 0.0])
        elif re.search(r"\batermark\b", lowered):    # the typo, a muddled vector
            vectors.append([0.6, 0.8])
        else:
            vectors.append([0.0, 1.0])
    return vectors


def make_index():
    return {
        "embedder": DEFAULT_EMBEDDER,
        "chunks": [
            {
                "chunk_id": "ch08-040",
                "chapter": "8",
                "heading": "Watermarks",
                "text": "Watermarks\nA watermark is a threshold.",
                "embedding": [1.0, 0.0],
            },
            {
                "chunk_id": "chA",
                "chapter": "1",
                "heading": "",
                "text": "Something else entirely.",
                "embedding": [0.0, 1.0],
            },
        ],
        "figures": [],
    }


class ResolvedReadingTests(unittest.TestCase):
    def test_an_out_of_book_word_is_swapped_for_the_closest_book_word(self):
        word_map = {
            "what": [0], "is": [0], "a": [0],
            "watermark": [0], "watermarks": [1],
        }
        self.assertEqual(
            resolved_reading("what is a atermark?", word_map),
            "what is a watermark?",
        )

    def test_a_book_word_is_never_swapped(self):
        word_map = {"what": [0], "watermark": [0]}
        question = "what is a watermark?"
        self.assertEqual(resolved_reading(question, word_map), question)

    def test_a_tie_between_two_candidates_swaps_nothing(self):
        word_map = {
            "where": [0], "is": [0], "the": [0], "door": [1],
            "streams": [0], "streama": [1],
        }
        question = "where is the streamx?"
        self.assertEqual(resolved_reading(question, word_map), question)

    def test_below_the_cutoff_swaps_nothing(self):
        word_map = {"what": [0], "colonnade": [0]}
        question = "what is a colombia?"
        self.assertEqual(resolved_reading(question, word_map), question)

    def test_an_empty_book_swaps_nothing(self):
        question = "what is a atermark?"
        self.assertEqual(resolved_reading(question, {}), question)


class SecondReadingTests(unittest.TestCase):
    def test_a_better_reading_names_itself_and_its_chunk(self):
        index = make_index()
        reading = second_reading(
            index, "what is a atermark?", 0.8, embed_fn=fake_embed
        )
        self.assertIsNotNone(reading)
        self.assertEqual(reading["chunk"]["chunk_id"], "ch08-040")
        self.assertEqual(reading["reading"], "what is a watermark?")
        self.assertEqual(reading["swaps"], {"atermark": "watermark"})

    def test_a_reading_that_only_matches_is_dropped(self):
        # "waremark" reads as well as "watermark", and equality is not an
        # improvement, so the literal question stands.
        index = make_index()
        self.assertIsNone(
            second_reading(index, "what is a waremark?", 1.0, embed_fn=fake_embed)
        )

    def test_nothing_to_resolve_never_embeds(self):
        def refuse(*args, **kwargs):
            raise AssertionError("must not embed without a swap")

        index = make_index()
        self.assertIsNone(
            second_reading(index, "what is a watermark?", 0.9, embed_fn=refuse)
        )


class LlmSecondReadingTests(unittest.TestCase):
    def test_a_kept_llm_reading_names_itself_and_its_chunk(self):
        index = make_index()
        reading = llm_second_reading(
            index,
            "what is a waremark?",
            0.8,
            generate_fn=lambda system, user, model: "what is a watermark?",
            embed_fn=fake_embed,
        )
        self.assertIsNotNone(reading)
        self.assertEqual(reading["reading"], "what is a watermark?")
        self.assertEqual(reading["chunk"]["chunk_id"], "ch08-040")
        self.assertEqual(reading["swaps"], {"waremark": "watermark"})

    def test_a_case_only_change_is_rejected_without_embedding(self):
        def refuse_embed(*args, **kwargs):
            raise AssertionError("must not embed a case-only change")

        index = make_index()
        reading = llm_second_reading(
            index,
            "what does iops mean",
            0.5,
            generate_fn=lambda system, user, model: "What does IOPS mean?",
            embed_fn=refuse_embed,
            word_map={"what": [0], "does": [0], "mean": [0]},
        )
        self.assertIsNone(reading)

    def test_an_expansion_is_rejected(self):
        index = make_index()
        reading = llm_second_reading(
            index,
            "what is a waremark?",
            0.1,
            generate_fn=lambda system, user, model: "what is a watermark used for",
            embed_fn=fake_embed,
        )
        self.assertIsNone(reading)

    def test_no_absent_word_never_calls_the_model(self):
        def refuse(*args, **kwargs):
            raise AssertionError("must not call the model")

        index = make_index()
        reading = llm_second_reading(
            index,
            "what is a watermark?",
            0.5,
            generate_fn=refuse,
            embed_fn=fake_embed,
            word_map={"what": [0], "is": [0], "a": [0], "watermark": [0]},
        )
        self.assertIsNone(reading)

    def test_a_reading_that_only_matches_is_dropped(self):
        index = make_index()
        reading = llm_second_reading(
            index,
            "what is a waremark?",
            1.0,
            generate_fn=lambda system, user, model: "what is a watermark?",
            embed_fn=fake_embed,
        )
        self.assertIsNone(reading)

    def test_a_failed_model_call_leaves_the_literal_question(self):
        def explode(*args, **kwargs):
            raise RuntimeError("model down")

        index = make_index()
        reading = llm_second_reading(
            index, "what is a waremark?", 0.5,
            generate_fn=explode, embed_fn=fake_embed,
        )
        self.assertIsNone(reading)


if __name__ == "__main__":
    unittest.main()
