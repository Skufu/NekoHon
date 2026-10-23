"""run-gate.py — one-command per-model gate driver (stable harness).

Automates the manual gate sequence run by hand for the x2c session
(artifacts/reports/x2-trial-2026-10-14.md, "Verdict 2026-10-14"): sealed
fragment suite, pin-pass battery xN runs, exact-refusal canary xN runs,
trial-queries repro, capped loop sweep over the 21 battery questions.

Every family runs as a subprocess (sys.executable), with the child's stdout
inherited so progress streams live; a non-zero exit aborts the gate loudly.
After each probe run the driver copies the probe's canonical output file(s)
to the model-suffixed names below, then restores the canonical file(s) to
their pre-run bytes, so a gate run never changes a pre-existing tracked file —
except the evidence files it writes, which are the point of the run.

Usage:
  python artifacts/harnesses/run-gate.py --model <tag> --label <name> \
      [--fragment-draws 10] [--battery-runs 3] [--refuse-runs 5] \
      [--sweep-draws 5] [--skip fragment,battery,refuse,trial,sweep]
  python artifacts/harnesses/run-gate.py --smoke --model <tag>

Defaults match the x2c gate. --smoke forces minimal draws (fragment 1,
battery 1 run, refuse 1 run, sweep 1) and writes ALL outputs under
artifacts/scratch/gate-smoke/ instead of the evidence dirs.

Outputs (live twin per family; re-running the same label overwrites them):
  evidence/probe-fragment/probe-fragment-2026-10-14.model-<model>.{json,log}
      (written by the probe itself; <model> = model with ':'->'-')
  evidence/probe-small-ask/probe-small-ask-2026-10-13.model-<label>.runK.{json,log}
  evidence/probe-small-refuse/probe-small-refuse-2026-10-13.model-<label>.runK.log
  evidence/probe-trial-queries/probe-trial-queries-2026-10-14.model-<label>.{json,log}
  evidence/probe-llm-loop/probe-llm-loop-2026-10-13.<label>-battery-sweep<N>.log

The loop sweep is a faithful reimplementation of the (gitignored) one-off
data/tmp_battery_sweep.py: the 21 battery questions x N draws, temperature 0,
num_predict=300, counting draws that end with done_reason == "length".
"""

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SELF = Path(__file__).resolve()

EVIDENCE = ROOT / "artifacts" / "runs"
PROBES = ROOT / "archive" / "artifacts" / "probes"
SMOKE_DIR = ROOT / "artifacts" / "scratch" / "gate-smoke"
OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"
OLLAMA_CHAT = "http://127.0.0.1:11434/api/chat"
SWEEP_CAP = 300
SWEEP_TIMEOUT = 900

FAMILIES = ("fragment", "battery", "refuse", "trial", "sweep")


def label_for(model: str) -> str:
    return model.replace(":", "-").replace("/", "-")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


# ---------------------------------------------------------------------------
# Sweep worker (re-executed as a subprocess by the sweep family)
# ---------------------------------------------------------------------------

def run_sweep_worker(model: str, draws: int, log_path: Path) -> None:
    """The loop sweep: battery questions x draws, capped, temperature 0."""
    sys.path.insert(0, str(ROOT))
    import answer as A
    from prompt import SYSTEM
    from retrieve import INDEX, load_index

    spec = importlib.util.spec_from_file_location(
        "step2_battery", ROOT / "artifacts" / "harnesses" / "step2-battery.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load artifacts/harnesses/step2-battery.py")
    battery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(battery)
    questions = [q for q, _ in battery.GOLDEN_PINS]
    questions += [q for q, _, _ in list(battery.TYPOS) + list(battery.PROBES)]
    questions += [q for q, _, _ in battery.COHERENCE]

    index = load_index(INDEX)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with log_path.open("w", encoding="utf-8") as fh:
        def emit(line):
            print(line, flush=True)
            fh.write(line + "\n")
            fh.flush()

        for question in questions:
            context = A.retrieval_context(index, question)
            payload = {
                "model": model, "stream": False, "think": False,
                "options": {"temperature": 0, "num_predict": SWEEP_CAP},
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": A.user_message(
                        context["asked"], context["passages"])},
                ],
            }
            loops = 0
            for _ in range(draws):
                request = urllib.request.Request(
                    OLLAMA_CHAT, data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=SWEEP_TIMEOUT) as response:
                    body = json.loads(response.read().decode("utf-8"))
                loops += body.get("done_reason") == "length"
            total += loops
            emit(f"{loops}/{draws} loops  {question[:60]}")
        emit(f"TOTAL loops: {total} out of {len(questions) * draws} draws "
             f"over {len(questions)} questions, model {model}")


# ---------------------------------------------------------------------------
# Log parsers (compact per-family summaries)
# ---------------------------------------------------------------------------

