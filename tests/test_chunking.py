"""Sentence packing checks. No EPUB, no Ollama."""

import unittest

from ingest import CHUNK_CHARS, _pieces, _sentences, _sentence_tail


class SentenceTests(unittest.TestCase):
    def test_plain_sentences_split(self):
        self.assertEqual(
            _sentences("One thing here. Two things here. Three."),
            ["One thing here.", "Two things here.", "Three."],
        )

    def test_an_abbreviation_does_not_end_a_sentence(self):
        text = "Use a store, e.g. Amazon S3, for this. Then stop."
        self.assertEqual(
            _sentences(text),
            ["Use a store, e.g. Amazon S3, for this.", "Then stop."],
        )

    def test_initials_do_not_end_a_sentence(self):
        text = "J. R. Storment wrote it. Then he left."
        self.assertEqual(
            _sentences(text), ["J. R. Storment wrote it.", "Then he left."]
        )


class PieceTests(unittest.TestCase):
    def test_a_short_text_is_one_piece(self):
        text = "A short paragraph. It has two sentences."
        self.assertEqual(_pieces(text), [text])

    def test_a_long_text_is_cut_and_every_piece_starts_at_a_sentence(self):
        sentence = "This is a sentence of a reasonable length for the test. "
        text = sentence * 60
        pieces = _pieces(text)
        self.assertGreater(len(pieces), 1)
        for piece in pieces:
            self.assertLessEqual(len(piece), CHUNK_CHARS)
            self.assertTrue(piece.startswith("This is a sentence"), piece[:60])

    def test_a_sentence_longer_than_the_cap_still_makes_progress(self):
        text = "start " + ("word " * (CHUNK_CHARS // 2 + 200))
        pieces = _pieces(text)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(piece) <= CHUNK_CHARS for piece in pieces))

    def test_no_piece_is_empty(self):
        text = ("Short one. " * 200).strip()
        self.assertTrue(all(piece.strip() for piece in _pieces(text)))


class OverlapTests(unittest.TestCase):
    def test_the_overlap_is_whole_sentences(self):
        text = "First sentence here. Second sentence here. Third sentence here."
        tail = _sentence_tail(text, 40)
        self.assertTrue(text.endswith(tail), tail)
        self.assertTrue(tail.startswith("Third"), tail)

    def test_the_overlap_never_starts_mid_sentence(self):
        text = "Alpha is done. Beta is done. Gamma is done. Delta is done."
        for limit in (10, 25, 40, 60):
            tail = _sentence_tail(text, limit)
            if tail:
                self.assertTrue(tail[0].isupper(), (limit, tail))


if __name__ == "__main__":
    unittest.main()
