#!/usr/bin/env python3
"""Probe 5: the real training_reviewed.verify_approval binds actual bytes.

No synthetic substitute: this calls the shipped runner function with a package
object built from its own schema. It is not an end-to-end GPU run.
"""

import json
import sys
from copy import deepcopy

import probe_common as C

sys.path.insert(0, str(C.ROOT / "artifacts" / "colab"))
import training_reviewed as TR  # noqa: E402


def build_package():
    package = TR.Package()
    package.manifest = {
        "inputs": {
            "dataset": {"sha256_bytes": "dataset", "sha256_rows": "rows",
                        "row_facts": {"rows": 1}},
            "recipe_sha256": "recipe",
            "runner": {"sha256": "runner", "deps_sha256": "deps"},
        },
        "recipe": {"base_revision": "base", "tokenizer_revision": "tokenizer",
                   "tokenizer_chat_template_sha256": "template",
                   "tokenizer_config_sha256": "config"},
    }
    package.contract = {"export": {"gguf": "q4_k_m", "merged_16bit": True}}
    package.manifest_sha256 = "manifest"
    package.contract_sha256 = "contract"
    package.validation_block = {"sha256_bytes": "validation", "rows": 1}
    package.facts = {"controls_sha256": "controls",
                     "inventory": {"sha256": "inventory",
                                   "fragment_sha256": "fragment",
                                   "receipt_sha256": "receipt"}}
    return package


def report_for(package):
    report = dict(TR.expected_package_facts(package))
    report.update({"schema": TR.PREFLIGHT_SCHEMA, "status": "pass",
                   "manifest_sha256": package.manifest_sha256,
                   "contract_sha256": package.contract_sha256})
    return report


def run_case(package, approval, report, report_bytes):
    issues = TR.new_issues()
    TR.verify_approval(approval, json.dumps(approval).encode(), report,
                       report_bytes, package, issues)
    return {"ok": issues.ok, "codes": [f["code"] for f in issues.failures]}


def main():
    package = build_package()
    report = report_for(package)
    report_bytes = json.dumps(report, sort_keys=True).encode()
    approval = {
        "schema": TR.APPROVAL_SCHEMA, "decision": "approved",
        "reviewer": "probe", "approved_at": "2026-10-30T00:00:00Z",
        "manifest_sha256": package.manifest_sha256,
        "contract_sha256": package.contract_sha256,
        "preflight_report_sha256": C.sha_bytes(report_bytes),
        "export": package.contract["export"],
    }
    cases = []
    cases.append({"case": "valid", **run_case(package, approval, report, report_bytes)})

    # Same parsed report, different bytes: the binding is on bytes.
    other_bytes = json.dumps(dict(report), sort_keys=True, indent=2).encode()
    cases.append({"case": "same_report_different_bytes",
                  **run_case(package, approval, json.loads(other_bytes), other_bytes)})

    # Caller package identity changes after the approval was written.
    other_package = build_package()
    other_package.manifest_sha256 = "different-manifest"
    cases.append({"case": "caller_package_changed",
                  **run_case(other_package, approval, report, report_bytes)})

    bad = deepcopy(approval); bad.pop("reviewer")
    cases.append({"case": "no_attribution", **run_case(package, bad, report, report_bytes)})
    bad = deepcopy(approval); bad["decision"] = "pending"
    cases.append({"case": "not_approved", **run_case(package, bad, report, report_bytes)})
    bad = deepcopy(approval); bad["schema"] = "auto-approval/1"
    cases.append({"case": "wrong_schema", **run_case(package, bad, report, report_bytes)})
    bad = deepcopy(approval); bad["export"] = {"gguf": "q8_0", "merged_16bit": True}
    cases.append({"case": "wrong_export", **run_case(package, bad, report, report_bytes)})
    failing = dict(report); failing["status"] = "fail"
    failing_bytes = json.dumps(failing, sort_keys=True).encode()
    bad = deepcopy(approval); bad["preflight_report_sha256"] = C.sha_bytes(failing_bytes)
    cases.append({"case": "report_not_passing",
                  **run_case(package, bad, failing, failing_bytes)})
    facts = dict(report); facts["dataset_sha256"] = "drifted"
    facts_bytes = json.dumps(facts, sort_keys=True).encode()
    bad = deepcopy(approval); bad["preflight_report_sha256"] = C.sha_bytes(facts_bytes)
    cases.append({"case": "report_fact_drift",
                  **run_case(package, bad, facts, facts_bytes)})

    out = {"environment": C.environment(), "cases": cases}
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
