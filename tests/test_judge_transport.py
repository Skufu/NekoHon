"""Behavioral tests for the judge's CLI transport and its strict parsers.

No CLI, no network, no key: the transport is exercised through `_CLI_RUNNER`,
which is the exact seam production uses. The cases are the ones that decide a
judge call: success, fallback, total failure, timeout, malformed stream, tool
use, disabled-tool agent config, and the provenance a caller copies from
`LAST_CALL`.
"""

import contextlib
import hashlib
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "harnesses"))

import judge as J  # noqa: E402

PRIMARY = "opencode/deepseek-v4.1-flash-free"
FALLBACK = "opencode-go/deepseek-v4.1-flash"


def ndjson(*events):
    return "\n".join(json.dumps(event) for event in events) + "\n"


def text_event(text):
    return {"type": "text", "part": {"type": "text", "text": text}}


def step_event():
    return {"type": "step_start", "part": {"type": "step-start"}}


def tool_event(name="shell"):
    return {
        "type": "tool_use",
        "part": {"type": "tool", "tool": name, "state": {"status": "completed"}},
    }


def ok(reply="yes"):
    return {
        "exit_code": 0,
        "stdout": ndjson(step_event(), text_event(reply)),
        "stderr": "",
        "timed_out": False,
        "duration_ms": 11,
    }


def failed(stderr="relay exploded", stdout="", exit_code=1):
    return {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": False,
        "duration_ms": 40,
    }


def timed_out():
    return {"exit_code": None, "stdout": "", "stderr": "killed", "timed_out": True, "duration_ms": 5000}


