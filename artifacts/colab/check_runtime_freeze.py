"""Offline check: does a VM freeze report satisfy the bundle's pins?

Exact pins in `expected` must match. `recorded` entries must be present and
non-empty but are not asserted to a version nobody measured. Exit 2 on any
mismatch, 0 only when every expected entry is satisfied.

Distribution names are compared with the published Python packaging
normalization (lowercase, each run of `-`, `_`, `.` collapses to `-`); the
version strings remain exact. A lock or freeze that names the same canonical
distribution twice with different versions fails instead of keeping one.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "release-manifest.json"


def canonical_name(name):
    """PEP 503 distribution-name normalization."""
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def parse_pins(lines, source, failures):
    pins = {}
    for line in lines:
        line = line.strip()
        if "==" not in line or line.startswith("#"):
            continue
        name, version = line.split("==", 1)
        key = canonical_name(name)
        version = version.strip()
        if key in pins and pins[key] != version:
            failures.append("%s lists %s twice with different versions (%s, %s)"
                            % (source, key, pins[key], version))
            continue
        pins[key] = version
    return pins


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("report", help="runtime-freeze.json produced on the VM")
    parser.add_argument("--manifest", default=str(MANIFEST))
    args = parser.parse_args(argv)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    expected = (manifest.get("dependencies") or {}).get("expected_top_level") or {}
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    if report.get("schema") != "runtime-freeze/1":
        print("FAIL schema %r" % report.get("schema"))
        return 2
    got = dict(report.get("versions") or {})
    got["python"] = report.get("python")
    failures = []
    lock_path = HERE / "requirements-locked.txt"
    if not lock_path.exists():
        failures.append("requirements-locked.txt is missing; refusing a top-level-only check")
    else:
        locked = parse_pins(lock_path.read_text(encoding="utf-8").splitlines(),
                            "requirements-locked.txt", failures)
        freeze_path = Path(args.report).with_name("runtime-freeze.txt")
        if not freeze_path.exists():
            failures.append("runtime-freeze.txt is missing; the full lock cannot be checked")
        else:
            installed = parse_pins(freeze_path.read_text(encoding="utf-8").splitlines(),
                                   "runtime-freeze.txt", failures)
            for name, version in sorted(locked.items()):
                if installed.get(name) != version:
                    failures.append("%s locked %s, installed %r"
                                    % (name, version, installed.get(name)))
    for name, wanted in sorted(expected.items()):
        actual = got.get(name)
        if wanted == "recorded":
            if not actual or actual == "unknown":
                failures.append("%s not recorded" % name)
        elif str(actual) != str(wanted):
            failures.append("%s expected %s, found %s" % (name, wanted, actual))
    print(json.dumps({"status": "pass" if not failures else "fail",
                      "failures": failures, "expected": expected,
                      "observed": {k: got.get(k) for k in expected}}, indent=1, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
