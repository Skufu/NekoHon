"""Rare-word boost checks. Fake index. No Ollama."""

import unittest

from keywords import boost


def make_index(texts):
    chunks = [
        {"chunk_id": f"ch{i:02d}", "chapter": "1", "heading": "", "text": text}
        for i, text in enumerate(texts)
    ]
    return {"chunks": chunks, "figures": []}


def passage(chunk_id):
    return {
        "chunk_id": chunk_id,
        "chapter": "1",
        "heading": "",
        "text": "",
        "source": "",
        "score": 0.9,
    }


class BoostTests(unittest.TestCase):
    def test_rare_word_swaps_in_the_best_overlap_chunk(self):
        texts = ["the filler words here"] * 8
        texts[3] = "the pragmatic lead cares about flexibility"
        texts[7] = "flexibility shows up here too"
        index = make_index(texts)
        passages = [passage(f"ch{i:02d}") for i in (0, 1, 2, 4, 5)]
        boosted = boost(index, "what is pragmatic about flexibility", passages,
                        rank_map={"ch03": 1})
        self.assertEqual([hit["chunk_id"] for hit in boosted[:4]],
                         ["ch00", "ch01", "ch02", "ch04"])
        self.assertEqual(boosted[-1]["chunk_id"], "ch03")

    def test_no_rare_word_leaves_everything_alone(self):
        index = make_index(["the data of the book"] * 20)
        passages = [passage(f"ch{i:02d}") for i in (15, 16, 17, 18, 19)]
        boosted = boost(index, "what is the data of the book", passages)
        self.assertEqual(boosted, passages)

    def test_a_present_chunk_is_not_duplicated(self):
        texts = ["the filler words here"] * 8
        texts[3] = "the pragmatic lead cares about flexibility"
        index = make_index(texts)
        passages = [passage("ch03")] + [passage(f"ch{i:02d}") for i in (0, 1, 2, 4)]
        boosted = boost(index, "what is pragmatic about flexibility", passages,
                        rank_map={"ch03": 1})
        self.assertEqual(boosted, passages)

    def test_a_common_word_above_the_rare_cutoff_does_not_fire(self):
        texts = ["capital plans for each team"] * 10 + ["unrelated filler"] * 2
        index = make_index(texts)
        passages = [passage(f"ch{i:02d}") for i in (10, 11, 0, 1, 2)]
        boosted = boost(index, "what is the capital of france", passages)
        self.assertEqual(boosted, passages)

    def test_a_chunk_from_the_tail_is_not_promoted(self):
        texts = ["the filler words here"] * 8
        texts[3] = "the pragmatic lead cares about flexibility"
        index = make_index(texts)
        passages = [passage(f"ch{i:02d}") for i in (0, 1, 2, 4, 5)]
        boosted = boost(index, "what is pragmatic about flexibility", passages,
                        rank_map={"ch03": 8})
        self.assertEqual(boosted, passages)

    def test_no_rank_evidence_fails_closed(self):
        texts = ["the filler words here"] * 8
        texts[3] = "the pragmatic lead cares about flexibility"
        index = make_index(texts)
        passages = [passage(f"ch{i:02d}") for i in (0, 1, 2, 4, 5)]
        self.assertEqual(
            boost(index, "what is pragmatic about flexibility", passages),
            passages,
        )


if __name__ == "__main__":
    unittest.main()
