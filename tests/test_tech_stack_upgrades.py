"""Comprehensive unit tests for the unlocked local tech stack upgrades:
1. SIMD Vector Indexing + Binary Storage (retrieve.py)
2. SQLite FTS5 Porter & Trigram Search + Injection Safety (fts_index.py)
3. Neural Cross-Encoder Reranking + RRF (rerank.py)
4. Exact Subword Token Budgeting + PDF Ingestion (ingest.py)
5. Anti-cheating negative controls
"""

import math
import os
import tempfile
import unittest
from pathlib import Path

from fts_index import fts_bm25_scores, get_fts_connection, search_trigram
from ingest import count_tokens, get_tokenizer, ingest_pdf, _section_chunks
from rerank import rerank_passages, rerank_rrf
from retrieve import (
    NOMIC_EMBEDDER,
    _build_uvec_matrix,
    _dot,
    cosine,
    load_binary_vectors,
    rank_chunks,
    save_binary_vectors,
)


def make_mock_index(chunks_data):
    """Helper to construct small test indexes without disk or Ollama."""
    return {
        "embedder": NOMIC_EMBEDDER,
        "embedding_dims": 3,
        "chunks": [
            {
                "chunk_id": f"chunk-{i:03d}",
                "chapter": str(item.get("chapter", 1)),
                "heading": item.get("heading", ""),
                "text": item.get("text", ""),
                "embedding": item.get("embedding", [0.0, 0.0, 1.0]),
                "source": f"ch{item.get('chapter', 1)}",
            }
            for i, item in enumerate(chunks_data)
        ],
        "figures": [],
    }


