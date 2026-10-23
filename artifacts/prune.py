"""Artifacts pruner — planner, read-only. Artifact, not engine.

Checks the rules in `artifacts/README.md`:

- unindexed: tracked files under artifacts/ not covered by a name or family
  row in the README index (rule 4).
- unreferenced: tracked files no repo doc/code names (candidates only; the
  index row's reason can still keep them).
- over-versioned: families holding more than two run files from different
  dates (rule 3).
- stale: tracked files whose last commit is older than STALE_DAYS (default
  2). Stale is a stop sign for agents: re-run, or ask the user (rule 5).
- missing: README rows whose file names no longer exist.

Run: python artifacts/prune.py [--plan] [--stale-days N]
Exit code is 0 always — this plans, it does not delete.
"""

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

TEXT_EXTS = (".py", ".md", ".html", ".json", ".txt", ".sh")
SKIP_PARTS = {"books", "data", "node_modules", ".git", "archive"}
# The gate itself and dir markers are infrastructure, not evidence.
SKIP_NAMES = {"README.md", "prune.py", ".gitkeep"}


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files", "artifacts"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    files = []
    for line in out.splitlines():
        line = line.strip().replace("\\", "/")
        if line.endswith(tuple(TEXT_EXTS + (".log",))):
            rel = line.removeprefix("artifacts/")
            if Path(rel).name not in SKIP_NAMES:
                files.append(rel)
    return sorted(files)


def last_commit_dates():
    out = subprocess.run(
        ["git", "--no-pager", "log", "--format=%x00%ad", "--date=short", "--name-only", "--", "artifacts"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout
    dates = {}
    current = None
    for line in out.splitlines():
        if line.startswith("\x00"):
            current = line[1:]
        elif line.startswith("artifacts/"):
            name = line.split("/", 1)[1]
            if name not in dates:
                dates[name] = current
    return dates


def main():
    parser = argparse.ArgumentParser(description="Artifacts pruner (plan only).")
    parser.add_argument("--plan", action="store_true", help="print the plan (the only mode)")
    parser.add_argument("--stale-days", type=int, default=2)
    args = parser.parse_args()

    files = tracked_files()
    dates = last_commit_dates()
    index_text = (HERE / "README.md").read_text(encoding="utf-8")

    # corpus of references (exclude books/data); self-references never count
    corpus = {}
    for path in ROOT.rglob("*"):
        if (
            path.is_file()
            and path.suffix in TEXT_EXTS
            and not (set(path.parts) & SKIP_PARTS)
        ):
            corpus[str(path)] = path.read_text(encoding="utf-8", errors="replace")

    cutoff = date.today() - timedelta(days=args.stale_days)
    stale, unindexed, unreferenced, over = [], [], [], []

    families = defaultdict(list)
    for name in files:
        base = Path(name).name
        stem = re.sub(r"-\d{4}-\d{2}-\d{2}", "", base)
        families[re.split(r"[-.]", stem)[0]].append(name)

        if name not in index_text and base not in index_text and not re.split(r"[-.]", base)[0] in index_text:
            unindexed.append(name)

        base = Path(name).name
        self_posix = (ROOT / "artifacts" / name).as_posix()
        others = [
            Path(h).name
            for h, t in corpus.items()
            if Path(h).as_posix() != self_posix and (name in t or base in t)
        ]
        if not others:
            unreferenced.append(name)

        stamped = dates.get(name)
        if stamped:
            try:
                if datetime.strptime(stamped, "%Y-%m-%d").date() < cutoff:
                    stale.append((name, stamped))
            except ValueError:
                pass

    for family, members in families.items():
        runs = [m for m in members if re.search(r"(v\d|run\d|wired|replay|quotealign|flaked)", m)]
        if len(runs) > 2:
            over.append((family, len(runs), sorted(runs)))

    missing = []
    index_section = index_text.split("## Index", 1)[-1] if "## Index" in index_text else index_text
    spans = re.findall(r'`([^`]+)`', index_section)
    for s in spans:
        for part in re.split(r'[, ]+', s):
            part = part.strip()
            if any(part.startswith(prefix) for prefix in ('harnesses/', 'probes/', 'datasets/', 'reports/', 'evidence/', 'plans/', 'validate/')) and not any(ch in part for ch in ('*', '{', '}', '<', '…')):
                if not (HERE / part).exists():
                    missing.append(part)
    missing = sorted(set(missing))

    print(f"# prune plan — {len(files)} tracked files, stale-days {args.stale_days}")
    print(f"\n## stale ({len(stale)}) — agents: re-run or ask the user before trusting")
    for name, stamped in sorted(stale):
        print(f"- {name} | {stamped}")
    print(f"\n## unindexed ({len(unindexed)}) — add a README row or delete")
    for name in sorted(unindexed):
        print(f"- {name}")
    print(f"\n## missing ({len(missing)}) — rows in README that do not exist on disk")
    for name in missing:
        print(f"- {name}")
    print(f"\n## unreferenced ({len(unreferenced)}) — candidates; the index row's reason may keep them")
    for name in sorted(unreferenced):
        print(f"- {name}")
    print(f"\n## over-versioned families ({len(over)}) — keep latest + what a doc names")
    for family, count, runs in sorted(over):
        print(f"- {family}: {count} runs -> {runs}")


if __name__ == "__main__":
    main()
