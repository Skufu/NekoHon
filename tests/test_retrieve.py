"""Phase 3 retrieval. Fake embedder. No Ollama, no real book."""

import unittest

from engine.retrieval.retrieve import (
    GEMMA_EMBEDDER,
    cosine,
    document_input,
    embed_index,
    format_input,
    rank_chunks,
    search,
    smoke,
)

DIMS = 3


def fake_embed(texts, model):
    vectors = []
    for text in texts:
        lowered = text.lower()
        if "change data capture" in lowered:
            vectors.append([1.0, 0.0, 0.0])
        elif "batch" in lowered:
            vectors.append([0.0, 1.0, 0.0])
        else:
            vectors.append([0.0, 0.0, 1.0])
    return vectors


def tiny_index():
    return {
        "book_id": "fake",
        "chunks": [
            {
                "chunk_id": "c7-001",
                "chapter": "7",
                "heading": "Change data capture",
                "text": "Change data capture\nChange data capture streams row-level changes.",
                "source": "ch07",
            },
            {
                "chunk_id": "c5-001",
                "chapter": "5",
                "heading": "Batch",
                "text": "Batch\nA batch load runs once a day.",
                "source": "ch05",
            },
        ],
        "figures": [
            {
                "id": "figure-7-3",
                "chapter": "7",
                "caption": "Batch and streaming ingestion.",
                "referencing_paragraph": "See Figure 7-3.",
                "file": "fig.png",
            }
        ],
    }


