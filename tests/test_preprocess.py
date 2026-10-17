"""One text seam checks. No Ollama."""

import unittest

from keywords import postings, rare
from preprocess import normalize, tokens, words
from retrieve import DEFAULT_EMBEDDER, format_input


class TokenizerTests(unittest.TestCase):
    def test_tokens_keep_the_spelling_and_words_fold_it(self):
        self.assertEqual(tokens("The Pragmatic Lead"), ["The", "Pragmatic", "Lead"])
        self.assertEqual(words("The Pragmatic Lead"), ["the", "pragmatic", "lead"])

    def test_punctuation_is_not_a_token_and_digits_are_not_one_either(self):
        # Pure digits are not tokens: "1/17" reads as nothing.
        # Alphanumeric terms with letters ("S3", "3NF", "DDR4") stay intact.
        self.assertEqual(words("S3 stores 1/17 of it."), ["s3", "stores", "of", "it"])


class SymmetryTests(unittest.TestCase):
    def test_postings_are_built_with_the_shared_tokenizer(self):
        text = "The Pragmatic Lead, 1/17 of it."
        index = {"chunks": [{"chunk_id": "c1", "text": text}]}
        self.assertEqual(set(postings(index)), set(words(text)))

    def test_the_query_side_folds_exactly_like_the_index_side(self):
        index = {"chunks": [{"chunk_id": "c1", "text": "A pragmatic lead."}]}
        table = postings(index)
        self.assertTrue(rare("PRAGMATIC", table))
        self.assertTrue(rare("pragmatic", table))
        self.assertFalse(rare("pragmatically", table))

    def test_case_cannot_split_the_two_sides(self):
        index = {"chunks": [{"chunk_id": "c1", "text": "A Watermark marks progress."}]}
        table = postings(index)
        for typed in ("Watermark", "WATERMARK", "watermark", "wAtErMaRk"):
            self.assertTrue(rare(typed, table))


class DenseSeamTests(unittest.TestCase):
    def test_normalize_is_nfkc_then_single_spaces(self):
        self.assertEqual(normalize("the ﬁle  is\topen"), "the file is open")
        self.assertEqual(normalize("a\u00a0b"), "a b")

    def test_normalize_keeps_newlines_so_the_heading_line_survives(self):
        self.assertEqual(normalize("Heading\n  body   text"), "Heading\nbody text")

    def test_normalize_is_idempotent(self):
        once = normalize("the ﬁle \u2460  runs")
        self.assertEqual(normalize(once), once)

    def test_the_prefix_is_added_after_the_dense_view(self):
        self.assertEqual(
            format_input(DEFAULT_EMBEDDER, "query", "a  b"),
            "search_query: a b",
        )
        self.assertEqual(
            format_input(DEFAULT_EMBEDDER, "document", "a  b"),
            "search_document: a b",
        )


if __name__ == "__main__":
    unittest.main()