def parse_ask(log: Path):
    if not log.exists():
        return None
    text = log.read_text(encoding="utf-8")
    match = re.search(r":\s*(\d+)/(\d+) pin-pass", text)
    if not match:
        return None
    fails = re.findall(r"^FAIL \[[^\]]*\]\s+(.+?)\s+pin=", text, re.MULTILINE)
    return {"n": int(match.group(1)), "total": int(match.group(2)), "fails": fails}


def parse_refuse(log: Path):
    if not log.exists():
        return None
    text = log.read_text(encoding="utf-8")
    match = re.search(r":\s*(\d+)/(\d+) exact refusals", text)
    if not match:
        return None
    cases = re.findall(r"^(PASS|FAIL) \[(\w+)\s*\]", text, re.MULTILINE)
    wrong = [name for mark, name in cases if mark == "FAIL"]
    return {"n": int(match.group(1)), "total": int(match.group(2)), "wrong": wrong}


def parse_fragment(log: Path):
    if not log.exists():
        return None
    text = log.read_text(encoding="utf-8")
    if "== summary ==" not in text:
        return None
    block = text.split("== summary ==", 1)[1]
    rows = re.findall(
        r"^(\S+)\s+(\d+)\s+(\d+)\s+(\d+/\d+(?: answ)?)\s+(\d+)\s+(\d+)\s+(.*)$",
        block, re.MULTILINE)
    if not rows:
        return None
    classes = [
        {"cls": cls, "items": int(items), "draws": int(draws), "pass": passes,
         "loops": int(loops), "errors": int(errors)}
        for cls, items, draws, passes, loops, errors, _verdicts in rows
    ]
    return {
        "classes": classes,
        "loops": sum(c["loops"] for c in classes),
        "errors": sum(c["errors"] for c in classes),
    }


def parse_trial(log: Path):
    if not log.exists():
        return None
    text = log.read_text(encoding="utf-8")
    rows = re.findall(
        r"^\[[^\]]+\] '(?P<q>.*)' refused=(?P<refused>True|False) cited=\[.*\]$",
        text, re.MULTILINE)
    if not rows:
        return None
    return [{"q": q, "refused": refused == "True"} for q, refused in rows]


def parse_sweep(log: Path):
    if not log.exists():
        return None
    text = log.read_text(encoding="utf-8")
    match = re.search(
        r"TOTAL loops: (\d+) out of (\d+) draws over (\d+) questions", text)
    if not match:
        return None
    return {"loops": int(match.group(1)), "draws": int(match.group(2)),
            "questions": int(match.group(3))}


# ---------------------------------------------------------------------------
# The driver
# ---------------------------------------------------------------------------

