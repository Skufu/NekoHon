"""Rate the follow-up pills and the quote a click shows, scenario by scenario.

The scenarios live in `tests/test_followup_pills.py` so this probe and the
tests grade the same behavior. No model, no server.

Run from the repo root:
    python artifacts/probes/probe-followup-quality-2026-10-26.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.test_followup_pills import RATING_SCENARIOS, rate_scenario  # noqa: E402


def main():
    passed = 0
    total = 0
    for scenario in RATING_SCENARIOS:
        result = rate_scenario(scenario)
        passed += result["passed"]
        total += result["total"]
        print(f"{result['name']}  {result['passed']}/{result['total']}")
        print(f"  pills: {result['pills']}")
        print(f"  quote: {result['quote']!r}")
        for name, ok, _detail in result["checks"]:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print()
    print(f"overall: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