class TechStackUpgradesTests(unittest.TestCase):
    # -------------------------------------------------------------
    # 1. SIMD Vector Indexing & Binary Storage Tests
    # -------------------------------------------------------------
    def test_uvec_matrix_matches_pure_python_dot(self):
        chunks_data = [
            {"text": "First passage on databases", "embedding": [0.6, 0.8, 0.0]},
            {"text": "Second passage on replication", "embedding": [0.0, 0.6, 0.8]},
            {"text": "Third passage on partitioning", "embedding": [0.8, 0.0, 0.6]},
        ]
        index = make_mock_index(chunks_data)
        _build_uvec_matrix(index)

        self.assertIn("_uvec_matrix", index)
        self.assertIsNotNone(index["_uvec_matrix"])
        self.assertEqual(index["_uvec_matrix"].shape, (3, 3))

        query_unit = [0.6, 0.8, 0.0]

        def fake_embed(texts, model):
            return [query_unit for _ in texts]

        ranked_numpy = rank_chunks(index, "test query", model=NOMIC_EMBEDDER, embed_fn=fake_embed)

        # Compare with pure python manual dot
        for score, chunk in ranked_numpy:
            py_dot = _dot(query_unit, chunk["_uvec"])
            self.assertAlmostEqual(score, py_dot, places=5)

        # Top hit should be the exact match chunk-000
        self.assertEqual(ranked_numpy[0][1]["chunk_id"], "chunk-000")
        self.assertAlmostEqual(ranked_numpy[0][0], 1.0, places=5)

    def test_binary_vector_save_and_load(self):
        chunks_data = [
            {"text": "Alpha", "embedding": [1.0, 0.0, 0.0]},
            {"text": "Beta", "embedding": [0.0, 1.0, 0.0]},
            {"text": "Gamma", "embedding": [0.0, 0.0, 1.0]},
        ]
        index = make_mock_index(chunks_data)
        _build_uvec_matrix(index)

        with tempfile.TemporaryDirectory() as tmpdir:
            vec_path = Path(tmpdir) / "vectors.npz"
            save_binary_vectors(index, vec_path)
            self.assertTrue(vec_path.is_file())

            # Fresh index without _uvec
            new_index = make_mock_index(chunks_data)
            for c in new_index["chunks"]:
                c.pop("embedding", None)
            matrix = load_binary_vectors(new_index, vec_path)

            self.assertEqual(matrix.shape, (3, 3))
            self.assertIn("_uvec", new_index["chunks"][0])
            self.assertEqual(new_index["chunks"][0]["_uvec"], [1.0, 0.0, 0.0])

    # -------------------------------------------------------------
    # 2. SQLite FTS5 Search & Injection Safety Tests
    # -------------------------------------------------------------
    def test_fts5_porter_morphological_matching(self):
        chunks_data = [
            {"heading": "Partitions", "text": "Partitioning divides a large dataset into smaller subsets."},
            {"heading": "Indexes", "text": "B-trees index keys in sorted order for range lookups."},
            {"heading": "Filler", "text": "Unrelated filler content number one."},
            {"heading": "Filler", "text": "Unrelated filler content number two."},
        ]
        index = make_mock_index(chunks_data)

        # Query uses "partitioned" (inflected form)
        scores = fts_bm25_scores(index, "partitioned tables")
        self.assertIn(0, scores)
        self.assertNotIn(1, scores)
        self.assertGreater(scores[0], 0.0)

    def test_fts5_trigram_exact_symbol_lookup(self):
        chunks_data = [
            {"heading": "Direct I/O", "text": "Using O_DIRECT bypasses OS page cache."},
            {"heading": "Normal Forms", "text": "Applying 3NF eliminates transitive dependencies."},
            {"heading": "C++ Code", "text": "Written in C++20 with std::span abstractions."},
        ]
        index = make_mock_index(chunks_data)

        res_odirect = search_trigram(index, "O_DIRECT")
        self.assertEqual(len(res_odirect), 1)
        self.assertEqual(res_odirect[0]["chunk_id"], "chunk-000")

        res_3nf = search_trigram(index, "3NF")
        self.assertEqual(len(res_3nf), 1)
        self.assertEqual(res_3nf[0]["chunk_id"], "chunk-001")

        res_cpp = search_trigram(index, "C++")
        self.assertEqual(len(res_cpp), 1)
        self.assertEqual(res_cpp[0]["chunk_id"], "chunk-002")

    def test_fts5_punctuation_and_operator_injection_safety(self):
        chunks_data = [
            {"heading": "Safe Heading", "text": "Standard prose content."},
        ]
        index = make_mock_index(chunks_data)

        dangerous_queries = [
            '"""""',
            'AND OR NOT * ^ : ( )',
            'NEAR(a, b, 10)',
            'SELECT * FROM chunks_fts;',
            "'; DROP TABLE chunks_fts; --",
            'C++ / O_DIRECT ? [!] {test}',
        ]
        for q in dangerous_queries:
            try:
                scores = fts_bm25_scores(index, q)
                self.assertIsInstance(scores, dict)
            except Exception as e:
                self.fail(f"FTS5 query '{q}' raised unexpected exception: {e}")

    def test_fts5_rank_band_tail_veto(self):
        chunks_data = [
            {"heading": "Target", "text": "A rare resilience mechanism operates here."},
            {"heading": "Distractor", "text": "Another resilience strategy lives here."},
            {"heading": "Filler 1", "text": "Filler text about unrelated systems."},
            {"heading": "Filler 2", "text": "More filler text about unrelated systems."},
            {"heading": "Filler 3", "text": "Even more filler text here."},
            {"heading": "Filler 4", "text": "Last filler paragraph."},
        ]
        index = make_mock_index(chunks_data)

        # "resilience" is present in chunks 0 and 1 (df=2 <= 6/2 = 3).
        # chunk-000 has dense rank 1 (inside band 2).
        # chunk-001 has dense rank 5 (outside band 2 -> tail veto!).
        ranks = {"chunk-000": 1, "chunk-001": 5}
        scores = fts_bm25_scores(index, "resilience", ranks=ranks, band=2)
        self.assertIn(0, scores)
        self.assertNotIn(1, scores)

    # -------------------------------------------------------------
    # 3. Neural Reranking Tests
    # -------------------------------------------------------------
    def test_cross_encoder_rerank_passages(self):
        passages = [
            {"chunk_id": "c1", "heading": "Cooking", "text": "How to bake a sourdough bread in an oven."},
            {"chunk_id": "c2", "heading": "Databases", "text": "PostgreSQL uses Write-Ahead Logging (WAL) for durability."},
        ]
        q = "What ensures durability in relational databases?"
        reranked = rerank_passages(q, passages, top_k=2)

        self.assertEqual(len(reranked), 2)
        self.assertEqual(reranked[0]["chunk_id"], "c2")
        self.assertGreater(reranked[0]["rerank_score"], reranked[1]["rerank_score"])

    def test_cross_encoder_keep_top1_mode(self):
        passages = [
            {"chunk_id": "pinned-lead", "heading": "Intro", "text": "General overview."},
            {"chunk_id": "c2", "heading": "Cooking", "text": "Baking bread."},
            {"chunk_id": "c3", "heading": "Databases", "text": "PostgreSQL WAL durability."},
        ]
        q = "What ensures durability in relational databases?"
        reranked = rerank_passages(q, passages, top_k=3, keep_top1=True)

        self.assertEqual(reranked[0]["chunk_id"], "pinned-lead")
        self.assertEqual(reranked[1]["chunk_id"], "c3")
        self.assertEqual(reranked[2]["chunk_id"], "c2")

    def test_rerank_rrf_blending(self):
        passages = [
            {"chunk_id": "c1", "heading": "H1", "text": "T1"},
            {"chunk_id": "c2", "heading": "H2", "text": "T2"},
        ]
        fused = rerank_rrf("query", passages, top_k=2)
        self.assertEqual(len(fused), 2)
        self.assertIn("rrf_score", fused[0])
        # Verify RRF formula bounds: with rrf_k=60 and rank >= 1, max score <= 2 / 61
        self.assertGreater(fused[0]["rrf_score"], 0.0)
        self.assertLessEqual(fused[0]["rrf_score"], 2.0 / 61.0)

    # -------------------------------------------------------------
    # 4. Token Budgeting & PDF Ingestion Tests
    # -------------------------------------------------------------
    def test_token_counting_and_budgeting(self):
        tok = get_tokenizer()
        self.assertIsNotNone(tok)

        text = "Relational database systems enforce ACID transactions."
        num_tokens = count_tokens(text)
        self.assertGreater(num_tokens, 5)
        self.assertLess(num_tokens, 20)

        # Test chunking with strict subword cap max_tokens=25
        blocks = [
            {"kind": "paragraph", "text": "Sentence one explains ACID transactions. Sentence two discusses consistency models. Sentence three analyzes serializability and isolation. Sentence four concludes partition tolerance."},
        ]
        chunks = _section_chunks("Section Title", blocks, max_tokens=25)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(count_tokens(c), 25)

    def test_ingest_pdf_in_memory(self):
        import fitz
        doc = fitz.open()
        p1 = doc.new_page()
        p1.insert_text((50, 72), "Chapter 1: Stream Processing\n\nStreams represent unbounded real-time event sequences.")
        p2 = doc.new_page()
        p2.insert_text((50, 72), "Chapter 2: Batch Processing\n\nBatch systems compute over bounded historical data.")
        pdf_bytes = doc.tobytes()

        chunks = ingest_pdf(pdf_bytes)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["chapter"], "1")
        self.assertIn("Stream Processing", chunks[0]["text"])
        self.assertEqual(chunks[0]["source"], "p.1")
        self.assertEqual(chunks[1]["chapter"], "2")
        self.assertIn("Batch Processing", chunks[1]["text"])
        self.assertEqual(chunks[1]["source"], "p.2")

    # -------------------------------------------------------------
    # 5. Anti-Cheating Negative Controls
    # -------------------------------------------------------------
    def test_negative_controls_zero_score_on_irrelevant_garbage(self):
        chunks_data = [
            {"heading": "Physics", "text": "Quantum mechanics describes microscopic physical phenomena."},
            {"heading": "Biology", "text": "Cellular respiration produces ATP in the mitochondria."},
            {"heading": "Chemistry", "text": "Chemical kinetics investigates reaction rates and equilibrium."},
            {"heading": "Astronomy", "text": "Galaxies accelerate away under cosmological expansion."},
        ]
        index = make_mock_index(chunks_data)

        # Query with zero matching terms should yield empty scores
        scores = fts_bm25_scores(index, "distributed database consistency linearizability")
        self.assertEqual(scores, {})

        # Trigram search for non-existent symbol should yield empty list
        res = search_trigram(index, "NON_EXISTENT_SYMBOL_12345")
        self.assertEqual(res, [])


if __name__ == "__main__":
    unittest.main()
