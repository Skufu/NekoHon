import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "harnesses"))

import judge as J


def load_rank_answers():
    spec = importlib.util.spec_from_file_location(
        "rank_answers_harness", ROOT / "artifacts" / "harnesses" / "rank-answers.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DigitParseTest(unittest.TestCase):
    def test_plain_digits(self):
        for digit in ("0", "1", "2", "3"):
            self.assertEqual(J._digit_match(digit), digit)

    def test_surrounded_digits(self):
        self.assertEqual(J._digit_match("answer: 2"), "2")
        self.assertEqual(J._digit_match("3 (fully answers)"), "3")

    def test_word_boundary_guard(self):
        self.assertIsNone(J._digit_match("10"))
        self.assertIsNone(J._digit_match("no digit"))

    def test_out_of_range(self):
        self.assertIsNone(J._digit_match("4"))


class DefectKeysTest(unittest.TestCase):
    def test_labels_direct(self):
        cases = {
            "wrong-asked-form": "wrong-asked-form",
            "wrong-subject": "wrong-subject",
            "incomplete-list": "incomplete-list",
            "incomplete-comparison": "incomplete-comparison",
            "false-refusal": "false-refusal",
            "uncited": "uncited",
            "recitation-loop": "recitation-loop",
            "filler-hedge": "filler-hedge",
            "format-drift": "format-drift",
            "invented-claim": "invented-claim",
            "overlong": "overlong",
            "none": "none",
        }
        for reply, expected in cases.items():
            with self.subTest(reply=reply):
                self.assertEqual(J._match(reply, J.DEFECT_KEYS), expected)

    def test_spaced_variants(self):
        self.assertEqual(J._match("wrong subject", J.DEFECT_KEYS), "wrong-subject")
        self.assertEqual(J._match("incomplete comparison", J.DEFECT_KEYS), "incomplete-comparison")
        self.assertEqual(J._match("no defect", J.DEFECT_KEYS), "none")

    def test_no_citation_is_uncited_not_none(self):
        self.assertEqual(J._match("no citation", J.DEFECT_KEYS), "uncited")

    def test_unknown_reply_is_none(self):
        self.assertIsNone(J._match("banana", J.DEFECT_KEYS))


class NotAGateTest(unittest.TestCase):
    def test_judge_module_declares_not_a_gate(self):
        self.assertTrue(J.NOT_A_GATE)

    def test_harness_declares_gate_flags_rejected(self):
        mod = load_rank_answers()
        self.assertIn("--gate", mod.GATE_FLAGS)

    def test_gate_flags_exit_nonzero_before_any_row_is_judged(self):
        mod = load_rank_answers()
        for flag in mod.GATE_FLAGS:
            with self.subTest(flag=flag):
                err = io.StringIO()
                argv = [
                    "rank-answers.py", flag,
                    "--set", "artifacts/datasets/owner-rated-2026-10-15.jsonl",
                ]
                with mock.patch.object(sys, "argv", argv), \
                        mock.patch.object(sys, "stderr", err):
                    with self.assertRaises(SystemExit) as cm:
                        mod.main()
                self.assertNotEqual(cm.exception.code, 0)
                msg = err.getvalue().lower()
                self.assertIn("not a gate", msg)
                self.assertIn("triage dial", msg)
                self.assertIn("owner decision", msg)

    def test_written_log_banner_lines_are_greppable(self):
        mod = load_rank_answers()
        self.assertIn("NOT A GATE", mod.GATE_REJECTION)
        src = (ROOT / "artifacts" / "harnesses" / "rank-answers.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("NOT A GATE", src)
        banner_owner_line = [
            line for line in src.splitlines()
            if "owner labels" in line and "stand-in" in line
        ]
        self.assertTrue(banner_owner_line)
        self.assertIn(
            "# UNVALIDATED against human labels — a triage list, not a score.",
            src,
        )


if __name__ == "__main__":
    unittest.main()
