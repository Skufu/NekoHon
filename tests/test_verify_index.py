"""Index hygiene audit. Synthetic indexes. No book, no Ollama."""

import unittest

from verify_index import audit, exit_code


def clean_index():
    return {
        "embedder": "nomic-embed-text",
        "embedding_dims": 2,
        "chunks": [
            {"chunk_id": "c1-001", "embedding": [1.0, 0.0]},
            {"chunk_id": "c1-002", "embedding": [0.6, 0.8]},
        ],
        "figures": [
            {"id": "figure-1-1", "embedding": [0.0, 1.0]},
        ],
    }


class AuditTests(unittest.TestCase):
    def test_clean_index_reports_no_problems(self):
        report = audit(clean_index())
        self.assertEqual(report["vectors"], 3)
        self.assertEqual(report["nonfinite"], [])
        self.assertEqual(report["zero_norm"], [])
        self.assertEqual(report["dim_drift"], [])
        self.assertEqual(report["missing"], [])
        self.assertFalse(report["no_declared_dims"])

    def test_a_non_finite_value_names_the_chunk(self):
        index = clean_index()
        index["chunks"][0]["embedding"] = [float("nan"), 0.5]
        report = audit(index)
        self.assertEqual(report["nonfinite"], ["chunk c1-001"])

    def test_a_zero_vector_names_the_figure(self):
        index = clean_index()
        index["figures"][0]["embedding"] = [0.0, 0.0]
        report = audit(index)
        self.assertEqual(report["zero_norm"], ["figure figure-1-1"])

    def test_width_drift_names_the_record(self):
        index = clean_index()
        index["chunks"][1]["embedding"] = [0.1, 0.2, 0.3]
        report = audit(index)
        self.assertEqual(report["dim_drift"], ["chunk c1-002 (3 wide)"])

    def test_a_missing_vector_is_listed_and_exits_dirty(self):
        index = clean_index()
        index["chunks"][0].pop("embedding")
        report = audit(index)
        self.assertEqual(report["missing"], ["chunk c1-001"])
        self.assertEqual(exit_code(report), 1)

    def test_a_clean_report_exits_0(self):
        self.assertEqual(exit_code(audit(clean_index())), 0)

    def test_vectors_without_declared_dims_are_flagged(self):
        index = clean_index()
        index.pop("embedding_dims")
        report = audit(index)
        self.assertTrue(report["no_declared_dims"])
        self.assertEqual(exit_code(report), 1)


if __name__ == "__main__":
    unittest.main()
