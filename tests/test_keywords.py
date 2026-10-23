"""Rare-word gate checks. Fake index. No Ollama."""

import unittest

from engine.retrieval.keywords import anchor_words, postings, rare


def make_index(texts):
    return {
        "chunks": [
            {"chunk_id": f"ch{i:02d}", "chapter": "1", "heading": "", "text": text}
            for i, text in enumerate(texts)
        ],
        "figures": [],
    }


class RareTests(unittest.TestCase):
    def test_a_rare_book_word_fires(self):
        index = make_index(["the pragmatic lead cares"] + ["filler words here"] * 9)
        self.assertTrue(rare("what is pragmatic", postings(index)))

    def test_common_words_do_not_fire(self):
        index = make_index(["the data of the book"] * 10)
        self.assertFalse(rare("what is the data of the book", postings(index)))

    def test_a_word_absent_from_the_book_does_not_fire(self):
        index = make_index(["the data of the book"] * 10)
        self.assertFalse(rare("what is the capital of france", postings(index)))


class PostingsTests(unittest.TestCase):
    def test_a_word_maps_to_its_chunk_positions(self):
        index = make_index(["alpha beta", "beta gamma", "alpha gamma"])
        table = postings(index)
        self.assertEqual(table["alpha"], [0, 2])
        self.assertEqual(table["beta"], [0, 1])


class AnchorTests(unittest.TestCase):
    def test_a_rare_content_word_anchors(self):
        index = make_index(["the pragmatic lead"] + ["filler words here"] * 9)
        self.assertEqual(anchor_words("what is pragmatic", postings(index)), {"pragmatic"})

    def test_a_stopword_never_anchors_even_when_rare_in_book(self):
        # "actually" is rare in this fake book, but it is a stopword: the
        # question's rare function words must not expand a paragraph.
        index = make_index(["it actually matters"] + ["filler words here"] * 9)
        self.assertEqual(anchor_words("what does it actually do", postings(index)), set())


if __name__ == "__main__":
    unittest.main()
