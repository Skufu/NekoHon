"""Preflight helper tests. Pure logic only: no Ollama, no server, no index."""

import unittest

from scripts.preflight import audit_clean, model_present, next_steps, version_ok


def _state(**overrides):
    state = {
        "python_ok": True,
        "book": True,
        "index": True,
        "ollama": True,
        "missing_models": [],
        "audit_clean": True,
    }
    state.update(overrides)
    return state


class PreflightTests(unittest.TestCase):
    def test_version_floor(self):
        self.assertFalse(version_ok((3, 8)))
        self.assertTrue(version_ok((3, 9)))
        self.assertTrue(version_ok((3, 12)))

    def test_model_matches_itself_and_any_tag(self):
        self.assertTrue(model_present(["qwen2.5:7b"], "qwen2.5:7b"))
        self.assertTrue(model_present(["nomic-embed-text:latest"], "nomic-embed-text"))
        self.assertFalse(
            model_present(["nomic-embed-text-v2:latest"], "nomic-embed-text")
        )

    def test_ready_state_prints_the_serve_step(self):
        steps = next_steps(_state())
        self.assertEqual(len(steps), 1)
        self.assertIn("server.py", steps[0])

    def test_missing_book_comes_before_the_index_build(self):
        steps = next_steps(_state(book=False, index=False, audit_clean=None))
        self.assertTrue(steps[0].startswith("put the EPUB"))
        self.assertTrue(any("ingest.py" in step for step in steps))

    def test_ollama_down_is_named_and_models_are_not_pulled_blind(self):
        steps = next_steps(
            _state(ollama=False, missing_models=["qwen2.5:7b"], audit_clean=True)
        )
        self.assertTrue(any("Ollama" in step for step in steps))
        self.assertFalse(any("ollama pull" in step for step in steps))

    def test_missing_model_is_a_pull_step(self):
        steps = next_steps(_state(missing_models=["qwen2.5:7b"]))
        self.assertEqual(steps[0], "pull the model: ollama pull qwen2.5:7b")

    def test_dirty_index_is_flagged(self):
        steps = next_steps(_state(audit_clean=False))
        self.assertTrue(any("audit" in step for step in steps))

    def test_audit_clean_flags_each_axis(self):
        clean = {
            "no_declared_dims": False,
            "missing": [],
            "nonfinite": [],
            "zero_norm": [],
            "dim_drift": [],
        }
        self.assertTrue(audit_clean(clean))
        self.assertFalse(audit_clean(dict(clean, dim_drift=["chunk ch01-001"])))
        self.assertFalse(audit_clean(dict(clean, missing=["figure figure-1-1"])))


if __name__ == "__main__":
    unittest.main()
