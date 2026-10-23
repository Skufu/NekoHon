import unittest

from engine.retrieval.preprocess import STOPWORDS, fold, normalize, stem, stemmed_words, words


class FoldTests(unittest.TestCase):
    def test_typographic_quotes_and_dashes_fold_to_ascii(self):
        self.assertEqual(
            fold("the book’s “quote” — done"), 'the book\'s "quote" - done'
        )
        self.assertEqual(fold("it’s"), fold("it's"))

    def test_nfkc_still_runs(self):
        self.assertEqual(fold("the ﬁle"), "the file")
        self.assertEqual(fold("ＡＢＣ"), "abc")

    def test_case_is_folded(self):
        self.assertEqual(fold("WaterMark"), "watermark")

    def test_fold_is_idempotent(self):
        once = fold("it’s “ﬁne” – really")
        self.assertEqual(fold(once), once)

    def test_normalize_keeps_case_and_typography(self):
        self.assertEqual(normalize("The ﬁle’s “name”"), "The file’s “name”")


class StopwordTests(unittest.TestCase):
    def test_function_words_are_covered(self):
        for word in ("actually", "the", "what", "would", "not", "into"):
            self.assertIn(word, STOPWORDS)

    def test_content_words_survive(self):
        for word in ("extract", "watermark", "data", "storage", "pipeline"):
            self.assertNotIn(word, STOPWORDS)

    def test_the_list_is_lowercase_ascii_words(self):
        self.assertEqual(len(STOPWORDS), 570)
        for word in STOPWORDS:
            self.assertEqual(word, word.lower())
            self.assertTrue(word.isascii(), word)


class StemmerTests(unittest.TestCase):
    def test_the_extract_family_collapses_to_one_stem(self):
        self.assertEqual(stem("extracted"), "extract")
        self.assertEqual(stem("extract"), "extract")
        self.assertEqual(stem("extracting"), "extract")

    def test_standard_porter2_families(self):
        for word, expected in (
            ("consigned", "consign"),
            ("consigning", "consign"),
            ("consignment", "consign"),
            ("relational", "relat"),
            ("generously", "generous"),
            ("files", "file"),
            ("filed", "file"),
            ("running", "run"),
            ("runs", "run"),
        ):
            self.assertEqual(stem(word), expected, word)

    def test_documented_porter2_exceptions(self):
        for word, expected in (
            ("ties", "tie"),
            ("tied", "tie"),
            ("tying", "tie"),
            ("skies", "sky"),
            ("skis", "ski"),
            ("sky", "sky"),
            ("news", "news"),
            ("dying", "die"),
            ("lying", "lie"),
        ):
            self.assertEqual(stem(word), expected, word)

    def test_case_is_folded_before_stemming(self):
        self.assertEqual(stem("Extracted"), "extract")
        self.assertEqual(stem("EXTRACTING"), "extract")

    def test_stemming_is_idempotent(self):
        for word in (
            "extracted",
            "relational",
            "generously",
            "skies",
            "news",
            "storage",
            "storing",
            "streaming",
            "consignment",
        ):
            once = stem(word)
            self.assertEqual(stem(once), once, word)

    def test_stemmed_words_folds_before_tokenizing(self):
        self.assertEqual(
            stemmed_words("Extracting the ﬁle"), ["extract", "the", "file"]
        )

    def test_stemmed_words_is_a_view_over_the_shared_tokenizer(self):
        self.assertEqual(
            stemmed_words("Extracted at 1/17 scale."), ["extract", "at", "scale"]
        )
        self.assertEqual(stemmed_words(""), [])
        self.assertEqual(
            [stem(word) for word in words("Extracted at scale.")],
            stemmed_words("Extracted at scale."),
        )


if __name__ == "__main__":
    unittest.main()
