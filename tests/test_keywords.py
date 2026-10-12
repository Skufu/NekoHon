"""Rare-word gate checks. Fake index. No Ollama."""

import unittest

from keywords import postings, rare


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


if __name__ == "__main__":
    unittest.main()
