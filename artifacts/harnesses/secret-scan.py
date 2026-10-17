"""Secret scan for this repo. Artifact, not engine.

Every blob in git history and every tracked file is checked against two sets:

- the actual secret values on this machine, read in-process and never
  printed: `.judge-key` in the repo, `~/.config/opencode/opencode.json`,
  `~/.local/share/opencode/auth.json`, `~/.hermes/.env` (only values whose
  field name says key/token/secret/auth);
- the common credential formats: `sk-`, `gh*_`, `github_pat_`, `AIza`,
  `AKIA`, `hf_`, `gsk_`, `xox*`, `xai-`, `glpat-`, PEM private keys,
  key/token/secret assignments, `Bearer <token>`.

Hits are printed masked (first 4 chars + length). Exit 1 when anything is
found, 0 otherwise, so the scan can gate a commit.

Blind spot, stated honestly: a key with no recognizable prefix that is also
not among this machine's known values is not caught. Extend `known_values`
when a new provider key lands on the box.

Run: python artifacts/harnesses/secret-scan.py [--repo PATH]
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

KEY_FIELD = re.compile(r"key|token|secret|auth|password|passwd", re.I)
PATTERNS = [
    ("sk", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}")),
    ("github", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("github_pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("google", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("aws", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("hf", re.compile(r"hf_[A-Za-z0-9]{20,}")),
    ("groq", re.compile(r"gsk_[A-Za-z0-9]{20,}")),
    ("slack", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("xai", re.compile(r"xai-[A-Za-z0-9]{20,}")),
    ("gitlab", re.compile(r"glpat-[A-Za-z0-9_-]{20,}")),
    ("pem", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "assign",
        re.compile(
            r"(?i)(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|client[_-]?secret)"
            r"[\"'\s:=]{1,6}[A-Za-z0-9_\-]{24,}"
        ),
    ),
    ("bearer", re.compile(r"Bearer\s+[A-Za-z0-9_.\-]{24,}")),
]


def mask(value):
    value = str(value)
    return value[:4] + "..." + "(" + str(len(value)) + ")"


def collect(node, label, found):
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and len(value) >= 16 and KEY_FIELD.search(str(key)):
                found.append((label + ":" + str(key), value))
            else:
                collect(value, label, found)
    elif isinstance(node, list):
        for item in node:
            collect(item, label, found)


def known_values(repo):
    found = []
    judge_key = repo / ".judge-key"
    if judge_key.is_file():
        found.append((".judge-key", judge_key.read_text(encoding="utf-8").strip()))
    home = Path.home()
    for path, label in (
        (home / ".config" / "opencode" / "opencode.json", "opencode.json"),
        (home / ".local" / "share" / "opencode" / "auth.json", "auth.json"),
    ):
        try:
            collect(json.loads(path.read_text(encoding="utf-8")), label, found)
        except (OSError, ValueError):
            continue
    env_path = home / ".hermes" / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and KEY_FIELD.search(line.split("=", 1)[0]):
                value = line.split("=", 1)[1].strip()
                if len(value) >= 16:
                    found.append((".hermes/.env:" + line.split("=", 1)[0], value))
    except OSError:
        pass
    return found


def scan_text(text, path, known, hits):
    for label, value in known:
        if value and value in text:
            hits.append((path, "known:" + label, mask(value)))
    for name, pattern in PATTERNS:
        for match in pattern.finditer(text):
            hits.append((path, "pattern:" + name, mask(match.group(0))))


def run(repo):
    known = known_values(repo)
    print("known secret values in scope:", len(known), "(values never printed)")
    hits = []
    listing = subprocess.run(
        ["git", "rev-list", "--objects", "--all"],
        cwd=repo, capture_output=True, text=True,
    ).stdout
    seen = set()
    checked = 0
    for line in listing.splitlines():
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        sha, path = parts
        if sha in seen:
            continue
        seen.add(sha)
        content = subprocess.run(
            ["git", "cat-file", "-p", sha], cwd=repo, capture_output=True
        ).stdout
        if not content or len(content) > 8_000_000:
            continue
        checked += 1
        scan_text(content.decode("latin-1", errors="replace"), "history:" + path, known, hits)
    print("history blobs checked:", checked)
    for name in subprocess.run(
        ["git", "ls-files"], cwd=repo, capture_output=True, text=True
    ).stdout.splitlines():
        try:
            text = (repo / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scan_text(text, "tree:" + name, known, hits)
    unique = sorted(set(hits))
    print("hits:", len(unique))
    for path, label, shown in unique[:80]:
        print(" ", path, "|", label, "|", shown)
    return 1 if unique else 0


def main():
    parser = argparse.ArgumentParser(description="Scan git history and the tree for secrets.")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent.parent))
    args = parser.parse_args()
    sys.exit(run(Path(args.repo).resolve()))


if __name__ == "__main__":
    main()
