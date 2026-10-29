#!/usr/bin/env python
"""Live UX smoke for the Nekohon reader (agent-browser only).

What this measures is what a reader sees, not what the source says: the library
opens, a book renders, a typed question submitted with Enter produces an answer,
a citation chip moves the book pane and the return pill moves it back, an
out-of-book question is exactly ``Not in this book.``, and switching volumes
leaves no note behind. Every step drives a real browser through the
``agent-browser`` CLI in an isolated session; nothing is mocked.

The run writes one dated JSON file with per-step checks and screenshots under
``artifacts/runs/ux-eval-<UTC>/``. A failed check, a timeout, an unreachable
browser, or a page that never reaches the expected state exits non-zero. There
is no "skip and stay green" path: a step that cannot run is recorded as failed
with its reason.

Run:
    python artifacts/harnesses/ux-eval.py
    python artifacts/harnesses/ux-eval.py --book-title "Fundamentals of Data Engineering"

Plot of the flow (real mermaid, per repo rules):

```mermaid
flowchart LR
  L[library opens] --> B[open a volume]
  B --> Q[type + Enter]
  Q --> A[answer appears]
  A --> J[chip jumps + marks quote]
  J --> R[return pill restores scroll]
  A --> X[out-of-book refusal]
  B --> S[switch volume isolates notes]
```
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "artifacts" / "runs"
DEFAULT_SESSION = "eval-ux-worker"
DEFAULT_UI = "http://localhost:3100"
REFUSAL = "Not in this book."
SCHEMA = "ux-eval/1"


# ---------------------------------------------------------------------------
# CLI plumbing (pure functions so the harness tests can exercise them)
# ---------------------------------------------------------------------------


class HarnessError(RuntimeError):
    """A command the harness needed did not work."""

    kind = "error"


class ToolUnavailable(HarnessError):
    """The browser binary (or a session) is not usable at all."""

    kind = "unavailable"


class CheckFailed(HarnessError):
    """The browser worked; the reader-visible outcome was not what we require."""

    kind = "check"


def parse_cli_json(stdout: str) -> dict:
    """Return the JSON object printed by agent-browser.

    agent-browser prints one JSON object per command, but noisy launchers can
    prepend a warning. The whole payload wins; otherwise the last parseable
    line is used. Anything else is an error, never an empty success.
    """
    text = (stdout or "").strip()
    if not text:
        raise HarnessError("agent-browser printed no output")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return payload
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    raise HarnessError(f"agent-browser output was not JSON: {text[:200]!r}")


def browser_command(
    executable: str, session: str, *args: str, json_output: bool = True
) -> list[str]:
    """Build an argv that always isolates the browser session.

    Windows resolves the CLI to ``agent-browser.CMD``; ``cmd.exe /c`` is needed
    because CreateProcess cannot launch a batch file directly.
    """
    argv = [executable, "--session", session, *args]
    if json_output:
        argv.append("--json")
    if executable.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", *argv]
    return argv


def parse_passage_count(text: str) -> int | None:
    """Read ``1,042 passages`` from a library card's metadata line."""
    match = re.search(r"([\d,]+)\s+passages?\b", text or "", re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def refusal_is_clean(answer_text: str, error_text: str | None) -> bool:
    """The refusal is exactly the sentence, rendered as an answer, not an error."""
    if error_text:
        return False
    return (answer_text or "").strip() == REFUSAL


QUOTE_EDGES = "\"'“”‘’"


def normalize_quote_text(text: str) -> str:
    """Compare the marked passage with the source quote despite presentation.

    The card wraps its quote in curly quotes and the DOM may break the marked
    run across lines; both sides are stripped of surrounding quote marks and
    collapsed to single spaces before comparison. Nothing else is normalised.
    """
    stripped = (text or "").strip().strip(QUOTE_EDGES).strip()
    return " ".join(stripped.split())


def quote_is_marked(marked_text: str, quote_text: str | None) -> bool:
    """The passage marks the exact quote the citation offered.

    Without a quote (a bare citation chip) any non-empty marked run is the
    most that can be checked; with one, the two must be the same text.
    """
    marked = normalize_quote_text(marked_text)
    if not marked:
        return False
    if quote_text is None:
        return True
    return marked == normalize_quote_text(quote_text)


# ---------------------------------------------------------------------------
# Browser driver
# ---------------------------------------------------------------------------


def find_browser() -> str:
    found = shutil.which("agent-browser")
    if not found:
        raise ToolUnavailable(
            "agent-browser is not on PATH; install it or pass --agent-browser"
        )
    return found


def _kill_tree(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        proc.kill()


def run_command(argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Run a CLI with file-backed output.

    agent-browser sometimes leaves a daemon attached to the inherited pipe: a
    plain ``subprocess.run(capture_output=True)`` then waits for EOF forever
    even after the command itself finished (measured 2026-10-29: a 25 s
    command hung a 330 s run). Output goes to files, so only the direct child's
    exit is awaited.
    """
    import tempfile

    tmp = tempfile.mkdtemp(prefix="ux-eval-")
    out_path = Path(tmp) / "stdout.txt"
    err_path = Path(tmp) / "stderr.txt"
    try:
        with open(out_path, "wb") as out, open(err_path, "wb") as err:
            proc = subprocess.Popen(
                argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err
            )
            timed_out = False
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_tree(proc)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        stdout = out_path.read_text(encoding="utf-8", errors="replace")
        stderr = err_path.read_text(encoding="utf-8", errors="replace")
    finally:
        # A detached agent-browser daemon can still hold these files open on
        # Windows; cleanup is best-effort and must never fail the command.
        shutil.rmtree(tmp, ignore_errors=True)
    if timed_out:
        raise subprocess.TimeoutExpired(
            cmd=argv, timeout=timeout, output=stdout, stderr=stderr
        )
    return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)


class Browser:
    """Thin, bounded wrapper over the agent-browser CLI."""

    def __init__(
        self,
        session: str = DEFAULT_SESSION,
        executable: str | None = None,
        command_timeout: float = 30.0,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
    ) -> None:
        self.session = session
        self.executable = executable or find_browser()
        self.command_timeout = command_timeout
        self.runner = runner or run_command

    # -- primitives ---------------------------------------------------------

    def _run(
        self,
        args: Iterable[str],
        timeout: float | None = None,
        json_output: bool = True,
    ) -> str:
        argv = browser_command(
            self.executable, self.session, *args, json_output=json_output
        )
        limit = self.command_timeout if timeout is None else timeout
        try:
            proc = self.runner(argv, timeout=limit)
        except subprocess.TimeoutExpired as exc:
            raise HarnessError(
                f"timeout after {limit:g}s: {' '.join(args)[:160]}"
            ) from exc
        except OSError as exc:
            raise ToolUnavailable(f"could not run agent-browser: {exc}") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:400]
            raise HarnessError(
                f"agent-browser exited {proc.returncode} for "
                f"{' '.join(args)[:120]}: {detail}"
            )
        return proc.stdout

    def cmd(self, *args: str, timeout: float | None = None) -> dict:
        payload = parse_cli_json(self._run(args, timeout=timeout))
        if payload.get("success") is False:
            raise HarnessError(
                f"agent-browser {args[0]} failed: {payload.get('error')}"
            )
        return payload

    def eval(self, js: str, timeout: float | None = None) -> Any:
        # agent-browser 0.22.2 runs through cmd.exe on Windows, which truncates
        # a multi-line argument at the first newline ("SyntaxError: Unexpected
        # end of input", measured). Harness JS has no meaningful newlines, so
        # it travels as one line.
        js = " ".join(js.split())
        payload = self.cmd("eval", js, timeout=timeout)
        data = payload.get("data") or {}
        if "result" not in data:
            raise HarnessError(f"eval returned no result: {payload}")
        return data["result"]

    def snapshot_text(self, timeout: float | None = None) -> str:
        return self._run(
            ["snapshot", "-i", "-c"], timeout=timeout, json_output=False
        )

    def screenshot(self, path: Path, timeout: float | None = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.cmd("screenshot", str(path), timeout=timeout)
        if not path.is_file() or path.stat().st_size == 0:
            raise HarnessError(f"screenshot was not written: {path}")
        return path

    def page_errors(self) -> list[str]:
        payload = self.cmd("errors")
        data = payload.get("data") or {}
        errors = data.get("errors")
        if isinstance(errors, list):
            return [str(item) for item in errors]
        if isinstance(data, list):
            return [str(item) for item in data]
        return []

    # -- waiting ------------------------------------------------------------

    def wait_for(
        self,
        js: str,
        predicate: Callable[[Any], bool],
        description: str,
        timeout: float,
        poll: float = 0.4,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> Any:
        deadline = clock() + timeout
        last: Any = None
        last_error: str | None = None
        while True:
            try:
                last = self.eval(js)
                last_error = None
                if predicate(last):
                    return last
            except HarnessError as exc:  # transient dev-server hiccups are retried
                last_error = str(exc)
            if clock() >= deadline:
                detail = last_error or json.dumps(last, default=str)[:500]
                raise CheckFailed(
                    f"timed out after {timeout:g}s waiting for {description}; "
                    f"last state: {detail}"
                )
            sleep(poll)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class Check:
    name: str
    ok: bool
    expected: str
    actual: Any

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "ok": self.ok,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass
class Step:
    name: str
    description: str
    depends_on: str | None = None
    checks: list[Check] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    error: str | None = None
    status: str = "running"  # running | passed | failed | blocked
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "passed"

    def require(self, name: str, ok: bool, expected: Any, actual: Any) -> None:
        self.checks.append(Check(name, bool(ok), str(expected), actual))
        if not ok:
            raise CheckFailed(
                f"{name}: expected {expected}, got {json.dumps(actual, default=str)[:300]}"
            )

    def note(self, name: str, expected: Any, actual: Any) -> None:
        """Record an observation that is reported but does not gate the step."""
        self.checks.append(Check(name, True, str(expected), actual))

    def add_evidence(self, key: str, value: Any) -> None:
        self.evidence[key] = value

    def fail(self, message: str) -> None:
        self.error = message
        self.status = "failed"

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "ok": self.ok,
            "depends_on": self.depends_on,
            "duration_s": round(self.duration_s, 3),
            "checks": [c.as_dict() for c in self.checks],
            "evidence": self.evidence,
            "error": self.error,
        }


@dataclass
class RunResult:
    meta: dict
    steps: list[Step] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def exit_code(self) -> int:
        if self.error:
            return 2
        return 0 if all(step.ok for step in self.steps) else 1

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def as_dict(self) -> dict:
        failures = [
            {"step": s.name, "status": s.status, "error": s.error}
            for s in self.steps
            if not s.ok
        ]
        return {
            "schema": SCHEMA,
            **self.meta,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "failures": failures,
            "steps": [s.as_dict() for s in self.steps],
            "diagnostics": self.diagnostics,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Selectors / page probes (kept next to the UI source they mirror)
# ---------------------------------------------------------------------------

# web/components/LibraryView.tsx: .nk-book, .nk-book-title, .nk-book-meta
LIBRARY_STATE = """(() => {
  const visible = (el) => !!(el && (el.offsetWidth || el.offsetHeight));
  const books = [...document.querySelectorAll('.nk-book')].filter(visible);
  return {
    ready: books.length > 0,
    books: books.length,
    titles: books.map(b => (b.querySelector('.nk-book-title')?.innerText || '').trim()),
    metas: books.map(b => (b.querySelector('.nk-book-meta')?.innerText || '').trim()),
    alert: (document.querySelector('.nk-alert')?.innerText || '').trim() || null
  };
})()"""

MARK_BOOK = """(() => {
  const visible = (el) => !!(el && (el.offsetWidth || el.offsetHeight));
  const books = [...document.querySelectorAll('.nk-book')].filter(visible);
  if (!books.length) return {marked: false, reason: 'no-books'};
  const index = Math.min(%d, books.length - 1);
  books.forEach(b => b.removeAttribute('data-ux-target'));
  books[index].setAttribute('data-ux-target', 'book');
  return {
    marked: true,
    index,
    label: books[index].getAttribute('aria-label') || '',
    title: (books[index].querySelector('.nk-book-title')?.innerText || '').trim(),
    meta: (books[index].querySelector('.nk-book-meta')?.innerText || '').trim()
  };
})()"""

# The eval session keeps its own browser profile; resetting its notes and
# reading progress makes the run repeatable without touching the owner's
# normal browser session (web/lib/store.ts persists nekohon-state-<book>).
CLEAN_SLATE = """(() => {
  const removed = [];
  for (const key of Object.keys(localStorage)) {
    if (key.startsWith('nekohon-state-') || key === 'nekohon-progress' ||
        key === 'atb-highlights') {
      localStorage.removeItem(key);
      removed.push(key);
    }
  }
  return {removed};
})()"""

# web/components/Reader.tsx: .book-title, [data-chunk-id], .chunk-heading,
# .nekohon-library (kept mounted but not visible), .composer-input
READER_STATE = """(() => {
  const visible = (el) => !!(el && (el.offsetWidth || el.offsetHeight));
  const library = document.querySelector('.nekohon-library');
  return {
    ready: !!document.querySelector('.rg-prose') &&
      document.querySelectorAll('[data-chunk-id]').length > 0,
    title: (document.querySelector('.book-title')?.innerText || '').trim(),
    chunks: document.querySelectorAll('[data-chunk-id]').length,
    headings: [...document.querySelectorAll('.chunk-heading')]
      .slice(0, 3).map(e => e.innerText.trim()),
    libraryVisible: visible(library),
    composer: !!document.querySelector('.composer-input'),
    cards: document.querySelectorAll('.gloss-card').length
  };
})()"""

# web/components/MarginCard.tsx + AnswerView.tsx: .gloss-card, .turn-question,
# .turn-body .answer, .chip, .chip-miss, .turn-error, .shimmer/.stream-cursor
ANSWER_STATE = """(() => {
  const cards = [...document.querySelectorAll('.gloss-card')];
  const card = cards[cards.length - 1] || null;
  if (!card) return {ready: false, reason: 'no-card', cards: 0};
  const busy = !!card.querySelector('.shimmer, .stream-cursor, .turn-busy');
  const error = (card.querySelector('.turn-error')?.innerText || '').trim() || null;
  const answers = [...card.querySelectorAll('.turn-body .answer')]
    .map(e => e.innerText.trim()).filter(Boolean);
  const question = (card.querySelector('.turn-question')?.innerText || '').trim();
  const chips = [...card.querySelectorAll('.chip')].map(e => ({
    label: e.innerText.trim(),
    miss: e.classList.contains('chip-miss')
  }));
  const sourcePills = [...card.querySelectorAll('.source-pill')]
    .map(e => e.innerText.trim());
  return {
    ready: !busy && (answers.length > 0 || !!error),
    cards: cards.length,
    busy,
    error,
    answers,
    question,
    chips,
    sourcePills,
    marks: document.querySelectorAll('mark.cite-mark').length,
    text: card.innerText.slice(0, 900)
  };
})()"""

MARK_CHIP = """(() => {
  const cards = [...document.querySelectorAll('.gloss-card')];
  const card = cards[cards.length - 1];
  if (!card) return {marked: false, reason: 'no-card'};
  card.querySelectorAll('[data-ux-target]').forEach(e => e.removeAttribute('data-ux-target'));
  const chip = card.querySelector('.chip');
  if (chip) {
    chip.setAttribute('data-ux-target', 'cite-jump');
    return {
      marked: true, kind: 'chip', expanded: true,
      label: chip.innerText.trim(),
      miss: chip.classList.contains('chip-miss'),
      scrollY: window.scrollY
    };
  }
  const pill = card.querySelector('.source-pill');
  if (!pill) return {marked: false, reason: 'no-citation-control'};
  const open = card.querySelector('.source-popover-wrapper.is-open');
  if (!open) {
    pill.setAttribute('data-ux-target', 'cite-open');
    return {
      marked: true, kind: 'source-pill', expanded: false,
      label: pill.innerText.trim(), miss: false, scrollY: window.scrollY
    };
  }
  const jump = card.querySelector('.source-jump-btn');
  if (!jump) return {marked: false, reason: 'no-jump-control'};
  jump.setAttribute('data-ux-target', 'cite-jump');
  return {
    marked: true, kind: 'jump', expanded: true,
    label: jump.innerText.trim(), miss: false, scrollY: window.scrollY
  };
})()"""

SOURCE_OPEN = """(() => {
  const cards = [...document.querySelectorAll('.gloss-card')];
  const card = cards[cards.length - 1];
  if (!card) return {open: false, jump: false};
  return {
    open: !!card.querySelector('.source-popover-wrapper.is-open'),
    jump: !!card.querySelector('.source-jump-btn')
  };
})()"""

SOURCE_QUOTE = """(() => (document.querySelector('.source-popover-text')?.textContent || '').trim())()"""

SWITCH_VISIBLE = """(() => {
  const button = document.querySelector("button[aria-label='Switch book']");
  if (!button) return {present: false, visible: false, scrollY: window.scrollY};
  const rect = button.getBoundingClientRect();
  return {
    present: true,
    visible: rect.width > 0 && rect.bottom > 0 && rect.top < window.innerHeight,
    scrollY: window.scrollY
  };
})()"""

JUMP_STATE = """(() => {
  const mark = document.querySelector('mark.cite-mark');
  const r = mark ? mark.getBoundingClientRect() : null;
  const view = window.innerHeight;
  return {
    scrollY: window.scrollY,
    marks: document.querySelectorAll('mark.cite-mark').length,
    /* textContent, not innerText: a mark inside a content-visibility chunk
       reports an empty innerText until its block is painted. */
    markText: (mark?.textContent || '').slice(0, 2000),
    markTop: r ? Math.round(r.top) : null,
    markBottom: r ? Math.round(r.bottom) : null,
    markVisible: !!r && (r.height >= view ? r.top >= 0 : r.top >= 0 && r.bottom <= view),
    banner: !!document.querySelector('.return-spot-banner'),
    pill: (document.querySelector('.return-spot-pill')?.innerText || '').trim()
  };
})()"""

ACTIVE_BOOK_META = """(() => {
  const item = document.querySelector('.topbar-book-item.is-active');
  if (!item) return {meta: null, title: null};
  return {
    title: (item.querySelector('.topbar-book-item-title')?.innerText || '').trim(),
    meta: (item.querySelector('.topbar-book-item-meta')?.innerText || '').trim()
  };
})()"""

MARK_SWITCH = """(() => {
  const items = [...document.querySelectorAll('.topbar-book-item')];
  if (items.length < 2) return {marked: false, count: items.length};
  items.forEach(i => i.removeAttribute('data-ux-target'));
  items[1].setAttribute('data-ux-target', 'switch-book');
  return {
    marked: true,
    count: items.length,
    target: (items[1].querySelector('.topbar-book-item-title')?.innerText || '').trim()
  };
})()"""


# ---------------------------------------------------------------------------
# The smoke run
# ---------------------------------------------------------------------------


@dataclass
class Config:
    ui: str = DEFAULT_UI
    session: str = DEFAULT_SESSION
    book_index: int = 0
    book_title: str | None = None
    query: str = "What is a watermark?"
    refusal_query: str = "What is the capital of France?"
    answer_timeout: float = 90.0
    step_timeout: float = 25.0
    budget_s: float = 240.0
    out: Path = DEFAULT_OUT
    agent_browser: str | None = None
    keep_open: bool = False
    viewport: tuple[int, int] = (1440, 900)


class UxSmoke:
    def __init__(self, cfg: Config, browser: Browser) -> None:
        self.cfg = cfg
        self.browser = browser
        self.started = time.monotonic()
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        self.stamp = stamp
        self.run_dir = cfg.out / f"ux-eval-{stamp}"
        self.json_path = cfg.out / f"ux-eval-{stamp}.json"
        self.result = RunResult(
            meta={
                "started": datetime.now(timezone.utc).isoformat(),
                "finished": None,
                "duration_s": None,
                "session": cfg.session,
                "target": {"ui": cfg.ui, "engine": "http://localhost:8000"},
                "config": {
                    "book_index": cfg.book_index,
                    "book_title": cfg.book_title,
                    "query": cfg.query,
                    "refusal_query": cfg.refusal_query,
                    "answer_timeout_s": cfg.answer_timeout,
                    "budget_s": cfg.budget_s,
                    "viewport": list(cfg.viewport),
                },
                "invocation": [sys.executable, *sys.argv],
                "paths": {
                    "run_dir": self._rel(self.run_dir),
                    "result": self._rel(self.json_path),
                },
            }
        )
        self.shot_index = 0
        self.pre_jump_scroll: float | None = None
        self.last_answer = ""
        self.last_question = ""

    # -- helpers ------------------------------------------------------------

    def _rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            return path.as_posix()

    def _remaining(self) -> float:
        return self.cfg.budget_s - (time.monotonic() - self.started)

    def _shot(self, step: Step, label: str) -> Path | None:
        self.shot_index += 1
        path = self.run_dir / f"{self.shot_index:02d}-{label}.png"
        try:
            self.browser.screenshot(path)
        except HarnessError as exc:
            step.add_evidence("screenshot_error", str(exc))
            return None
        step.add_evidence("screenshot", self._rel(path))
        return path

    def _snapshot(self, step: Step, label: str) -> None:
        path = self.run_dir / f"{self.shot_index:02d}-{label}.snapshot.txt"
        try:
            text = self.browser.snapshot_text()
        except HarnessError as exc:
            step.add_evidence("snapshot_error", str(exc))
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        step.add_evidence("snapshot", self._rel(path))

    def _submit(self, step: Step, question: str) -> dict:
        """Click the composer, type with real key events, submit with Enter."""
        self.browser.cmd("click", ".composer-input", timeout=self.cfg.step_timeout)
        self.browser.cmd("type", ".composer-input", question, timeout=self.cfg.step_timeout)
        typed = self.browser.cmd("get", "value", ".composer-input").get("data", {}).get("value")
        step.require("composer accepts typed text", typed == question, question, typed)
        self.browser.cmd("press", "Enter", timeout=self.cfg.step_timeout)
        return self.browser.wait_for(
            ANSWER_STATE,
            lambda s: bool(s.get("ready")) and question[:40].lower() in (s.get("question") or "").lower(),
            f"an answer for {question!r}",
            timeout=min(self.cfg.answer_timeout, max(5.0, self._remaining())),
        )

    def _settle_layout(self, js: str, timeout: float = 8.0, stable_s: float = 1.0) -> dict:
        """Wait until both the scroll offset and the marked run come to rest.

        The citation jump is a 520 ms eased scroll followed by one late-paint
        correction. Chunk blocks under ``content-visibility: auto`` keep
        settling their heights afterwards, so the mark can drift while the
        scroll offset is already constant (measured: scrollY steady at 273,805
        with the mark moving). Rest means neither moved for one second.
        """
        time.sleep(0.9)
        previous = self.browser.eval(js)
        deadline = time.monotonic() + timeout
        last_change = time.monotonic()
        while time.monotonic() < deadline:
            current = self.browser.eval(js)
            moved = abs(float(current.get("scrollY") or 0)
                        - float(previous.get("scrollY") or 0)) > 2
            drifted = abs(float(current.get("markTop") or 0)
                          - float(previous.get("markTop") or 0)) > 2
            if moved or drifted:
                last_change = time.monotonic()
            elif time.monotonic() - last_change >= stable_s:
                return current
            previous = current
            time.sleep(0.4)
        return previous

    # -- steps --------------------------------------------------------------

    def step_library(self, step: Step) -> None:
        self.browser.cmd("set", "viewport", *map(str, self.cfg.viewport), timeout=self.cfg.step_timeout)
        opened = self.browser.cmd("open", self.cfg.ui, timeout=self.cfg.step_timeout)
        state = self.browser.wait_for(
            LIBRARY_STATE, lambda s: bool(s.get("ready")), "the library shelf",
            timeout=min(self.cfg.step_timeout, max(5.0, self._remaining())),
        )
        step.require("library reached", bool(opened.get("data", {}).get("url")), self.cfg.ui,
                     opened.get("data", {}).get("url"))
        step.require("volumes are listed", state["books"] >= 2, ">= 2", state["books"])
        step.require("no disconnected-engine alert", state["alert"] is None, None, state["alert"])
        step.add_evidence("titles", state["titles"])
        step.add_evidence("metas", state["metas"])
        self._shot(step, "library")
        self._snapshot(step, "library")

    def step_clean(self, step: Step) -> None:
        cleared = self.browser.eval(CLEAN_SLATE)
        step.add_evidence("cleared_keys", cleared.get("removed", []))
        self.browser.cmd("reload", timeout=self.cfg.step_timeout)
        state = self.browser.wait_for(
            LIBRARY_STATE, lambda s: bool(s.get("ready")), "the library after a clean slate",
            timeout=min(self.cfg.step_timeout, max(5.0, self._remaining())),
        )
        step.require("library returns after reload", state["books"] >= 2, ">= 2", state["books"])

    def step_open_book(self, step: Step) -> None:
        marked = self.browser.eval(MARK_BOOK % self.cfg.book_index)
        step.require("a volume can be targeted", bool(marked.get("marked")), True, marked)
        if self.cfg.book_title:
            step.require(
                "requested volume is present",
                marked.get("title") == self.cfg.book_title,
                self.cfg.book_title,
                marked.get("title"),
            )
        expected_chunks = parse_passage_count(marked.get("meta", ""))
        step.note("library card names its extent", "chapters counts as shown", marked.get("meta"))
        self.browser.cmd("click", "[data-ux-target='book']", timeout=self.cfg.step_timeout)
        state = self.browser.wait_for(
            READER_STATE,
            lambda s: bool(s.get("ready")) and s.get("title") == marked.get("title"),
            f"the reader for {marked.get('title')!r}",
            timeout=min(self.cfg.step_timeout, max(5.0, self._remaining())),
        )
        step.require("reader shows the volume", state["title"] == marked.get("title"),
                     marked.get("title"), state["title"])
        step.require("library yields to the reader", state["libraryVisible"] is False, False,
                     state["libraryVisible"])
        step.require("chunks rendered", state["chunks"] > 0, "> 0", state["chunks"])
        step.require("composer is present", state["composer"] is True, True, state["composer"])
        step.require("reader starts with no notes", state["cards"] == 0, 0, state["cards"])

        # The switcher states each volume's passage count; the reader should
        # render exactly that many passages.
        self.browser.cmd("click", "button[aria-label='Switch book']", timeout=self.cfg.step_timeout)
        meta = self.browser.wait_for(
            ACTIVE_BOOK_META, lambda s: bool(s.get("meta")), "the active volume's passage count",
            timeout=min(self.cfg.step_timeout, max(5.0, self._remaining())),
        )
        self.browser.cmd("click", "button[aria-label='Switch book']", timeout=self.cfg.step_timeout)
        self.browser.wait_for(
            "(() => ({open: !!document.querySelector('.topbar-book-menu')}))()",
            lambda s: s.get("open") is False, "the volume menu to close",
            timeout=min(self.cfg.step_timeout, max(5.0, self._remaining())),
        )
        expected = parse_passage_count(meta.get("meta", ""))
        step.require("switcher states a passage count", expected is not None, "N passages",
                     meta.get("meta"))
        step.require("chunks match the switcher's count", state["chunks"] == expected,
                     expected, state["chunks"])
        step.add_evidence("book", marked.get("title"))
        step.add_evidence("chunk_count", state["chunks"])
        step.add_evidence("headings", state["headings"])
        self._shot(step, "book-open")
        self._snapshot(step, "book-open")

    def step_submit(self, step: Step) -> None:
        state = self._submit(step, self.cfg.query)
        self.last_question = state.get("question", "")
        step.require("answer finished streaming", state["busy"] is False, False, state["busy"])
        step.require("no error state", state["error"] is None, None, state["error"])
        step.require("question is the one asked", self.cfg.query.lower() in state["question"].lower(),
                     self.cfg.query, state["question"])
        step.add_evidence("question", state["question"])
        step.add_evidence("text", state["text"])
        self._shot(step, "answer")

    def step_answer(self, step: Step) -> None:
        state = self.browser.eval(ANSWER_STATE)
        step.require("an answer is on screen", bool(state.get("answers")), ">= 1 answer",
                     state.get("answers"))
        answer = (state.get("answers") or [""])[0]
        self.last_answer = answer
        step.require("answer is not a refusal", answer.strip() != REFUSAL,
                     f"not {REFUSAL!r}", answer[:200])
        citations = (state.get("chips") or []) + (state.get("sourcePills") or [])
        step.require("citations are offered", len(citations) >= 1, ">= 1 citation control",
                     citations)
        step.add_evidence("answer", answer)
        step.add_evidence("chips", state.get("chips"))
        step.add_evidence("source_pills", state.get("sourcePills"))
        self._snapshot(step, "answer")

    def step_citation_jump(self, step: Step) -> None:
        before = self.browser.eval(JUMP_STATE)
        self.pre_jump_scroll = float(before.get("scrollY") or 0)
        marked = self.browser.eval(MARK_CHIP)
        step.require("a citation control exists", bool(marked.get("marked")), True, marked)
        step.require("control is a real citation, not a miss", marked.get("miss") is False, False,
                     marked.get("miss"))
        quote_text: str | None = None
        if not marked.get("expanded"):
            self.browser.cmd("click", "[data-ux-target='cite-open']", timeout=self.cfg.step_timeout)
            self.browser.wait_for(
                SOURCE_OPEN, lambda s: s.get("open") and s.get("jump"),
                "the source quote and its jump control",
                timeout=min(self.cfg.step_timeout, max(5.0, self._remaining())),
            )
            marked = self.browser.eval(MARK_CHIP)
            step.require("jump control is reachable", marked.get("kind") == "jump", "jump", marked)
            quote_text = self.browser.eval(SOURCE_QUOTE)
            step.require("the card offers its exact quote", bool(normalize_quote_text(quote_text or "")),
                         "a non-empty source quote", (quote_text or "")[:200])
        target = "[data-ux-target='cite-jump']"
        clicked_at = time.monotonic()
        self.browser.cmd("click", target, timeout=self.cfg.step_timeout)
        self.browser.wait_for(
            JUMP_STATE,
            lambda s: s.get("marks", 0) >= 1 and bool(s.get("banner"))
            and bool(normalize_quote_text(s.get("markText"))),
            "the citation jump, highlight, and return pill",
            timeout=min(self.cfg.step_timeout, max(5.0, self._remaining())),
        )
        after = self._settle_layout(JUMP_STATE)
        rest_after = time.monotonic() - clicked_at
        step.require("book pane moved", abs(after["scrollY"] - before["scrollY"]) > 100,
                     "> 100px", after["scrollY"] - before["scrollY"])
        step.require(
            "the cited passage is on screen",
            after.get("markVisible") is True,
            "the whole mark inside the viewport",
            {"top": after.get("markTop"), "bottom": after.get("markBottom"),
             "scrollY": after.get("scrollY")},
        )
        step.require(
            "exact quote is marked",
            quote_is_marked(after.get("markText", ""), quote_text),
            "the quote the card offered",
            {"marked": normalize_quote_text(after.get("markText", ""))[:200],
             "offered": normalize_quote_text(quote_text or "")[:200]},
        )
        step.require("return control appears", bool(after["pill"]), True, after["pill"])
        step.add_evidence("citation_control", marked.get("label"))
        step.add_evidence("source_quote", normalize_quote_text(quote_text or ""))
        step.add_evidence("marked_quote", normalize_quote_text(after.get("markText", "")))
        step.add_evidence("scroll_before", before.get("scrollY"))
        step.add_evidence("scroll_after", after.get("scrollY"))
        step.add_evidence("rest_after_s", round(rest_after, 2))
        step.add_evidence("mark_position", {"top": after.get("markTop"),
                                            "bottom": after.get("markBottom")})
        self._shot(step, "citation-jump")

    def step_citation_return(self, step: Step) -> None:
        before = self.browser.eval(JUMP_STATE)
        step.require("a return control is offered",
                     bool(before.get("banner")) and bool(before.get("pill")),
                     "the return pill", {"banner": before.get("banner"),
                                         "pill": before.get("pill")})
        origin = self.pre_jump_scroll if self.pre_jump_scroll is not None else 0.0
        self.browser.cmd("click", ".return-spot-pill", timeout=self.cfg.step_timeout)
        after = self.browser.wait_for(
            JUMP_STATE,
            lambda s: not s.get("banner") and abs(s.get("scrollY", 0) - origin) <= 60,
            "the return to the reading position",
            timeout=min(self.cfg.step_timeout, max(5.0, self._remaining())),
        )
        step.require("return pill disappears", after["banner"] is False, False, after["banner"])
        step.require("scroll is restored", abs(after["scrollY"] - origin) <= 60,
                     f"within 60px of {origin:g}", after["scrollY"])
        step.add_evidence("scroll_before_return", before.get("scrollY"))
        step.add_evidence("scroll_after_return", after["scrollY"])
        self._shot(step, "citation-return")

    def step_refusal(self, step: Step) -> None:
        state = self._submit(step, self.cfg.refusal_query)
        answers = state.get("answers") or []
        refusal_text = answers[0] if answers else ""
        step.require("refusal is the exact sentence", refusal_text.strip() == REFUSAL,
                     REFUSAL, [a[:120] for a in answers])
        step.require("refusal is clean", refusal_is_clean(refusal_text, state.get("error")),
                     "exact sentence, no error", {"answer": refusal_text, "error": state.get("error")})
        step.require("refusal turn is not busy", state.get("busy") is False, False, state.get("busy"))
        step.note("nearest misses are labelled", "if any citations",
                  "nearest misses:" in (state.get("text") or ""))
        step.note("nearby figures are labelled", "if any figures",
                  "nearby, not an answer" in (state.get("text") or ""))
        step.add_evidence("answer", refusal_text)
        step.add_evidence("text", state.get("text"))
        self._shot(step, "refusal")

    def step_book_switch(self, step: Step) -> None:
        before = self.browser.eval(READER_STATE)
        # The top bar tucks away while reading and reveals on an upward scroll;
        # a reader who wants another volume scrolls back up first.
        scrolled_from = self.browser.eval(JUMP_STATE).get("scrollY")
        self.browser.eval("(() => { window.scrollTo(0, 0); return window.scrollY; })()")
        switcher = self.browser.wait_for(
            SWITCH_VISIBLE,
            lambda s: s.get("present") and s.get("visible"),
            "the volume switcher after scrolling back to the top",
            timeout=min(self.cfg.step_timeout, max(5.0, self._remaining())),
        )
        step.require("volume switcher is reachable", switcher.get("visible") is True, True, switcher)
        step.add_evidence("scrolled_from", scrolled_from)
        self.browser.cmd("click", "button[aria-label='Switch book']", timeout=self.cfg.step_timeout)
        marked = self.browser.wait_for(
            MARK_SWITCH, lambda s: bool(s.get("marked")), "the volume menu",
            timeout=min(self.cfg.step_timeout, max(5.0, self._remaining())),
        )
        step.require("a second volume is offered", bool(marked.get("marked")), True, marked)
        self.browser.cmd("click", "[data-ux-target='switch-book']", timeout=self.cfg.step_timeout)
        after = self.browser.wait_for(
            READER_STATE,
            lambda s: bool(s.get("ready")) and s.get("title") != before.get("title") and s.get("cards") == 0,
            f"the switch to {marked.get('target')!r} with a clean margin",
            timeout=min(self.cfg.step_timeout, max(5.0, self._remaining())),
        )
        step.require("volume changed", after["title"] != before["title"], f"!= {before.get('title')!r}",
                     after["title"])
        step.require("new chunks rendered", after["chunks"] > 0, "> 0", after["chunks"])
        step.require("old notes are gone", after["cards"] == 0, 0, after["cards"])
        probe = self.last_answer[:60] or self.last_question or "What is a watermark?"
        stale = self.browser.eval(
            "(() => ({oldAnswerVisible: document.body.innerText.includes(%s)}))()"
            % json.dumps(probe)
        )
        step.require("old answer text is not in the pane", stale.get("oldAnswerVisible") is False,
                     False, stale.get("oldAnswerVisible"))
        step.add_evidence("from", before.get("title"))
        step.add_evidence("to", after.get("title"))
        step.add_evidence("chunk_count", after["chunks"])
        self._shot(step, "book-switch")
        self._snapshot(step, "book-switch")

    # -- runner -------------------------------------------------------------

    def _run_step(
        self,
        name: str,
        description: str,
        fn: Callable[[Step], None],
        depends_on: str | None = None,
    ) -> Step:
        step = Step(name=name, description=description, depends_on=depends_on)
        self.result.steps.append(step)
        prior = {s.name: s for s in self.result.steps}
        if depends_on and not prior[depends_on].ok:
            step.status = "blocked"
            step.error = f"blocked by failed step {depends_on!r}"
            # A blocked step is a failure, never a skip.
            return step
        if self._remaining() <= 2.0:
            step.fail(f"time budget of {self.cfg.budget_s:g}s exhausted before this step")
            return step
        started = time.monotonic()
        try:
            fn(step)
            step.status = "passed"
        except CheckFailed as exc:
            step.fail(str(exc))
        except ToolUnavailable:
            raise
        except HarnessError as exc:
            step.fail(str(exc))
        except Exception as exc:  # noqa: BLE001 - an unexpected crash is a failure, not a skip
            step.fail(f"{type(exc).__name__}: {exc}")
        finally:
            step.duration_s = time.monotonic() - started
            if step.status == "failed":
                self._shot(step, f"{name}-failed")
        return step

    def run(self) -> RunResult:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._run_step("library", "Library opens with the local volumes", self.step_library)
        self._run_step("clean-slate", "Isolated session starts with no saved notes",
                       self.step_clean, depends_on="library")
        self._run_step("open-book", "A volume opens into the reader", self.step_open_book,
                       depends_on="clean-slate")
        self._run_step("submit-question", "Typed question submits with Enter",
                       self.step_submit, depends_on="open-book")
        self._run_step("answer", "An answer with citations appears", self.step_answer,
                       depends_on="submit-question")
        self._run_step("citation-jump", "Citation chip moves the pane and marks the quote",
                       self.step_citation_jump, depends_on="answer")
        self._run_step("citation-return", "Return pill restores the reading position",
                       self.step_citation_return, depends_on="answer")
        self._run_step("refusal", "Out-of-book question refuses cleanly", self.step_refusal,
                       depends_on="open-book")
        self._run_step("book-switch", "Switching volumes isolates notes", self.step_book_switch,
                       depends_on="open-book")

        try:
            errors = self.browser.page_errors()
        except HarnessError as exc:
            errors = []
            self.result.diagnostics["page_errors_error"] = str(exc)
        self.result.diagnostics["page_errors"] = errors

        if not self.cfg.keep_open:
            try:
                self.browser.cmd("close", timeout=self.cfg.step_timeout)
            except HarnessError as exc:
                self.result.diagnostics["close_error"] = str(exc)

        self.finish()
        return self.result

    def finish(self) -> None:
        self.result.meta["finished"] = datetime.now(timezone.utc).isoformat()
        self.result.meta["duration_s"] = round(time.monotonic() - self.started, 2)
        self.result.meta["paths"]["run_dir"] = self._rel(self.run_dir)
        self.result.meta["paths"]["result"] = self._rel(self.json_path)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        payload = self.result.as_dict()
        self.json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (self.run_dir / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_config(args: argparse.Namespace) -> Config:
    return Config(
        ui=args.ui,
        session=args.session,
        book_index=args.book_index,
        book_title=args.book_title,
        query=args.query,
        refusal_query=args.refusal_query,
        answer_timeout=args.answer_timeout,
        step_timeout=args.step_timeout,
        budget_s=args.budget,
        out=Path(args.out) if args.out else DEFAULT_OUT,
        agent_browser=args.agent_browser,
        keep_open=args.keep_open,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live reader UX smoke (agent-browser only)")
    parser.add_argument("--ui", default=DEFAULT_UI)
    parser.add_argument("--session", default=DEFAULT_SESSION)
    parser.add_argument("--book-index", type=int, default=0,
                        help="library card to open (0 = first)")
    parser.add_argument("--book-title", default=None,
                        help="fail if the chosen card is not this title")
    parser.add_argument("--query", default="What is a watermark?")
    parser.add_argument("--refusal-query", default="What is the capital of France?")
    parser.add_argument("--answer-timeout", type=float, default=90.0)
    parser.add_argument("--step-timeout", type=float, default=25.0)
    parser.add_argument("--budget", type=float, default=240.0)
    parser.add_argument("--out", default=None, help="output directory (default artifacts/runs)")
    parser.add_argument("--agent-browser", default=None)
    parser.add_argument("--keep-open", action="store_true",
                        help="leave the isolated session open for inspection")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        reconfigure = getattr(sys.stdout, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    args = parse_args(argv)
    cfg = build_config(args)

    def write_infra_failure(message: str) -> int:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        cfg.out.mkdir(parents=True, exist_ok=True)
        run_dir = cfg.out / f"ux-eval-{stamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": SCHEMA,
            "started": datetime.now(timezone.utc).isoformat(),
            "finished": datetime.now(timezone.utc).isoformat(),
            "duration_s": 0,
            "session": cfg.session,
            "target": {"ui": cfg.ui, "engine": "http://localhost:8000"},
            "ok": False,
            "exit_code": 2,
            "error": message,
            "failures": [{"step": "setup", "status": "failed", "error": message}],
            "steps": [],
            "diagnostics": {},
        }
        path = cfg.out / f"ux-eval-{stamp}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (run_dir / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"UX SMOKE: INCOMPLETE (exit 2) — {message}")
        print(f"result: {path}")
        return 2

    try:
        browser = Browser(
            session=cfg.session,
            executable=cfg.agent_browser,
            command_timeout=max(cfg.step_timeout, 30.0),
        )
    except ToolUnavailable as exc:
        return write_infra_failure(str(exc))

    smoke = UxSmoke(cfg, browser)
    try:
        result = smoke.run()
    except ToolUnavailable as exc:
        return write_infra_failure(str(exc))

    payload = result.as_dict()
    print(f"UX SMOKE: {'PASS' if result.ok else 'FAIL'} (exit {result.exit_code})")
    print(f"session: {cfg.session}   ui: {cfg.ui}")
    print(f"result:  {smoke._rel(smoke.json_path)}")
    print(f"run dir: {smoke._rel(smoke.run_dir)}")
    for step in result.steps:
        mark = "PASS" if step.ok else step.status.upper()
        print(f"  [{mark:6}] {step.name:16} {step.duration_s:6.2f}s  {step.error or ''}")
    if result.diagnostics.get("page_errors"):
        print(f"page errors: {len(result.diagnostics['page_errors'])} recorded (see JSON)")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