class FakeRunner:
    """Records each CLI invocation and replays canned results in order."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, args, stdin_text, timeout, cwd, env):
        config_root = env.get("XDG_CONFIG_HOME", "")
        agent_path = os.path.join(config_root, "opencode", "agent", "verdict-only.md")
        self.calls.append(
            {
                "args": list(args),
                "stdin": stdin_text,
                "timeout": timeout,
                "cwd": cwd,
                "cwd_exists": os.path.isdir(cwd),
                "cwd_entries": sorted(os.listdir(cwd)) if os.path.isdir(cwd) else None,
                "env": dict(env),
                "config_root": config_root,
                "config_root_exists": os.path.isdir(config_root),
                "agent_path": agent_path,
                "agent_markdown": (
                    Path(agent_path).read_text(encoding="utf-8")
                    if os.path.isfile(agent_path)
                    else None
                ),
            }
        )
        index = min(len(self.calls) - 1, len(self.results) - 1)
        result = self.results[index]
        if callable(result):
            return result(args, stdin_text, timeout, cwd, env)
        return result


@contextlib.contextmanager
def cli(results, model=PRIMARY, backend="cli"):
    runner = FakeRunner(results)
    with mock.patch.object(J, "JUDGE_BACKEND", backend), \
            mock.patch.object(J, "JUDGE_MODEL", model), \
            mock.patch.object(J, "_CLI_RUNNER", runner), \
            mock.patch.object(J, "_cli_version", lambda: "opencode test-build"):
        yield runner


class DefaultsTest(unittest.TestCase):
    def test_primary_is_the_free_flash_model_and_the_fallback_is_fixed(self):
        self.assertEqual(J.CLI_MODEL, PRIMARY)
        self.assertEqual(J.CLI_FALLBACK, FALLBACK)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JUDGE_FALLBACK_MODEL", None)
            self.assertEqual(J._fallback_model(), FALLBACK)

    def test_an_arbitrary_fallback_is_refused_not_honored(self):
        with mock.patch.dict(os.environ, {"JUDGE_FALLBACK_MODEL": "openai/gpt-5"}):
            with self.assertRaises(RuntimeError) as raised:
                J._fallback_model()
        self.assertIn(FALLBACK, str(raised.exception))

    def test_an_arbitrary_fallback_stops_the_call_before_the_cli_runs(self):
        with cli([ok("yes")]) as runner:
            with mock.patch.dict(os.environ, {"JUDGE_FALLBACK_MODEL": "anything/else"}):
                with self.assertRaises(RuntimeError):
                    J._complete("s", "u", PRIMARY, 5)
        self.assertEqual(runner.calls, [])

    def test_default_cloud_model_is_deepseek_flash(self):
        self.assertEqual(J.CLOUD_MODEL, "deepseek-v4.1-flash")
        self.assertEqual(J._default_model("openai"), "deepseek-v4.1-flash")
        self.assertEqual(J._default_model("cli"), PRIMARY)
        self.assertEqual(J._default_model("opencode"), PRIMARY)
        self.assertEqual(J._default_model("ollama"), J.OLLAMA_MODEL)

    def test_cloud_wire_and_output_budget_suite_the_reasoning_model(self):
        self.assertEqual(J.JUDGE_WIRE, os.environ.get("JUDGE_WIRE", "responses"))
        self.assertEqual(
            J.JUDGE_MAX_OUTPUT, int(os.environ.get("JUDGE_MAX_OUTPUT", "12000"))
        )

    def test_unknown_backend_fails_closed(self):
        with mock.patch.object(J, "JUDGE_BACKEND", "bogus"):
            with self.assertRaises(RuntimeError):
                J._complete("s", "u", PRIMARY, 5)


class CliSuccessTest(unittest.TestCase):
    def test_primary_success_returns_text_and_records_provenance(self):
        with cli([ok("yes")]) as runner:
            raw = J._complete("SYS-PROMPT", "USER-BODY", PRIMARY, 5)
        self.assertEqual(raw, "yes")
        call = dict(J.LAST_CALL)
        self.assertEqual(call["model_used"], PRIMARY)
        self.assertEqual(call["model_requested"], PRIMARY)
        self.assertFalse(call["fallback_used"])
        self.assertEqual(call["transport"], "opencode-cli")
        self.assertEqual(len(call["attempts"]), 1)
        attempt = call["attempts"][0]
        self.assertEqual(attempt["reply"], "yes")
        self.assertEqual(attempt["reply_sha256"], hashlib.sha256(b"yes").hexdigest())
        self.assertEqual(attempt["exit_code"], 0)
        self.assertEqual(attempt["error"], "")
        self.assertEqual(call["reply_sha256"], hashlib.sha256(b"yes").hexdigest())
        # The hashes describe the bytes actually sent on stdin.
        sent = runner.calls[0]["stdin"]
        self.assertEqual(call["prompt"]["payload_sha256"], hashlib.sha256(sent.encode()).hexdigest())
        self.assertEqual(
            call["prompt"]["system_sha256"], hashlib.sha256(b"SYS-PROMPT").hexdigest()
        )
        self.assertEqual(
            call["prompt"]["user_sha256"], hashlib.sha256(b"USER-BODY").hexdigest()
        )
        self.assertIn("SYS-PROMPT", sent)
        self.assertIn("USER-BODY", sent)
        self.assertEqual(J.judge_name_actual(), PRIMARY)

    def test_command_runs_standalone_json_against_the_tool_free_agent(self):
        with cli([ok("no")]) as runner:
            J._complete("s", "u", PRIMARY, 5)
        args = runner.calls[0]["args"]
        self.assertEqual(args[0], J.JUDGE_CLI)
        self.assertIn("run", args)
        self.assertIn("--standalone", args)
        self.assertEqual(args[args.index("--agent") + 1], "verdict-only")
        self.assertEqual(args[args.index("--format") + 1], "json")
        self.assertEqual(args[args.index("--model") + 1], PRIMARY)
        for forbidden in ("--continue", "-c", "--session", "-s", "--file", "-f", "--auto"):
            self.assertNotIn(forbidden, args)

    def test_tools_are_disabled_before_the_call_by_an_isolated_agent(self):
        with cli([ok("yes")]) as runner:
            J._complete("s", "u", PRIMARY, 5)
        call = runner.calls[0]
        config_root = call["config_root"]
        self.assertTrue(call["config_root_exists"])
        self.assertTrue(os.path.isabs(config_root))
        self.assertFalse(
            os.path.abspath(config_root).startswith(str(ROOT)),
            "the agent config lives outside the workspace",
        )
        markdown = call["agent_markdown"] or ""
        for tool in ("bash", "read", "edit", "write", "glob", "grep", "list", "webfetch", "task"):
            self.assertIn(f"{tool}: false", markdown)
        self.assertIn("mode: primary", markdown)
        self.assertEqual(call["env"]["XDG_CONFIG_HOME"], config_root)
        self.assertNotIn("OPENCODE_CONFIG", call["env"])
        # The private config root is removed with the call.
        self.assertFalse(os.path.exists(config_root))

    def test_each_attempt_runs_in_an_empty_temp_directory(self):
        with cli([ok("yes")]) as runner:
            J._complete("s", "u", PRIMARY, 5)
        call = runner.calls[0]
        self.assertTrue(call["cwd_exists"])
        self.assertEqual(call["cwd_entries"], [])
        self.assertNotEqual(call["cwd"], call["config_root"])
        self.assertFalse(os.path.exists(call["cwd"]), "sandbox directory is removed after the call")

    def test_one_wall_clock_budget_covers_both_attempts(self):
        def slow_failure(_args, _stdin, _timeout, _cwd, _env):
            time.sleep(1.2)
            return failed("slow relay", exit_code=1)

        with cli([slow_failure, ok("yes")]) as runner:
            raw = J._complete("s", "u", PRIMARY, 2.0)
        self.assertEqual(raw, "yes")
        self.assertLessEqual(J.LAST_CALL["budget_seconds"], 2.0)
        first, second = runner.calls[0], runner.calls[1]
        self.assertLessEqual(first["timeout"], 2.0)
        self.assertLess(second["timeout"], 0.95, "the fallback only gets what is left")
        self.assertLessEqual(J.LAST_CALL["attempts"][1]["seconds_allowed"], 0.95)

    def test_no_fallback_is_started_with_a_sliver_of_the_budget(self):
        def slow_failure(_args, _stdin, _timeout, _cwd, _env):
            time.sleep(0.75)
            return failed("slow relay", exit_code=1)

        with cli([slow_failure]) as runner:
            with self.assertRaises(J.JudgeTransportError) as raised:
                J._complete("s", "u", PRIMARY, 1.0)
        self.assertEqual(len(runner.calls), 1)
        self.assertIn("no time left", str(raised.exception))
        self.assertLess(J.LAST_CALL["duration_ms"], 2000)


class CliFallbackTest(unittest.TestCase):
    def test_failure_falls_back_exactly_once_and_records_the_error(self):
        with cli([failed("relay exploded"), ok("no")]) as runner:
            raw = J._complete("s", "u", PRIMARY, 5)
        self.assertEqual(raw, "no")
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(runner.calls[1]["args"][runner.calls[1]["args"].index("--model") + 1], FALLBACK)
        call = dict(J.LAST_CALL)
        self.assertEqual(call["model_used"], FALLBACK)
        self.assertTrue(call["fallback_used"])
        self.assertEqual([a["model"] for a in call["attempts"]], [PRIMARY, FALLBACK])
        primary = call["attempts"][0]
        self.assertIn("exited 1", primary["error"])
        self.assertIn("relay exploded", primary["stderr_tail"])
        self.assertTrue(primary["stderr_sha256"])
        self.assertEqual(primary["reply"], "")

    def test_both_fail_raises_and_keeps_both_attempts(self):
        with cli([failed("primary down"), failed("fallback down")]):
            with self.assertRaises(J.JudgeTransportError) as raised:
                J._complete("s", "u", PRIMARY, 5)
        message = str(raised.exception)
        self.assertIn("primary down", message)
        self.assertIn("fallback down", message)
        call = dict(J.LAST_CALL)
        self.assertEqual(call["model_used"], "")
        self.assertEqual(len(call["attempts"]), 2)
        self.assertIn(PRIMARY, call["error"])
        self.assertIn(FALLBACK, call["error"])
        self.assertTrue(call["prompt"]["payload_sha256"])

    def test_timeout_fails_the_attempt_then_falls_back(self):
        with cli([timed_out(), ok("yes")]):
            raw = J._complete("s", "u", PRIMARY, 5)
        self.assertEqual(raw, "yes")
        self.assertIn("timeout", J.LAST_CALL["attempts"][0]["error"])
        self.assertTrue(J.LAST_CALL["attempts"][0]["timed_out"])
        self.assertTrue(J.LAST_CALL["fallback_used"])

    def test_both_timeouts_raise(self):
        with cli([timed_out(), timed_out()]):
            with self.assertRaises(J.JudgeTransportError):
                J._complete("s", "u", PRIMARY, 5)

    def test_missing_cli_binary_falls_back(self):
        def missing(*_args):
            raise FileNotFoundError("opencode not found")

        with cli([missing, ok("yes")]):
            raw = J._complete("s", "u", PRIMARY, 5)
        self.assertEqual(raw, "yes")
        self.assertIn("FileNotFoundError", J.LAST_CALL["attempts"][0]["error"])

    def test_explicit_model_gets_no_fallback(self):
        with cli([failed("nope")]) as runner:
            with self.assertRaises(J.JudgeTransportError):
                J._complete("s", "u", "opencode/glm-5.3-flash", 5)
        self.assertEqual(len(runner.calls), 1)
        call = dict(J.LAST_CALL)
        self.assertEqual(call["fallback_model"], "")
        self.assertEqual(call["attempts"][0]["model"], "opencode/glm-5.3-flash")


class CliFailClosedTest(unittest.TestCase):
    def test_malformed_stream_is_not_a_verdict(self):
        garbage = "this is not json\n" + json.dumps(["not", "an", "event"]) + "\n"
        with cli([failed(stdout=garbage, exit_code=0), ok("yes")]):
            raw = J._complete("s", "u", PRIMARY, 5)
        self.assertEqual(raw, "yes")
        attempt = J.LAST_CALL["attempts"][0]
        self.assertEqual(attempt["malformed_lines"], 2)
        self.assertIn("no assistant text", attempt["error"])
        self.assertTrue(attempt["stdout_sha256"])

    def test_stream_without_text_fails(self):
        with cli([failed(stdout=ndjson(step_event()), exit_code=0), ok("no")]):
            J._complete("s", "u", PRIMARY, 5)
        self.assertIn("no assistant text", J.LAST_CALL["attempts"][0]["error"])

    def test_tool_use_is_rejected_even_when_text_follows(self):
        stream = ndjson(step_event(), tool_event("shell"), text_event("yes"))
        with cli([failed(stdout=stream, exit_code=0), ok("no")]):
            raw = J._complete("s", "u", PRIMARY, 5)
        self.assertEqual(raw, "no", "a tool-using turn never supplies the verdict")
        primary = J.LAST_CALL["attempts"][0]
        self.assertEqual(primary["tools"], ["shell"])
        self.assertIn("tool", primary["error"])
        self.assertEqual(primary["reply"], "")

    def test_tool_use_with_no_fallback_raises(self):
        stream = ndjson(tool_event("read"), text_event("yes"))
        with cli([failed(stdout=stream, exit_code=0), failed(stdout=stream, exit_code=0)]):
            with self.assertRaises(J.JudgeTransportError):
                J._complete("s", "u", PRIMARY, 5)
        self.assertEqual(J.LAST_CALL["attempts"][0]["tools"], ["read"])

    def test_error_event_is_reported_not_parsed(self):
        stream = ndjson({"type": "error", "error": {"message": "Agent not found"}}, text_event("yes"))
        with cli([failed(stdout=stream, exit_code=0), ok("yes")]):
            J._complete("s", "u", PRIMARY, 5)
        self.assertIn("Agent not found", J.LAST_CALL["attempts"][0]["error"])


class StrictParserTest(unittest.TestCase):
    def test_exact_labels_and_aliases_are_accepted(self):
        self.assertEqual(J._match("yes", J.YES_NO_KEYS), "yes")
        self.assertEqual(J._match(" No. ", J.YES_NO_KEYS), "no")
        self.assertEqual(J._match("not_relevant", J.RELEVANCE_KEYS), "not_relevant")
        self.assertEqual(J._match("unsupported", J.FIDELITY_KEYS), "unsupported")
        self.assertEqual(J._match("none", J.EXAMPLE_KEYS), "none")
        self.assertEqual(J._match("states", J.KEY_FACT_KEYS), "states")

    def test_paraphrase_is_not_a_verdict(self):
        self.assertIsNone(J._match("The answer is yes", J.YES_NO_KEYS))
        self.assertIsNone(J._match("I would say this is relevant", J.RELEVANCE_KEYS))
        self.assertIsNone(J._match("not relevant at all", J.RELEVANCE_KEYS))

    def test_two_labels_fold_closed(self):
        self.assertIsNone(J._match("yes and no", J.YES_NO_KEYS))
        self.assertIsNone(J._match("", J.YES_NO_KEYS))

    def test_digit_parser_rejects_ambiguity(self):
        self.assertEqual(J._digit_match("3"), "3")
        self.assertEqual(J._digit_match("answer: 2"), "2")
        self.assertEqual(J._digit_match("3 (fully answers)"), "3")
        self.assertIsNone(J._digit_match("2 and 3"))
        self.assertIsNone(J._digit_match("10"))
        self.assertIsNone(J._digit_match("4"))
        self.assertIsNone(J._digit_match(""))


class VerdictRetryTest(unittest.TestCase):
    def test_a_paraphrase_gets_one_strict_reask(self):
        replies = ["The answer is yes", "yes"]
        with mock.patch.object(J, "_complete", side_effect=replies) as complete:
            label = J.judge_relevance("What is a buffer?", "A buffer holds records.")
        self.assertEqual(label, "relevant")
        self.assertEqual(complete.call_count, 2)
        self.assertIn("Reply with exactly one of", complete.call_args_list[1][0][0])
        self.assertEqual(J.LAST_REPLY["text"], "yes")

    def test_a_second_miss_is_judge_error_not_a_guess(self):
        replies = ["The answer is yes", "still unclear"]
        with mock.patch.object(J, "_complete", side_effect=replies):
            label = J.judge_relevance("q", "p")
        self.assertEqual(label, "judge_error")
        self.assertEqual(J.LAST_REPLY["text"], "still unclear")

    def test_digit_axis_reask_and_fail_closed(self):
        with mock.patch.object(J, "_complete", side_effect=["I rate it 2 of 3", "2"]):
            self.assertEqual(J.judge_form("q", "a"), "2")
        with mock.patch.object(J, "_complete", side_effect=["I rate it 2 of 3", "2 or 3"]):
            self.assertIsNone(J.judge_form("q", "a"))


class TransportContractTest(unittest.TestCase):
    def test_the_parent_contract_is_raw_text_plus_last_call(self):
        with cli([ok("supported")]):
            raw = J._complete(J.FIDELITY_SYSTEM, "Question: q", J.CLI_MODEL, 5)
            transport = dict(J.LAST_CALL)
        self.assertIsInstance(raw, str)
        for key in ("backend", "transport", "model_requested", "model_used",
                    "fallback_used", "prompt", "attempts", "duration_ms",
                    "agent", "tools_disabled", "standalone", "budget_seconds"):
            self.assertIn(key, transport)
        for key in ("system_sha256", "user_sha256", "payload_sha256", "payload_chars"):
            self.assertIn(key, transport["prompt"])
        self.assertEqual(J._match(raw, J.FIDELITY_KEYS), "supported")

    def test_last_call_is_reset_between_calls(self):
        with cli([failed("first down"), ok("yes")]):
            J._complete("s", "u", PRIMARY, 5)
        self.assertEqual(len(J.LAST_CALL["attempts"]), 2)
        with cli([ok("no")]):
            J._complete("s", "u", PRIMARY, 5)
        self.assertEqual(len(J.LAST_CALL["attempts"]), 1)
        self.assertFalse(J.LAST_CALL["fallback_used"])
        self.assertEqual(J.LAST_CALL["error"], "")


class BackendOverrideTest(unittest.TestCase):
    def test_openai_override_still_uses_the_cloud_wire(self):
        def runner(*_args):
            raise AssertionError("CLI must not run when JUDGE_BACKEND=openai")

        with mock.patch.object(J, "JUDGE_BACKEND", "openai"), \
                mock.patch.object(J, "JUDGE_MODEL", J.CLOUD_MODEL), \
                mock.patch.object(J, "JUDGE_WIRE", "responses"), \
                mock.patch.object(J, "_cloud_complete", return_value="supported"), \
                mock.patch.object(J, "_CLI_RUNNER", runner):
            raw = J._complete("s", "u", J.CLOUD_MODEL, 5)
        self.assertEqual(raw, "supported")
        call = dict(J.LAST_CALL)
        self.assertEqual(call["backend"], "openai")
        self.assertEqual(call["transport"], "http-json")
        self.assertEqual(call["model_used"], "deepseek-v4.1-flash")
        self.assertEqual(call["attempts"], [])
        self.assertTrue(call["prompt"]["payload_sha256"])

    def test_openai_payload_carries_the_deepseek_model(self):
        payload = J._cloud_payload("sys", "user", J.CLOUD_MODEL)
        self.assertEqual(payload["model"], "deepseek-v4.1-flash")
        self.assertGreater(payload["max_output_tokens"], 2048)

    def test_ollama_override_stays_local(self):
        with mock.patch.object(J, "JUDGE_BACKEND", "ollama"), \
                mock.patch.object(J, "JUDGE_MODEL", J.OLLAMA_MODEL), \
                mock.patch.object(J.A, "ollama_generate", return_value="no") as local:
            raw = J._complete("s", "u", J.OLLAMA_MODEL, 5)
        self.assertEqual(raw, "no")
        local.assert_called_once()
        call = dict(J.LAST_CALL)
        self.assertEqual(call["backend"], "ollama")
        self.assertEqual(call["transport"], "ollama-localhost")
        self.assertEqual(call["reply_sha256"], hashlib.sha256(b"no").hexdigest())

    def test_cloud_error_is_recorded_then_raised(self):
        with mock.patch.object(J, "JUDGE_BACKEND", "openai"), \
                mock.patch.object(J, "_cloud_complete", side_effect=RuntimeError("judge HTTP 503")):
            with self.assertRaises(RuntimeError):
                J._complete("s", "u", J.CLOUD_MODEL, 5)
        self.assertIn("503", J.LAST_CALL["error"])
        self.assertTrue(J.LAST_CALL["prompt"]["payload_sha256"])


if __name__ == "__main__":
    unittest.main()
