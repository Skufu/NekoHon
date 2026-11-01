"""Gate for a corpus-reviewed candidate artifact directory.

This is a pure validator plus CLI. It never edits the artifact directory and
never writes a report unless ``--out`` is given. It fails closed: every required
check must run, and any integrity failure returns exit 1 with structured reasons.

Checks:
  * proposal length == selected ledger rows == manifest selected count;
  * ordered, full-dict equality of every proposal record to its original line;
  * proposal message/user/target hashes recomputed from actual proposal bytes;
  * candidate artifact hashes and optional ``.sha256`` sidecars;
  * pinned review-ledger hashes from combined-review-check.json;
  * selected non-refusal claims have a supported literal provided-source witness;
  * stale origin/messages/user/target hashes and forbidden mechanical warnings;
  * full-component and candidate-component folds are pure;
  * selected source/question/input/text identities do not overlap dev86;
  * manifest checks, counts, coverage, and readiness-flag consistency.

Usage:
    python artifacts/harnesses/corpus_release_verifier.py \
        --artifactdir artifacts/runs/data-release-2026-10-29/corpus-reviewed-v2 \
        [--root .] [--candidate-dir DIR] [--out report.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT_DEFAULT = Path(__file__).resolve().parents[2]
REL = Path("artifacts/runs/data-release-2026-10-29")
REFUSAL = "Not in this book."
FORBIDDEN_SELECTED_CODES = {
    "target_quote_normalized_only",
    "target_quote_not_in_book",
    "target_quote_wrong_source",
    "source_formatting_drift",
    "source_normalized_only",
    "source_unresolved",
    "source_id_text_conflict",
    "chapter_tag_mismatch",
}
PROVISIONAL_PREFIXES = ("PROVISIONAL", "DRAFT_PROPOSED")


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def question_key(question):
    return " ".join((question or "").lower().split()).rstrip("?.! ").strip()


def find_candidate_dir(artifact_dir):
    preferred = Path(artifact_dir) / "candidate-fullgraph-2026-10-30"
    if preferred.is_dir():
        return preferred
    candidates = sorted(path for path in Path(artifact_dir).glob("candidate*") if path.is_dir())
    if not candidates:
        raise FileNotFoundError("no candidate directory under artifact dir")
    return candidates[-1]


def resolve(root, path):
    candidate = Path(path)
    return candidate if candidate.is_absolute() else Path(root) / candidate


def validate(artifact_dir, root=None, candidate_dir=None):
    root = Path(root or ROOT_DEFAULT).resolve()
    artifact_dir = Path(artifact_dir).resolve()
    candidate_dir = Path(candidate_dir).resolve() if candidate_dir else find_candidate_dir(artifact_dir)
    reasons = []
    checks = {}

    def fail(code, detail):
        reasons.append({"code": code, "detail": detail})

    def check(code, condition, detail="", value=None):
        checks[code] = {"pass": bool(condition), "value": value}
        if not condition:
            fail(code, detail)

    try:
        main_manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        main_manifest = None
    candidate_manifest = json.loads((candidate_dir / "candidate-manifest.json").read_text(encoding="utf-8"))
    main_ledger = load_jsonl(artifact_dir / "ledger.jsonl")
    candidate_ledger = load_jsonl(candidate_dir / "candidate-ledger.jsonl")
    proposal = load_jsonl(candidate_dir / "candidate-proposal.jsonl")

    historical = [row for row in main_ledger if row.get("role") == "historical_train"]
    dev = [row for row in main_ledger if row.get("role") == "dev"]
    selected = [row for row in candidate_ledger if row.get("selected")]
    selected_ids = [row.get("id") for row in selected]
    check("selected_ids_unique", len(selected_ids) == len(set(selected_ids)), "selected ids are not unique")

    manifest_counts = candidate_manifest.get("counts") or {}
    expected_selected = manifest_counts.get("selected")
    check(
        "proposal_length",
        len(proposal) == len(selected) == expected_selected,
        f"proposal {len(proposal)}, selected ledger {len(selected)}, manifest selected {expected_selected}",
        {"proposal": len(proposal), "selected": len(selected), "manifest": expected_selected},
    )
    train = [row for row in selected if row.get("fold") == "train"]
    validation = [row for row in selected if row.get("fold") == "validation"]
    check(
        "fold_counts",
        len(train) == manifest_counts.get("train") and len(validation) == manifest_counts.get("validation"),
        "train/validation counts differ from manifest",
        {"train": len(train), "validation": len(validation)},
    )

    # Ordered full-dict proposal equality and actual proposal hashes.
    original_cache = {}
    main_by_id = {row.get("id"): row for row in historical}
    bad_proposal = []
    bad_hashes = []
    stale = []
    for index, row in enumerate(selected):
        if index >= len(proposal):
            bad_proposal.append({"id": row.get("id"), "reason": "missing proposal row"})
            continue
        origin = row.get("origin") or {}
        source_path = resolve(root, origin.get("path"))
        line = int(origin.get("record") or 0)
        if source_path not in original_cache:
            raw_lines = source_path.read_bytes().split(b"\n")
            raw_lines = [line for line in raw_lines if line]
            original_cache[source_path] = raw_lines
        lines = original_cache[source_path]
        if line < 1 or line > len(lines):
            bad_proposal.append({"id": row.get("id"), "reason": "origin line out of range"})
            continue
        raw_line = lines[line - 1]
        original = json.loads(raw_line)
        if proposal[index] != original:
            bad_proposal.append({"id": row.get("id"), "reason": "proposal record differs from original line", "index": index})
            continue
        if sha_bytes(source_path.read_bytes()) != origin.get("sha256"):
            stale.append({"id": row.get("id"), "reason": "origin full-file sha mismatch"})
        if sha_bytes(raw_line) != origin.get("line_sha256"):
            stale.append({"id": row.get("id"), "reason": "origin line sha mismatch"})
        messages = proposal[index].get("messages") or []
        if len(messages) < 3:
            bad_hashes.append({"id": row.get("id"), "reason": "proposal has fewer than 3 messages"})
            continue
        messages_hash = sha_text(json.dumps(messages, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        user_hash = sha_text(messages[1].get("content") or "")
        target_hash = sha_text(messages[2].get("content") or "")
        if messages_hash != row.get("messages_sha256"):
            bad_hashes.append({"id": row.get("id"), "reason": "actual proposal messages hash mismatch"})
        authoritative = main_by_id.get(row.get("id"), {})
        if user_hash != authoritative.get("user_prompt_sha256"):
            bad_hashes.append({"id": row.get("id"), "reason": "actual proposal user hash mismatch"})
        if target_hash != row.get("target_sha256") and target_hash != authoritative.get("target_sha256"):
            bad_hashes.append({"id": row.get("id"), "reason": "actual proposal target hash mismatch"})
        codes = set(row.get("original_issue_codes") or [])
        if codes & FORBIDDEN_SELECTED_CODES:
            stale.append({"id": row.get("id"), "reason": "selected row has forbidden mechanical warning", "codes": sorted(codes & FORBIDDEN_SELECTED_CODES)})
    check("proposal_order_and_content", not bad_proposal, "proposal length/order/content differs", bad_proposal[:10])
    check("proposal_hashes", not bad_hashes, "actual proposal hashes differ from ledger", bad_hashes[:10])
    check("stale_origin_or_mechanical", not stale, "stale origin or forbidden warning", stale[:10])

    # Artifact hashes and optional sidecars.
    artifacts = candidate_manifest.get("artifacts") or {}
    check("candidate_proposal_hash", artifacts.get("candidate_proposal_sha256") == sha_bytes((candidate_dir / "candidate-proposal.jsonl").read_bytes()), "candidate proposal hash mismatch")
    check("candidate_ledger_hash", artifacts.get("candidate_ledger_sha256") == sha_bytes((candidate_dir / "candidate-ledger.jsonl").read_bytes()), "candidate ledger hash mismatch")
    sidecars = []
    for directory in (artifact_dir, candidate_dir):
        for sidecar in directory.glob("*.sha256"):
            stem = sidecar.name[:-7]
            target = directory / stem
            if not target.is_file():
                for suffix in (".json", ".jsonl"):
                    alternative = directory / (stem + suffix)
                    if alternative.is_file():
                        target = alternative
                        break
            if not target.is_file():
                sidecars.append(f"unresolved:{sidecar}")
            elif sidecar.read_text().strip() != sha_bytes(target.read_bytes()):
                sidecars.append(f"stale:{sidecar}")
    check("sidecars", not sidecars, "sidecar hashes differ or target missing", sidecars[:10])

    # Review pins and missing/duplicate review coverage.
    combined_path = artifact_dir / "combined-review-check.json"
    if not combined_path.is_file():
        combined_path = root / REL / "combined-review-check.json"
    combined = json.loads(combined_path.read_text(encoding="utf-8")) if combined_path.is_file() else {}
    expected = {part.get("shard", "").upper(): part.get("sha256") for part in combined.get("parts") or []}
    review_paths = {}
    for row in historical:
        review = row.get("semantic_review") or {}
        shard = str(review.get("shard") or "").upper()
        if shard and review.get("review_ledger_path"):
            review_paths.setdefault(shard, review.get("review_ledger_path"))
    if not review_paths:
        review_paths = {
            "A": str(root / REL / "corpus-review-a/ledger.jsonl"),
            "B": str(root / REL / "corpus-review-b/ledger.jsonl"),
        }
    review_rows = {}
    pin_mismatch = []
    for shard, path in review_paths.items():
        path = resolve(root, path)
        actual = sha_bytes(path.read_bytes()) if path.is_file() else None
        if not expected.get(shard) or actual != expected.get(shard):
            pin_mismatch.append({"shard": shard, "expected": expected.get(shard), "actual": actual})
        if path.is_file():
            review_rows[shard] = {row["id"]: row for row in load_jsonl(path)}
    check("review_pins", not pin_mismatch, "review ledger pins mismatch", pin_mismatch)
    missing_reviews = [row.get("id") for row in historical if not row.get("semantic_review")]
    duplicate_reviews = []
    seen = set()
    for row in historical:
        rid = row.get("id")
        if rid in seen:
            duplicate_reviews.append(rid)
        seen.add(rid)
    if main_manifest:
        check("semantic_review_coverage", not missing_reviews and not duplicate_reviews, "missing/duplicate semantic reviews", {"missing": missing_reviews[:10], "duplicate": duplicate_reviews[:10]})

    # Selected candidate status must agree with the main ledger and the pinned
    # external review. REVIEW is legitimate when the warning was resolved by
    # source review; FAIL is never selectable.
    bad_status = []
    for row in selected:
        main_row = main_by_id.get(row.get("id"), {})
        review = main_row.get("semantic_review") or {}
        shard = str(review.get("shard") or "").upper()
        reviewer_row = (review_rows.get(shard) or {}).get(row.get("id"))
        status_reasons = []
        if row.get("semantic_decision") != "accepted":
            status_reasons.append("candidate semantic_decision")
        if row.get("semantic_binding_status") != "BOUND":
            status_reasons.append("candidate semantic_binding_status")
        if row.get("mechanical_status") not in ("PASS", "REVIEW"):
            status_reasons.append("candidate mechanical_status")
        if review.get("decision") != "accepted":
            status_reasons.append("main semantic decision")
        if review.get("binding_status") != "BOUND":
            status_reasons.append("main binding status")
        if main_row.get("mechanical_status") not in ("PASS", "REVIEW"):
            status_reasons.append("main mechanical_status")
        if row.get("semantic_decision") != review.get("decision"):
            status_reasons.append("candidate/main semantic mismatch")
        if row.get("semantic_binding_status") != review.get("binding_status"):
            status_reasons.append("candidate/main binding mismatch")
        if row.get("mechanical_status") != main_row.get("mechanical_status"):
            status_reasons.append("candidate/main mechanical mismatch")
        if reviewer_row is None or ((reviewer_row.get("review") or {}).get("status") != "accepted"):
            status_reasons.append("pinned review status")
        if status_reasons:
            bad_status.append({"id": row.get("id"), "reasons": status_reasons})
    check("selected_status", not bad_status, "selected candidate status is not accepted/BOUND/non-FAIL with pinned accepted review", bad_status[:10])

    # Claims and literal witnesses for selected non-refusal rows.
    bad_claims = []
    bad_witnesses = []
    for row in selected:
        if (row.get("target_kind") or row.get("target_kind")) == "refusal":
            continue
        review = (row.get("semantic_review") or {})
        # Candidate ledger does not carry semantic_review; use main ledger by id.
        main_row = next((item for item in historical if item.get("id") == row.get("id")), {})
        review = main_row.get("semantic_review") or review
        shard = str(review.get("shard") or "").upper()
        reviewer_row = (review_rows.get(shard) or {}).get(row.get("id"))
        if reviewer_row is None:
            bad_claims.append({"id": row.get("id"), "reason": "review row missing"})
            continue
        claims = reviewer_row.get("target_claims") or []
        supported = [
            claim
            for claim in claims
            if claim.get("verdict") == "supported"
            and any(w.get("role") == "provided_source" for w in claim.get("witnesses") or [])
        ]
        if not supported:
            bad_claims.append({"id": row.get("id"), "reason": "no supported provided-source claim"})
            continue
        source_path = resolve(root, (row.get("origin") or {}).get("path"))
        lines = original_cache.get(source_path)
        if lines is None:
            lines = [line for line in source_path.read_bytes().split(b"\n") if line]
        original = json.loads(lines[int(row["origin"]["record"]) - 1])
        messages = original.get("messages") or []
        for claim in supported:
            for witness in claim.get("witnesses") or []:
                if witness.get("role") != "provided_source":
                    continue
                mi = witness.get("message_index")
                start, end = witness.get("start"), witness.get("end")
                if not isinstance(mi, int) or mi < 0 or mi >= len(messages):
                    bad_witnesses.append({"id": row.get("id"), "reason": "message index"})
                    continue
                content = messages[mi].get("content") or ""
                if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end > len(content) or content[start:end] != witness.get("text"):
                    bad_witnesses.append({"id": row.get("id"), "reason": "offset/text"})
                    continue
                if content.startswith("Earlier in this conversation"):
                    passage_start = content.find("Passages:\n")
                    passage_end = content.find("\n\nCopy one sentence")
                    if passage_start < 0 and "Passage context:\n" in content:
                        passage_start = content.find("Passage context:\n")
                        passage_end = len(content)
                    if passage_start < 0 or start < passage_start or (passage_end >= 0 and end > passage_end):
                        bad_witnesses.append({"id": row.get("id"), "reason": "outside provided passage"})
                else:
                    passage_start = content.find("Passages:\n")
                    passage_end = content.find("\n\nCopy one sentence")
                    if passage_start < 0 and "Passage context:\n" in content:
                        passage_start = content.find("Passage context:\n")
                        passage_end = len(content)
                    if passage_start < 0 or start < passage_start or (passage_end >= 0 and end > passage_end):
                        bad_witnesses.append({"id": row.get("id"), "reason": "outside provided passage"})
    check("selected_claims", not bad_claims, "selected non-refusal claims missing", bad_claims[:10])
    check("selected_witnesses", not bad_witnesses, "selected witnesses invalid", bad_witnesses[:10])

    # Full and candidate component folds.
    def mixed_folds(key):
        groups = defaultdict(set)
        for row in selected:
            groups[row.get(key)].add(row.get("fold"))
        return sorted(component for component, folds in groups.items() if len(folds) > 1)

    mixed_full = mixed_folds("full_component_id")
    mixed_candidate = mixed_folds("candidate_component_id")
    check("full_component_mixed_fold", not mixed_full, "full components straddle folds", mixed_full[:10])
    check("candidate_component_mixed_fold", not mixed_candidate, "candidate components straddle folds", mixed_candidate[:10])
    manifest_checks = candidate_manifest.get("checks") or {}
    bad_checks = {
        key: value
        for key, value in manifest_checks.items()
        if (key != "zero_target_support_straddle" and value) or (key == "zero_target_support_straddle" and value is not True)
    }
    check("manifest_checks", not bad_checks, "candidate manifest checks are nonempty/false", bad_checks)

    # Dev separation, question and exact-text identities.
    dev_support = {key for row in dev for key in row.get("support_keys") or []}
    dev_context = {key for row in dev for key in row.get("context_keys") or []}
    dev_text = {tuple(key) for row in dev for key in row.get("support_text_keys") or []}
    selected_ids_set = set(selected_ids)
    selected_main = [row for row in historical if row.get("id") in selected_ids_set]
    support_overlap = sorted({key for row in selected_main for key in row.get("support_keys") or []} & dev_support)
    context_overlap = sorted(
        ({key for row in selected_main for key in row.get("support_keys") or []} | {key for row in selected_main for key in row.get("context_keys") or []})
        & (dev_support | dev_context)
    )
    text_overlap = sorted({tuple(key) for row in selected_main for key in row.get("support_text_keys") or []} & dev_text)
    dev_questions = {question_key(row.get("question")) for row in dev}
    question_overlap = sorted({question_key(row.get("question")) for row in selected_main} & dev_questions)
    check("dev_support_overlap", not support_overlap, "selected support overlaps dev", support_overlap[:10])
    check("dev_context_overlap", not context_overlap, "selected context overlaps dev", context_overlap[:10])
    check("dev_text_overlap", not text_overlap, "selected exact text overlaps dev", text_overlap[:10])
    check("dev_question_overlap", not question_overlap, "selected question overlaps dev", question_overlap[:10])
    input_hashes = [row.get("messages_sha256") for row in selected]
    check("duplicate_selected_input", len(input_hashes) == len(set(input_hashes)), "selected rows repeat a complete input")

    # Coverage / counts / readiness.
    coverage = candidate_manifest.get("coverage") or {}
    target_kinds = Counter(row.get("target_kind") for row in selected)
    check("coverage_target_kinds", dict(coverage.get("target_kinds") or {}) == dict(target_kinds), "coverage target kinds differ", {"manifest": coverage.get("target_kinds"), "actual": dict(target_kinds)})
    check("coverage_refusals", coverage.get("refusals") == target_kinds.get("refusal", 0), "coverage refusal count differs")
    check("coverage_synthetic", coverage.get("synthetic_rows", 0) == sum(1 for row in selected_main if any(str(scope).startswith("synthetic:") for scope in row.get("source_scope") or [])), "coverage synthetic count differs")
    readiness = {
        "ready_for_training": candidate_manifest.get("ready_for_training"),
        "prospective_eligible": candidate_manifest.get("prospective_eligible"),
        "launchable": candidate_manifest.get("launchable"),
        "canonical_bind_pending": candidate_manifest.get("canonical_bind_pending"),
        "certified_gpu_release": candidate_manifest.get("certified_gpu_release"),
        "status": candidate_manifest.get("status"),
    }
    status = str(readiness["status"] or "")
    contradiction = (
        readiness["ready_for_training"] is not False
        or readiness["prospective_eligible"] is not True
        or readiness["launchable"] is not False
        or readiness["canonical_bind_pending"] is not True
        or readiness["certified_gpu_release"] is not False
        or not status.startswith(PROVISIONAL_PREFIXES)
    )
    check("readiness_consistency", not contradiction, "readiness flags contradict provisional state", readiness)

    report = {
        "status": "FAIL" if reasons else "PASS",
        "artifactdir": str(artifact_dir),
        "candidate_dir": str(candidate_dir),
        "reasons": reasons,
        "checks": checks,
        "counts": {
            "proposal": len(proposal),
            "selected": len(selected),
            "train": len(train),
            "validation": len(validation),
            "historical": len(historical),
            "dev": len(dev),
        },
        "readiness": readiness,
    }
    scope_path = artifact_dir / "graph-scope-verification.json"
    if scope_path.is_file():
        scope = json.loads(scope_path.read_text(encoding="utf-8"))
        report["graph_scope"] = {
            "v2_population": (scope.get("v2_full_graph") or {}).get("population"),
            "v2_components": (scope.get("v2_full_graph") or {}).get("components"),
            "v2_top_sizes": (scope.get("v2_full_graph") or {}).get("top_sizes"),
            "larger_1767_population": (scope.get("larger_1767_reporting_graph") or {}).get("population"),
            "larger_1767_components": (scope.get("larger_1767_reporting_graph") or {}).get("components"),
            "larger_1767_top_sizes": (scope.get("larger_1767_reporting_graph") or {}).get("top_sizes"),
            "duplicate_777_new_edges": (scope.get("duplicate_777_check") or {}).get("new_structural_edges_vs_844"),
        }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fail-closed gate for a corpus-reviewed candidate.")
    parser.add_argument("--artifactdir", default=str(Path(__file__).resolve().parents[1] / "runs" / "data-release-2026-10-29" / "corpus-reviewed-v2"))
    parser.add_argument("--root", default=str(ROOT_DEFAULT))
    parser.add_argument("--candidate-dir", default=None)
    parser.add_argument("--out", default=None, help="write the report here; default is print-only")
    args = parser.parse_args(argv)
    try:
        report = validate(args.artifactdir, root=args.root, candidate_dir=args.candidate_dir)
    except Exception as error:
        report = {"status": "FAIL", "reasons": [{"code": "validator_exception", "detail": repr(error)}], "checks": {}}
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
