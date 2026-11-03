"""Lexical gate: rare words and book-named words justify a BM25 pass.

Fake index. No Ollama, no model. The df=51 fixtures reproduce the novel's own
numbers (`atofe` 51 chunks, `rudeus` 65), the case where the old gate stayed
closed on the book's most repeated vocabulary.
"""

import unittest

from keywords import lexical_terms, named_words, postings, rare


def make_index(texts):
    return {
        "chunks": [
            {"chunk_id": f"ch{i:03d}", "chapter": "1", "heading": "", "text": text}
            for i, text in enumerate(texts)
        ],
        "figures": [],
    }


class NamedWordTests(unittest.TestCase):
    def test_a_capitalised_name_is_named(self):
        index = make_index(["Atofe appears here"] * 51)
        self.assertIn("atofe", named_words(index))

    def test_a_lower_case_word_is_not_named(self):
        index = make_index(["the pipeline runs"] * 51)
        self.assertNotIn("pipeline", named_words(index))

    def test_a_word_capitalised_only_at_sentence_start_is_not_named(self):
        # One capitalised mention in 51 is typography: below NAMED_DF.
        index = make_index(["Data flows downhill"] + ["the data flows downhill"] * 50)
        self.assertNotIn("data", named_words(index))

    def test_a_stopword_is_never_named(self):
        # "I" is capitalised in every mention of a first-person book.
        index = make_index(["I saw it"] * 51)
        self.assertNotIn("i", named_words(index))
        self.assertEqual(named_words(index), frozenset())

    def test_the_cache_is_reused_and_invalidated_by_a_new_chunk_list(self):
        index = make_index(["Atofe appears here"] * 51)
        first = named_words(index)
        self.assertIs(named_words(index), first)
        # Keep the old list alive so CPython cannot hand its id to the new one.
        old_chunks = index["chunks"]
        index["chunks"] = [
            {"chunk_id": f"ch{i:03d}", "chapter": "1", "heading": "", "text": "a name appears here"}
            for i in range(51)
        ]
        self.assertNotIn("atofe", named_words(index))
        self.assertIn("atofe", named_words({**index, "chunks": old_chunks}))


class LexicalTermTests(unittest.TestCase):
    def test_a_repeated_name_fires_the_leg(self):
        index = make_index(["Atofe appears here"] * 51)
        word_map = postings(index)
        self.assertFalse(rare("who is atofe", word_map))
        self.assertEqual(lexical_terms(index, "who is atofe", word_map), ["atofe"])

    def test_a_lower_case_common_word_with_the_same_df_does_not_fire(self):
        index = make_index(["the pipeline runs"] * 51)
        word_map = postings(index)
        self.assertEqual(len(word_map["pipeline"]), 51)
        self.assertEqual(lexical_terms(index, "what is a pipeline", word_map), [])

    def test_a_rare_term_still_fires(self):
        index = make_index(["the pragmatic lead"] + ["filler words here"] * 50)
        word_map = postings(index)
        self.assertEqual(lexical_terms(index, "what is pragmatic", word_map), ["pragmatic"])

    def test_a_name_absent_from_the_book_does_not_fire(self):
        index = make_index(["Atofe appears here"] * 51)
        word_map = postings(index)
        self.assertEqual(lexical_terms(index, "who is frodo", word_map), [])

    def test_duplicates_collapse_and_order_is_the_question_s(self):
        index = make_index(["Atofe appears here"] * 51)
        word_map = postings(index)
        self.assertEqual(
            lexical_terms(index, "is atofe and atofe the same", word_map), ["atofe"]
        )


if __name__ == "__main__":
    unittest.main()
