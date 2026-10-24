"""Repair doc paths that point at a file which moved, when the move is unambiguous.

Rule: a missing path is rewritten only when its basename exists exactly once in
the repo. Two matches means the reference is genuinely ambiguous and a human
decides. `--apply` writes; without it, prints the plan.

This is a docs-only tool: it never touches code or data.
"""

import argparse
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ["README.md", "BUILD_PLAN.md", "GLOSSARY.md", "AGENTS.md", "artifacts/README.md"]
PATH_RE = re.compile(r"artifacts/[A-Za-z0-9_./-]+?\.(?:jsonl|json|md|py|ipynb|txt)")
SKIP = {"probe-foo-2026-10-15.py", "eval-set-2026-10-15.json",
        "answer-mode-2026-10-15.md", "eval-plain-2026-10-15-v7.json",
        "generate-bindings-2026-10-21.py"}


def candidates(basename):
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "node_modules" and d != "__pycache__"]
        if basename in filenames:
            found.append(str(Path(dirpath, basename).relative_to(ROOT)).replace("\\", "/"))
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    plan = []
    for doc in DOCS:
        path = ROOT / doc
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        changed = False
        for index, line in enumerate(lines):
            for match in PATH_RE.finditer(line):
                ref = match.group(0)
                if (ROOT / ref).exists() or os.path.basename(ref) in SKIP:
                    continue
                found = candidates(os.path.basename(ref))
                if len(found) != 1:
                    plan.append((doc, index + 1, ref, f"ambiguous: {found}"))
                    continue
                lines[index] = line.replace(ref, found[0])
                line = lines[index]
                changed = True
                plan.append((doc, index + 1, ref, found[0]))
        if args.apply and changed:
            path.write_text("\n".join(lines), encoding="utf-8")

    for doc, line, old, new in plan:
        print(f"{doc}:{line}  {old} -> {new}")
    print(f"\n{sum(1 for p in plan if not p[3].startswith('ambiguous'))} repairable, "
          f"{sum(1 for p in plan if p[3].startswith('ambiguous'))} ambiguous")


if __name__ == "__main__":
    main()
