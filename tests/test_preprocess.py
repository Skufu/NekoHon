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
        # Documented on purpose: "S3" reads as "s" and "1/17" reads as nothing.
        # Widening this moves every df count, and the rare gate rides on those.
        self.assertEqual(words("S3 stores 1/17 of it."), ["s", "stores", "of", "it"])


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
    def test_the_dense_view_is_deliberately_the_identity(self):
        # If this fails, the bytes the embedder sees changed, and every vector
        # in data/index.json is stale. That is a bake-off, not a commit.
        self.assertEqual(normalize("A  B\n\tC"), "A  B\n\tC")

    def test_the_prefix_is_added_after_the_dense_view(self):
        self.assertEqual(
            format_input(DEFAULT_EMBEDDER, "query", "a  b"),
            "search_query: a  b",
        )
        self.assertEqual(
            format_input(DEFAULT_EMBEDDER, "document", "a  b"),
            "search_document: a  b",
        )


if __name__ == "__main__":
    unittest.main()