class RetrieveTests(unittest.TestCase):
    def test_cosine_bounds(self):
        self.assertAlmostEqual(cosine([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertAlmostEqual(cosine([1.0, 0.0], [0.0, 1.0]), 0.0)
        self.assertEqual(cosine([0.0, 0.0], [1.0, 0.0]), 0.0)
        self.assertEqual(cosine([1.0], [1.0, 0.0]), 0.0)

    def test_embed_uses_prefix_and_skips_a_second_pass(self):
        seen = []

        def recording(texts, model):
            seen.extend(texts)
            return fake_embed(texts, model)

        index = tiny_index()
        first_chunks, first_figures = embed_index(index, embed_fn=recording, dims=DIMS)
        self.assertEqual(first_chunks, 2)
        self.assertEqual(first_figures, 1)
        self.assertTrue(seen[0].startswith("search_document: "))
        self.assertIn("Change data capture", " ".join(seen))
        self.assertEqual(len(index["chunks"][0]["embedding"]), DIMS)
        self.assertEqual(index["embedder"], "nomic-embed-text")
        seen.clear()
        second_chunks, second_figures = embed_index(index, embed_fn=recording, dims=DIMS)
        self.assertEqual((second_chunks, second_figures), (0, 0))
        self.assertEqual(seen, [])

    def test_search_puts_the_matching_chunk_first(self):
        index = tiny_index()
        embed_index(index, embed_fn=fake_embed, dims=DIMS)
        hits = search(
            index,
            "What is change data capture used for?",
            embed_fn=fake_embed,
            k=10,
        )
        self.assertEqual(hits[0]["chunk_id"], "c7-001")
        self.assertEqual(hits[0]["chapter"], "7")
        self.assertGreater(hits[0]["score"], hits[1]["score"])

    def test_smoke_counts_chapter_and_phrase(self):
        index = tiny_index()
        embed_index(index, embed_fn=fake_embed, dims=DIMS)
        questions = [
            {
                "q": "What is change data capture used for?",
                "chapter": "7",
                "must_contain": "row-level",
            },
            {
                "q": "What is change data capture used for?",
                "chapter": "5",
                "must_contain": "row-level",
            },
        ]
        hits, total, lines = smoke(index, questions, embed_fn=fake_embed)
        self.assertEqual((hits, total), (1, 2))
        self.assertTrue(lines[0].startswith("hit"))
        self.assertTrue(lines[1].startswith("miss"))

    def test_gemma_uses_the_card_prefixes(self):
        query = format_input(GEMMA_EMBEDDER, "query", "What is a watermark?")
        self.assertEqual(query, "task: search result | query: What is a watermark?")
        untitled = format_input(GEMMA_EMBEDDER, "document", "a passage")
        self.assertEqual(untitled, "title: none | text: a passage")
        chunk = {
            "heading": "Watermarks",
            "text": "Watermarks\nA watermark is a threshold.",
        }
        formatted = document_input(GEMMA_EMBEDDER, chunk, "chunk")
        self.assertEqual(
            formatted,
            "title: Watermarks | text: A watermark is a threshold.",
        )
        nomic = document_input("nomic-embed-text", chunk, "chunk")
        self.assertTrue(nomic.startswith("search_document: "))
        self.assertIn("Watermarks", nomic)

    def test_query_prefix_is_not_the_document_prefix(self):
        seen = []

        def recording(texts, model):
            seen.extend(texts)
            return fake_embed(texts, model)

        index = tiny_index()
        embed_index(index, embed_fn=recording, dims=DIMS)
        search(index, "change data capture", embed_fn=recording, k=1)
        self.assertTrue(seen[-1].startswith("search_query: "))

    def test_embed_index_refuses_a_non_finite_vector(self):
        def bad_embed(texts, model):
            return [[float("nan"), 0.0, 0.0] for _ in texts]

        index = tiny_index()
        with self.assertRaises(SystemExit) as caught:
            embed_index(index, embed_fn=bad_embed, dims=DIMS)
        self.assertIn("c7-001", str(caught.exception))
        self.assertNotIn("embedding", index["chunks"][0])

    def test_embed_index_refuses_a_zero_vector(self):
        def bad_embed(texts, model):
            return [[0.0, 0.0, 0.0] for _ in texts]

        index = tiny_index()
        with self.assertRaises(SystemExit) as caught:
            embed_index(index, embed_fn=bad_embed, dims=DIMS)
        self.assertIn("c7-001", str(caught.exception))
        self.assertIn("all-zero", str(caught.exception))

    def test_rank_chunks_refuses_a_zero_query(self):
        def zero_query(texts, model):
            return [[0.0, 0.0] for _ in texts]

        index = {
            "embedder": "nomic-embed-text",
            "embedding_dims": 2,
            "chunks": [{"chunk_id": "c1", "text": "a row", "embedding": [1.0, 0.0]}],
        }
        with self.assertRaises(SystemExit) as caught:
            rank_chunks(index, "anything", embed_fn=zero_query)
        self.assertIn("all-zero", str(caught.exception))

    def test_embed_index_refuses_a_wrong_width_response(self):
        def bad_embed(texts, model):
            return [[1.0, 0.0] for _ in texts]

        index = tiny_index()
        with self.assertRaises(SystemExit) as caught:
            embed_index(index, embed_fn=bad_embed, dims=DIMS)
        self.assertIn("width 2, expected 3", str(caught.exception))

    def test_embed_index_refuses_a_short_response(self):
        def bad_embed(texts, model):
            return [[1.0, 0.0, 0.0]]

        index = tiny_index()
        with self.assertRaises(SystemExit) as caught:
            embed_index(index, embed_fn=bad_embed, dims=DIMS)
        self.assertIn("1 vectors for 2 texts", str(caught.exception))

    def test_rank_refuses_a_query_width_drift(self):
        index = tiny_index()
        embed_index(index, embed_fn=fake_embed, dims=DIMS)

        def short_embed(texts, model):
            return [[1.0, 0.0] for _ in texts]

        with self.assertRaises(SystemExit) as caught:
            search(index, "batch", embed_fn=short_embed)
        self.assertIn("index declares 3", str(caught.exception))

    def test_rank_refuses_a_non_finite_query(self):
        index = tiny_index()
        embed_index(index, embed_fn=fake_embed, dims=DIMS)

        def nan_embed(texts, model):
            return [[float("nan"), 0.0, 0.0] for _ in texts]

        with self.assertRaises(SystemExit) as caught:
            search(index, "batch", embed_fn=nan_embed)
        self.assertIn("non-finite", str(caught.exception))

    def test_rank_names_a_drifted_stored_vector(self):
        index = tiny_index()
        embed_index(index, embed_fn=fake_embed, dims=DIMS)
        index["chunks"][1]["embedding"] = [1.0, 0.0]
        with self.assertRaises(SystemExit) as caught:
            search(index, "batch", embed_fn=fake_embed)
        self.assertIn("c5-001", str(caught.exception))

    def test_search_skips_a_record_without_a_vector(self):
        index = tiny_index()
        embed_index(index, embed_fn=fake_embed, dims=DIMS)
        index["chunks"][0].pop("embedding")
        hits = search(index, "batch", embed_fn=fake_embed, k=10)
        self.assertEqual([hit["chunk_id"] for hit in hits], ["c5-001"])


if __name__ == "__main__":
    unittest.main()
