"""Harness tests for ``artifacts/harnesses/ux-eval.py``.

These test the runner's own plumbing — CLI JSON parsing, the isolated command
line, timeout/error propagation, refusal matching, and the rule that a blocked
step fails the run. They start no browser and touch no network; the live proof
is the dated ``artifacts/runs/ux-eval-*`` run.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ux_eval_harness", ROOT / "artifacts" / "harnesses" / "ux-eval.py"
)
assert SPEC and SPEC.loader
ux = importlib.util.module_from_spec(SPEC)
sys.modules["ux_eval_harness"] = ux
SPEC.loader.exec_module(ux)


def completed(argv, code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, code, stdout, stderr)


class FakeBrowser:
    """Only the surface ``UxSmoke._run_step`` touches."""

    def __init__(self) -> None:
        self.shots = 0

    def screenshot(self, path: Path):
        self.shots += 1
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        return path


class CliJsonParsingTests(unittest.TestCase):
    def test_clean_payload(self):
        payload = ux.parse_cli_json('{"success": true, "data": {"result": 2}}')
        self.assertEqual(payload["data"]["result"], 2)

    def test_warning_before_the_json_object_is_tolerated(self):
        stdout = 'warning: something\n{"success": true, "data": {"url": "http://x"}}\n'
        self.assertEqual(ux.parse_cli_json(stdout)["data"]["url"], "http://x")

    def test_non_json_output_is_an_error_not_an_empty_success(self):
        with self.assertRaises(ux.HarnessError):
            ux.parse_cli_json("just words")

    def test_empty_output_is_an_error(self):
        with self.assertRaises(ux.HarnessError):
            ux.parse_cli_json("   ")


class CommandBuildingTests(unittest.TestCase):
    def test_session_flag_is_always_passed(self):
        argv = ux.browser_command("agent-browser", "eval-ux-worker", "open", "http://x")
        self.assertEqual(argv[:4], ["agent-browser", "--session", "eval-ux-worker", "open"])
        self.assertEqual(argv[-1], "--json")

    def test_windows_batch_shim_is_wrapped(self):
        argv = ux.browser_command(
            r"C:\npm\agent-browser.CMD", "eval-ux-worker", "eval", "1+1"
        )
        self.assertEqual(argv[:4], ["cmd", "/c", r"C:\npm\agent-browser.CMD", "--session"])
        self.assertIn("eval-ux-worker", argv)
        self.assertEqual(argv[-1], "--json")

    def test_snapshot_can_skip_json(self):
        argv = ux.browser_command(
            "agent-browser", "eval-ux-worker", "snapshot", "-i", "-c", json_output=False
        )
        self.assertNotIn("--json", argv)


class CommandExecutionTests(unittest.TestCase):
    def test_output_is_captured_with_file_backed_runner(self):
        result = ux.run_command([sys.executable, "-c", "print('hello from child')"], timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello from child", result.stdout)

    def test_a_real_timeout_raises_instead_of_hanging(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            ux.run_command(
                [sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.5
            )


class BrowserErrorHandlingTests(unittest.TestCase):
    def browser(self, runner):
        return ux.Browser(
            session="eval-ux-worker", executable="agent-browser", runner=runner,
            command_timeout=5,
        )

    def test_nonzero_exit_raises_with_stderr(self):
        browser = self.browser(lambda argv, **kw: completed(argv, 1, "", "boom"))
        with self.assertRaises(ux.HarnessError) as ctx:
            browser.eval("1+1")
        self.assertIn("boom", str(ctx.exception))

    def test_success_false_payload_raises(self):
        payload = json.dumps({"success": False, "data": None, "error": "no element"})
        browser = self.browser(lambda argv, **kw: completed(argv, 0, payload, ""))
        with self.assertRaises(ux.HarnessError) as ctx:
            browser.cmd("click", "#nope")
        self.assertIn("no element", str(ctx.exception))

    def test_timeout_is_reported_as_timeout(self):
        def runner(argv, **kw):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kw.get("timeout", 5))

        with self.assertRaises(ux.HarnessError) as ctx:
            self.browser(runner).eval("1+1")
        self.assertIn("timeout", str(ctx.exception).lower())

    def test_missing_executable_is_tool_unavailable(self):
        def runner(argv, **kw):
            raise OSError("not found")

        with self.assertRaises(ux.ToolUnavailable):
            self.browser(runner).eval("1+1")

    def test_eval_without_result_is_an_error(self):
        payload = json.dumps({"success": True, "data": {"origin": "x"}, "error": None})
        browser = self.browser(lambda argv, **kw: completed(argv, 0, payload, ""))
        with self.assertRaises(ux.HarnessError):
            browser.eval("1+1")

    def test_screenshot_must_actually_write_a_file(self):
        payload = json.dumps({"success": True, "data": {"path": "x"}, "error": None})
        browser = self.browser(lambda argv, **kw: completed(argv, 0, payload, ""))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ux.HarnessError):
                browser.screenshot(Path(tmp) / "shot.png")

    def test_multiline_js_is_sent_as_one_line(self):
        seen = {}

        def runner(argv, **kw):
            seen["argv"] = argv
            payload = json.dumps({"success": True, "data": {"result": 1}, "error": None})
            return completed(argv, 0, payload, "")

        ux.Browser(
            session="eval-ux-worker", executable="agent-browser", runner=runner
        ).eval("(() => {\n  const a = 1;\n  return a;\n})()")
        js_arg = seen["argv"][seen["argv"].index("eval") + 1]
        self.assertNotIn("\n", js_arg)
        self.assertIn("const a = 1;", js_arg)


class WaitTests(unittest.TestCase):
    def test_returns_the_state_that_matched(self):
        class Eval:
            def eval(self, js):
                return {"ready": True, "value": 7}

        state = ux.Browser.wait_for(
            Eval(), "js", lambda s: s.get("ready"), "a ready page",
            timeout=1, sleep=lambda s: None,
        )
        self.assertEqual(state["value"], 7)

    def test_timeout_is_a_check_failure_with_the_last_state(self):
        class Eval:
            def eval(self, js):
                return {"ready": False, "reason": "no-card"}

        with self.assertRaises(ux.CheckFailed) as ctx:
            ux.Browser.wait_for(
                Eval(), "js", lambda s: s.get("ready"), "an answer",
                timeout=0, sleep=lambda s: None,
            )
        self.assertIn("an answer", str(ctx.exception))
        self.assertIn("no-card", str(ctx.exception))

    def test_a_transient_command_error_is_retried(self):
        class Eval:
            def __init__(self):
                self.calls = 0

            def eval(self, js):
                self.calls += 1
                if self.calls == 1:
                    raise ux.HarnessError("dev server reloaded")
                return {"ready": True}

        fake = Eval()
        state = ux.Browser.wait_for(
            fake, "js", lambda s: s.get("ready"), "a ready page",
            timeout=1, sleep=lambda s: None,
        )
        self.assertTrue(state["ready"])
        self.assertEqual(fake.calls, 2)


class OutcomeHelpersTests(unittest.TestCase):
    def test_refusal_is_exactly_the_sentence(self):
        self.assertTrue(ux.refusal_is_clean("Not in this book.", None))
        self.assertTrue(ux.refusal_is_clean("  Not in this book.  ", None))

    def test_refusal_with_elaboration_is_not_clean(self):
        self.assertFalse(ux.refusal_is_clean("Not in this book. The book is about data.", None))

    def test_refusal_rendered_as_an_error_is_not_clean(self):
        self.assertFalse(ux.refusal_is_clean("Not in this book.", "engine unreachable"))

    def test_passage_count_is_read_from_the_library_card(self):
        self.assertEqual(
            ux.parse_passage_count("Reis, Joe; Housley, Matt · 1,042 passages"), 1042
        )
        self.assertEqual(ux.parse_passage_count("Vivek Kalyanarangan · 473 passages"), 473)
        self.assertIsNone(ux.parse_passage_count("no count here"))


class MarkedQuoteTests(unittest.TestCase):
    QUOTE = (
        "A watermark (Figure 8-8) is a threshold used by a window to determine "
        "whether data in a window is within the established time interval."
    )

    def test_presentation_quotes_and_wrapping_are_folded(self):
        self.assertEqual(
            ux.normalize_quote_text(f"“{self.QUOTE}”"),
            ux.normalize_quote_text(self.QUOTE),
        )
        self.assertEqual(
            ux.normalize_quote_text("one\ntwo   three"), "one two three"
        )

    def test_marked_text_must_be_the_offered_quote(self):
        self.assertTrue(ux.quote_is_marked(f"“{self.QUOTE}”", self.QUOTE))
        self.assertFalse(ux.quote_is_marked("a different sentence entirely", self.QUOTE))

    def test_a_bare_chip_only_requires_a_non_empty_mark(self):
        self.assertTrue(ux.quote_is_marked(self.QUOTE, None))
        self.assertFalse(ux.quote_is_marked("   ", None))
        self.assertFalse(ux.quote_is_marked("", self.QUOTE))

    def test_mark_probe_reads_text_content_not_inner_text(self):
        # innerText of a mark inside a content-visibility chunk is "" until the
        # block paints (measured); the marked run must come from textContent.
        self.assertIn("markText: (mark?.textContent", ux.JUMP_STATE)


class StepAccountingTests(unittest.TestCase):
    def test_failed_step_makes_the_run_non_green(self):
        result = ux.RunResult(meta={})
        step = ux.Step(name="answer", description="answer appears")
        step.fail("no answer")
        result.steps.append(step)
        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.as_dict()["failures"][0]["step"], "answer")

    def test_infra_error_exits_two(self):
        result = ux.RunResult(meta={}, error="agent-browser missing")
        self.assertEqual(result.exit_code, 2)

    def test_a_blocked_dependent_step_fails_the_run_and_is_never_a_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            smoke = ux.UxSmoke(
                ux.Config(out=Path(tmp), budget_s=30), FakeBrowser()
            )

            def fails(step):
                step.require("library reached", False, True, False)

            first = smoke._run_step("library", "library", fails)
            second = smoke._run_step("open-book", "open", lambda step: None,
                                     depends_on="library")
            self.assertEqual(first.status, "failed")
            self.assertEqual(second.status, "blocked")
            self.assertFalse(second.ok)
            self.assertEqual(smoke.result.exit_code, 1)
            self.assertEqual(smoke.result.as_dict()["failures"][1]["status"], "blocked")

    def test_an_unexpected_exception_is_a_failure_not_a_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            smoke = ux.UxSmoke(
                ux.Config(out=Path(tmp), budget_s=30), FakeBrowser()
            )

            def explode(step):
                raise RuntimeError("kaboom")

            step = smoke._run_step("explode", "explode", explode)
            self.assertEqual(step.status, "failed")
            self.assertIn("kaboom", step.error or "")
            self.assertEqual(smoke.result.exit_code, 1)

    def test_a_passing_run_is_green(self):
        result = ux.RunResult(meta={})
        step = ux.Step(name="library", description="library", status="passed")
        result.steps.append(step)
        self.assertTrue(result.ok)
        self.assertEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