class Gate:
    def __init__(self, args):
        self.model = args.model
        self.label = args.label or label_for(args.model)
        self.smoke = bool(args.smoke)
        self.skip = {part.strip() for part in args.skip.split(",") if part.strip()}
        self.written = []
        self.summary = []
        if self.smoke:
            self.fragment_draws = 1
            self.battery_runs = 1
            self.refuse_runs = 1
            self.sweep_draws = 1
        else:
            self.fragment_draws = args.fragment_draws
            self.battery_runs = args.battery_runs
            self.refuse_runs = args.refuse_runs
            self.sweep_draws = args.sweep_draws

    def out_dir(self, default: Path) -> Path:
        return SMOKE_DIR if self.smoke else default

    # -- plumbing -----------------------------------------------------------

    def fail(self, message):
        print(f"\nGATE FAILED: {message}", file=sys.stderr)
        if self.written:
            print("evidence written before the failure:", file=sys.stderr)
            for path in self.written:
                print(f"  {rel(path)}", file=sys.stderr)
        raise SystemExit(1)

    def preflight(self):
        try:
            with urllib.request.urlopen(OLLAMA_TAGS, timeout=10) as response:
                tags = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            self.fail(f"Ollama not reachable at 127.0.0.1:11434 "
                      f"({type(exc).__name__}: {exc}); start it and re-run")
        names = [m.get("name", "") for m in tags.get("models", [])]
        known = set(names) | {name.split(":", 1)[0] for name in names}
        if self.model not in known:
            self.fail(f"model {self.model!r} not in ollama list: "
                      f"{', '.join(sorted(names))}")

    def spawn(self, cmd):
        printable = " ".join(str(part) for part in cmd)
        print(f"\n$ {printable}", flush=True)
        proc = subprocess.run([str(part) for part in cmd], cwd=str(ROOT),
                              check=False)
        if proc.returncode != 0:
            self.fail(f"command exited {proc.returncode}")

    def place(self, src: Path, dst: Path) -> Path:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        self.written.append(dst)
        return dst

    @staticmethod
    def snapshot(paths):
        return {p: (p.read_bytes() if p.exists() else None) for p in paths}

    @staticmethod
    def restore(snaps):
        for path, data in snaps.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)

    def unparsed(self, family, log):
        self.summary.append(f"{family:<9} log parse failed — see {rel(log)}")

    # -- families -----------------------------------------------------------

    def fragment(self):
        probe = PROBES / "probe-fragment-2026-10-14.py"
        ev_dir = EVIDENCE / "probe-fragment"
        stem = f"probe-fragment-2026-10-14.model-{label_for(self.model)}"
        outs = [ev_dir / f"{stem}.json", ev_dir / f"{stem}.log"]
        if self.smoke:
            snaps = self.snapshot(outs)
            try:
                self.spawn([sys.executable, probe, "--model", self.model,
                            "--draws", str(self.fragment_draws)])
                log = self.place(outs[1], self.out_dir(ev_dir) / outs[1].name)
                self.place(outs[0], self.out_dir(ev_dir) / outs[0].name)
            finally:
                self.restore(snaps)
        else:
            self.spawn([sys.executable, probe, "--model", self.model,
                        "--draws", str(self.fragment_draws)])
            log = outs[1]
            self.written.extend(outs)
        parsed = parse_fragment(log)
        if parsed is None:
            self.unparsed("fragment", log)
            return
        table = ", ".join(f"{c['cls']} {c['pass']}" for c in parsed["classes"])
        self.summary.append(
            f"fragment  {self.fragment_draws} draw(s)/item: {table} "
            f"| loops={parsed['loops']} errors={parsed['errors']}")

    def battery(self):
        probe = PROBES / "probe-small-ask-2026-10-13.py"
        can_dir = EVIDENCE / "probe-small-ask"
        canonical = [can_dir / f"probe-small-ask-2026-10-13{ext}"
                     for ext in (".json", ".log")]
        runs, logs = [], []
        for k in range(1, self.battery_runs + 1):
            stem = f"probe-small-ask-2026-10-13.model-{self.label}.run{k}"
            snaps = self.snapshot(canonical)
            try:
                self.spawn([sys.executable, probe, "--model", self.model])
                log = self.place(canonical[1], self.out_dir(can_dir) / f"{stem}.log")
                self.place(canonical[0], self.out_dir(can_dir) / f"{stem}.json")
            finally:
                self.restore(snaps)
            logs.append(log)
            runs.append(parse_ask(log))
        if all(parsed is None for parsed in runs):
            self.unparsed("battery", logs[-1])
            return
        parts, fails = [], []
        for k, parsed in enumerate(runs, 1):
            if parsed is None:
                parts.append(f"run{k} unparsed")
                continue
            parts.append(f"run{k} {parsed['n']}/{parsed['total']}")
            fails.extend(parsed["fails"])
        unique = list(dict.fromkeys(fails))
        line = f"battery   {len(runs)} run(s): {', '.join(parts)} pin-pass"
        if unique:
            shown = ", ".join(repr(q) for q in unique[:4])
            if len(unique) > 4:
                shown += ", ..."
            line += f" | unique fails ({len(unique)}): {shown}"
        self.summary.append(line)

    def refuse(self):
        probe = PROBES / "probe-small-refuse-2026-10-13.py"
        can_dir = EVIDENCE / "probe-small-refuse"
        canonical = [can_dir / f"probe-small-refuse-2026-10-13{ext}"
                     for ext in (".json", ".log")]
        runs, logs = [], []
        for k in range(1, self.refuse_runs + 1):
            stem = f"probe-small-refuse-2026-10-13.model-{self.label}.run{k}"
            snaps = self.snapshot(canonical)
            try:
                self.spawn([sys.executable, probe, "--model", self.model])
                log = self.place(canonical[1], self.out_dir(can_dir) / f"{stem}.log")
            finally:
                self.restore(snaps)
            logs.append(log)
            runs.append(parse_refuse(log))
        if all(parsed is None for parsed in runs):
            self.unparsed("refuse", logs[-1])
            return
        parts, wrong = [], []
        for k, parsed in enumerate(runs, 1):
            if parsed is None:
                parts.append(f"run{k} unparsed")
                continue
            parts.append(f"run{k} {parsed['n']}/{parsed['total']}")
            wrong.extend(parsed["wrong"])
        line = f"refuse    {', '.join(parts)} exact"
        if wrong:
            line += f" | non-exact: {', '.join(sorted(set(wrong)))}"
        self.summary.append(line)

    def trial(self):
        probe = PROBES / "probe-trial-queries-2026-10-14.py"
        can_dir = EVIDENCE / "probe-trial-queries"
        canonical = [can_dir / f"probe-trial-queries-2026-10-14{ext}"
                     for ext in (".json", ".log")]
        stem = f"probe-trial-queries-2026-10-14.model-{self.label}"
        snaps = self.snapshot(canonical)
        try:
            self.spawn([sys.executable, probe, self.model])
            log = self.place(canonical[1], self.out_dir(can_dir) / f"{stem}.log")
            self.place(canonical[0], self.out_dir(can_dir) / f"{stem}.json")
        finally:
            self.restore(snaps)
        rows = parse_trial(log)
        if rows is None:
            self.unparsed("trial", log)
            return
        refused = [row["q"] for row in rows if row["refused"]]
        line = (f"trial     answered {len(rows) - len(refused)}/{len(rows)}, "
                f"refused {len(refused)}/{len(rows)}")
        if refused:
            line += " | refused: " + ", ".join(repr(q) for q in refused[:6])
        self.summary.append(line)

    def sweep(self):
        ev_dir = EVIDENCE / "probe-llm-loop"
        log = (self.out_dir(ev_dir) /
               f"probe-llm-loop-2026-10-13.{self.label}-battery-sweep"
               f"{self.sweep_draws}.log")
        self.spawn([sys.executable, SELF, "--sweep-worker", "--model", self.model,
                    "--sweep-draws", str(self.sweep_draws),
                    "--sweep-log", str(log)])
        self.written.append(log)
        parsed = parse_sweep(log)
        if parsed is None:
            self.unparsed("sweep", log)
            return
        self.summary.append(
            f"sweep     loops {parsed['loops']}/{parsed['draws']} draws "
            f"({parsed['questions']} questions x {self.sweep_draws})")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="run-gate.py",
        description="Per-model gate driver: fragment suite + battery + "
                    "refusal canary + trial queries + capped loop sweep.")
    parser.add_argument("--model", default="smallbook_x2",
                        help="ollama model tag under test (default: smallbook_x2)")
    parser.add_argument("--label", default=None,
                        help="short label for evidence names "
                             "(default: model with ':'->'-')")
    parser.add_argument("--fragment-draws", type=int, default=10,
                        help="draws per sealed fragment item (default 10; smoke 1)")
    parser.add_argument("--battery-runs", type=int, default=3,
                        help="pin-pass battery runs (default 3; smoke 1)")
    parser.add_argument("--refuse-runs", type=int, default=5,
                        help="exact-refusal canary runs (default 5; smoke 1)")
    parser.add_argument("--sweep-draws", type=int, default=5,
                        help="draws per battery question in the loop sweep "
                             "(default 5; smoke 1)")
    parser.add_argument("--skip", default="",
                        help="comma-separated families to skip: "
                             "fragment,battery,refuse,trial,sweep")
    parser.add_argument("--smoke", action="store_true",
                        help="minimal draws, all outputs under "
                             "artifacts/scratch/gate-smoke/")
    parser.add_argument("--sweep-worker", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--sweep-log", type=Path, default=None,
                        help=argparse.SUPPRESS)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.sweep_worker:
        if args.sweep_log is None:
            parser.error("--sweep-log is required with --sweep-worker")
        run_sweep_worker(args.model, args.sweep_draws, args.sweep_log)
        return

    if args.label and any(ch in args.label for ch in '/\\:*?"<>|'):
        parser.error(f"--label {args.label!r} contains characters "
                     "not allowed in file names")
    for flag, value in (("--fragment-draws", args.fragment_draws),
                        ("--battery-runs", args.battery_runs),
                        ("--refuse-runs", args.refuse_runs),
                        ("--sweep-draws", args.sweep_draws)):
        if value < 1:
            parser.error(f"{flag} must be >= 1")
    unknown = sorted({p.strip() for p in args.skip.split(",") if p.strip()}
                     - set(FAMILIES))
    if unknown:
        parser.error(f"unknown --skip value(s): {', '.join(unknown)} "
                     f"(choose from {', '.join(FAMILIES)})")

    gate = Gate(args)
    gate.preflight()

    print(f"run-gate: model={gate.model} label={gate.label} "
          f"mode={'smoke' if gate.smoke else 'full'}")
    if gate.smoke:
        print("smoke: minimal draws; all outputs under "
              "artifacts/scratch/gate-smoke/")
    active = [name for name in FAMILIES if name not in gate.skip]
    print("families: " + (", ".join(active) if active else "(all skipped)"))
    for name in active:
        getattr(gate, name)()

    print("\n==================== gate summary ====================")
    print(f"model={gate.model}  label={gate.label}  "
          f"mode={'smoke' if gate.smoke else 'full'}")
    for line in gate.summary:
        print(line)
    print(f"outputs ({len(gate.written)}):")
    for path in gate.written:
        print(f"  {rel(path)}")
    print("======================================================")


if __name__ == "__main__":
    main()
