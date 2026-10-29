"""Instrumentation tests only; generated fixtures are not model-quality proof."""
import importlib.util
import sys
import types
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "artifacts/harnesses"))
import behavioral_eval as E
import observe
from eval_capture import record_engine_calls, protect_evidence


class LegacyCaptureTests(unittest.TestCase):
    def setUp(self):
        self.index = {"book_id": "fixture", "chunks": [{"chunk_id": "p", "chapter": "1", "text": "A buffer holds records temporarily."}]}
        self.result = {"answer": '[Ch. 1] "A buffer holds records temporarily."\nIt keeps records for a short time.', "refused": False, "citations": [{"chunk_id": "p", "chapter": "1", "quote": "A buffer holds records temporarily."}]}
        self.engine = types.SimpleNamespace(ANSWER_MODEL="fixture-not-a-model")
        def ask(index, question, history=None):
            observe.record_retrieval(shown_passages=index["chunks"])
            return self.result
        def respond(index, question, history=None):
            return self.engine.ask(index, question, history=history)
        def explain(index, selection):
            return self.engine.ask(index, selection)
        self.engine.ask, self.engine.respond, self.engine.explain = ask, respond, explain

    def test_nested_calls_emit_once_and_return_the_original_result(self):
        rows = []
        with record_engine_calls(self.engine, observe, rows.append, "fixture-suite"):
            actual = self.engine.respond(self.index, "What is a buffer?")
        self.assertIs(actual, self.result)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["question"], "What is a buffer?")
        self.assertEqual(E.check_capture(rows[0])["defects"], [])

    def test_wrapped_functions_restore_after_a_crashing_suite(self):
        original = self.engine.ask
        with self.assertRaisesRegex(RuntimeError, "suite failure"):
            with record_engine_calls(self.engine, observe, lambda row: None, "fixture-suite"):
                raise RuntimeError("suite failure")
        self.assertIs(self.engine.ask, original)

    def test_existing_trace_still_receives_original_retrieval(self):
        rows = []
        with observe.trace(write_log=False) as outer:
            with record_engine_calls(self.engine, observe, rows.append, "fixture-suite"):
                self.engine.ask(self.index, "What is a buffer?")
            self.assertEqual(outer.shown_passages[0]["chunk_id"], "p")
        self.assertEqual(rows[0]["trace"]["trace_id"], outer.trace_id)

    def test_captured_history_is_not_a_later_mutable_reference(self):
        rows, history = [], [{"question": "What is storage?", "answer": "Stored records."}]
        with record_engine_calls(self.engine, observe, rows.append, "fixture-suite"):
            self.engine.ask(self.index, "What about a buffer?", history=history)
        history[0]["answer"] = "Mutated"
        self.assertEqual(rows[0]["history"][0]["answer"], "Stored records.")


class EvidenceOutputSafetyTests(unittest.TestCase):
    def test_legacy_write_is_blocked_without_damaging_existing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence"
            evidence.mkdir()
            target = evidence / "existing.json"
            target.write_text("original uncommitted evidence", encoding="utf-8")
            with protect_evidence(evidence):
                with self.assertRaises(PermissionError):
                    target.write_text("replacement", encoding="utf-8")
                with self.assertRaises(PermissionError):
                    target.unlink()
                (Path(directory) / "new-capture.json").write_text("allowed", encoding="utf-8")
            self.assertEqual(target.read_text(encoding="utf-8"), "original uncommitted evidence")
            target.write_text("scope ended", encoding="utf-8")
            self.assertEqual(target.read_text(encoding="utf-8"), "scope ended")


class ReaderRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("reader_eval_test", ROOT / "artifacts/harnesses/reader-eval.py")
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    def test_capture_parser_cannot_choose_locked_or_all_split(self):
        with self.assertRaises(SystemExit):
            self.runner.parser().parse_args(["capture", "--dataset", "unused", "--output", "unused", "--split", "all"])

    def test_suite_passes_arguments_to_the_original_runner(self):
        args = self.runner.parser().parse_args(["suite", "--script", "fair-eval.py", "--output", "capture.json", "--", "--split", "dev", "--model", "fixture"])
        self.assertEqual(args.suite_args, ["--", "--split", "dev", "--model", "fixture"])


if __name__ == "__main__":
    unittest.main()
