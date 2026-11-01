"""Manifest-consuming training runner for the reviewed corpus.

Status: code, not a run. `package` is CPU-only and covered by
`tests/test_training_reviewed.py`; `preflight` and `train` are written against
the pinned Unsloth/TRL/transformers APIs but have never run on a GPU. The
scratch notes name the unverified surface.

    package    CPU, no model. Reads a `prepare-training-manifest/1` plus a
               `training-runner-contract/1`, re-proves both datasets against
               the frozen ledger, and writes package-check.json.
    preflight  GPU. Requires a ready-to-launch package. Resolves the pinned base
               at its requested commit, verifies config.json, the tokenizer
               vocabulary files, and every weight file by sha256 (weights
               streamed) before the loader runs, passes the
               verified local snapshot (never the repo tag) to the loader with
               local-only flags, hashes the actual cached tokenizer_config.json,
               checks the chat template, proves ordinary text tokenizes, tokenizes
               every train and validation
               row without truncation, builds final-assistant masks, and runs
               bounded stop checks. Writes a report plus an identity measurement
               even when it refuses.
    train      GPU. Requires that report plus an independent approval binding
               its bytes. Re-runs every source check and every measurement in
               session, refuses on drift, trains, exports, and writes a
               `training-run-report/1` only if prepare_training.verify_run
               accepts it.

The mask is final-assistant-only. The historical helper could supervise every
assistant turn; this corpus has one assistant message per row, so the masks
agree on today's bytes. A row that cannot prove the rule fails closed.

Exit codes: 0 ok, 2 refused, 3 bad usage.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import traceback
import zipfile
from pathlib import Path

MANIFEST_SCHEMA = "prepare-training-manifest/1"
CONTRACT_SCHEMA = "training-runner-contract/1"
PREFLIGHT_SCHEMA = "training-preflight-report/1"
APPROVAL_SCHEMA = "training-preflight-approval/1"
RUN_SCHEMA = "training-run-report/1"
IDENTITY_SCHEMA = "training-identity-measurement/1"
STOP_CHECK_MAX_NEW_TOKENS = 256
EXPORT_QUANT = "q4_k_m"
EXPORT_MERGED = "merged_16bit"
HASH_CHUNK_SIZE = 8 * 1024 * 1024
WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth", ".gguf", ".h5", ".msgpack", ".ckpt")
TOKENIZER_REPRESENTATION_FILES = ("tokenizer.json", "tokenizer.model",
                                  "vocab.json", "merges.txt")
TOKENIZER_SANITY_TEXTS = (
    "The quick brown fox jumps over the lazy dog.",
    "A steady rain fell on the empty street.",
)

_PT = None


def _prepare_training():
    """Load the sibling gate by path, so a stray module cannot shadow it."""
    global _PT
    if _PT is None:
        path = Path(__file__).with_name("prepare_training.py")
        spec = importlib.util.spec_from_file_location("_reviewed_prepare_training", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load %s" % path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _PT = module
    return _PT


def new_issues():
    return _prepare_training().Report()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_text(text):
    return sha256_bytes(str(text).encode("utf-8"))


def canonical_json(obj):
    return _prepare_training().canonical_json(obj)


def read_jsonl(data):
    return _prepare_training().read_jsonl(data)


def label_family(row):
    return _prepare_training().label_family(row)


def row_messages_sha256(row):
    return sha256_text(canonical_json(row.get("messages")))


def sorted_hash(values):
    return sha256_text("\n".join(sorted(str(value) for value in values)))


def file_sha256(path):
    return sha256_bytes(Path(path).read_bytes())


def stream_file_sha256(path, chunk_size=HASH_CHUNK_SIZE):
    """Hash a large file without holding it in memory. Returns (sha256, bytes)."""
    digest = hashlib.sha256()
    total = 0
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            total += len(block)
            digest.update(block)
    return digest.hexdigest(), total


def same_real_path(left, right):
    if not left or not right:
        return False
    return os.path.realpath(str(left)) == os.path.realpath(str(right))


def same_path(left, right):
    left, right = str(left), str(right)
    return left == right or left.endswith(right) or right.endswith(left)


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def read_json_file(path, issues, label):
    """Return (object, bytes). A missing or bad file is a named failure."""
    if not path:
        issues.fail(label + "_missing", "no path was supplied")
        return None, b""
    path = Path(path)
    if not path.exists():
        issues.fail(label + "_missing", "%s does not exist" % path)
        return None, b""
    try:
        data = path.read_bytes()
        obj = json.loads(data.decode("utf-8"))
    except Exception as exc:
        issues.fail(label + "_invalid", "%s: %s" % (path, exc))
        return None, b""
    if not isinstance(obj, dict):
        issues.fail(label + "_invalid", "%s is not a JSON object" % path)
        return None, b""
    return obj, data


class Package:
    """Everything the CPU stage proved, plus the rows the GPU stage needs."""

    def __init__(self):
        self.issues = new_issues()
        self.manifest = None
        self.contract = None
        self.manifest_sha256 = None
        self.contract_sha256 = None
        self.rows = []
        self.validation_rows = []
        self.validation_block = {}
        self.ledger = []
        self.facts = {}


# --------------------------------------------------------------- package


def verify_header(manifest, contract, manifest_bytes, contract_bytes, issues):
    if manifest.get("schema") != MANIFEST_SCHEMA:
        issues.fail("manifest_schema", "expected %s, found %r"
                    % (MANIFEST_SCHEMA, manifest.get("schema")))
    status = str(manifest.get("status", ""))
    if status not in ("ready-to-launch", "validated_fixture"):
        issues.fail("manifest_not_ready",
                    "manifest status is %r; only ready-to-launch or a validated fixture may proceed"
                    % status)
    if manifest.get("failures"):
        issues.fail("manifest_failures_present",
                    "a ready-to-launch manifest carries %d failure(s)" % len(manifest["failures"]))
    if contract.get("schema") != CONTRACT_SCHEMA:
        issues.fail("contract_schema_unknown", "expected %s, found %r"
                    % (CONTRACT_SCHEMA, contract.get("schema")))
    if not _prepare_training().SHA_RE.match(str(contract.get("manifest_sha256", ""))):
        issues.fail("contract_manifest_sha256_invalid", "contract.manifest_sha256 is not a sha256")
    elif contract["manifest_sha256"] != sha256_bytes(manifest_bytes):
        issues.fail("contract_manifest_mismatch",
                    "contract binds %s, manifest bytes are %s"
                    % (contract["manifest_sha256"], sha256_bytes(manifest_bytes)))
    if contract.get("release_id") != manifest.get("release_id"):
        issues.fail("release_id_mismatch", "contract %r, manifest %r"
                    % (contract.get("release_id"), manifest.get("release_id")))
    if not manifest.get("release_id"):
        issues.fail("release_id_missing", "manifest.release_id is required")


def verify_runner_binding(manifest, contract, issues, deps_path=None):
    runner = ((manifest.get("inputs") or {}).get("runner") or {})
    expected = str(runner.get("sha256", ""))
    if not _prepare_training().SHA_RE.match(expected):
        issues.fail("runner_sha256_missing", "manifest.inputs.runner.sha256 is not a sha256")
    else:
        actual = file_sha256(Path(__file__).resolve())
        if expected != actual:
            issues.fail("runner_self_hash_mismatch",
                        "manifest binds runner %s, these bytes are %s" % (expected, actual))
    if runner.get("path") and Path(runner["path"]).name != Path(__file__).name:
        issues.fail("runner_name_mismatch", "manifest names %r, this file is %r"
                    % (runner.get("path"), Path(__file__).name))
    deps_hash = str(runner.get("deps_sha256", ""))
    contract_hash = str(contract.get("deps_sha256", ""))
    if contract_hash and not _prepare_training().SHA_RE.match(contract_hash):
        issues.fail("deps_pin_invalid", "contract.deps_sha256 is not a sha256")
    if deps_hash and contract_hash and deps_hash != contract_hash:
        issues.fail("deps_pin_conflict",
                    "manifest deps %s, contract deps %s" % (deps_hash, contract_hash))
    if not _prepare_training().SHA_RE.match(deps_hash):
        issues.fail("runner_deps_hash_missing",
                    "manifest.inputs.runner.deps_sha256 is not a sha256")
    expected_deps = deps_hash or contract_hash
    path = deps_path or runner.get("deps") or contract.get("deps")
    if not path or not Path(path).exists():
        issues.fail("runner_deps_missing",
                    "deps file %r is required; pass --deps or bind the real path" % path)
        return {"path": str(path) if path else None, "sha256": None}
    actual = file_sha256(path)
    if expected_deps and actual != expected_deps:
        issues.fail("runner_deps_hash_mismatch",
                    "%s bytes differ from the reviewed hash" % path)
    return {"path": str(path), "sha256": actual}


def verify_recipe(manifest, issues):
    recipe = manifest.get("recipe") or {}
    required = _prepare_training().REQUIRED_RECIPE
    for field in required:
        if recipe.get(field) in (None, "", []):
            issues.fail("recipe_missing", "recipe.%s is required" % field)
    for field in ("base_revision", "tokenizer_revision"):
        value = str(recipe.get(field, ""))
        if value and not _prepare_training().COMMIT_RE.match(value):
            issues.fail("recipe_unpinned", "recipe.%s is not a 40-hex commit: %r" % (field, value))
    for field in ("tokenizer_chat_template_sha256", "tokenizer_config_sha256"):
        value = str(recipe.get(field, ""))
        if value and not _prepare_training().SHA_RE.match(value):
            issues.fail("recipe_unpinned",
                        "recipe.%s is required and must be a sha256, found %r" % (field, value))
    base = str(recipe.get("base_revision", ""))
    tokenizer = str(recipe.get("tokenizer_revision", ""))
    if _prepare_training().COMMIT_RE.match(base) and _prepare_training().COMMIT_RE.match(tokenizer) \
            and base != tokenizer:
        issues.fail("tokenizer_revision_unsupported",
                    "the pinned loader takes one revision: base %s, tokenizer %s; "
                    "refuse to ignore the tokenizer pin" % (base, tokenizer))
    if not isinstance(recipe.get("max_seq_length"), int) or recipe.get("max_seq_length", 0) <= 0:
        issues.fail("recipe_max_seq_length", "recipe.max_seq_length must be a positive integer")
    if not isinstance(recipe.get("epochs"), int) or recipe.get("epochs", 0) <= 0:
        issues.fail("recipe_epochs", "recipe.epochs must be a positive integer")
    _prepare_training().validate_artifact_pins(recipe, issues)
    return recipe


def verify_provenance(manifest, issues, review_path=None):
    """A ready string is not provenance: re-check the review file and controls."""
    inputs = manifest.get("inputs") or {}
    review = inputs.get("source_review") or {}
    if not review:
        issues.fail("source_review_missing", "manifest.inputs.source_review is absent")
    else:
        path = review_path or review.get("path")
        if not path or not Path(path).exists():
            issues.fail("source_review_missing",
                        "review file %r does not exist; pass --review" % path)
        else:
            actual = file_sha256(path)
            declared = str(review.get("sha256_bytes", ""))
            if not _prepare_training().SHA_RE.match(declared) or declared != actual:
                issues.fail("source_review_sha256_mismatch",
                            "review bytes %s, manifest %r" % (actual, declared))
            doc = _prepare_training().load_review_artifact(path, issues)
            if doc is not None:
                dataset = inputs.get("dataset") or {}
                split = inputs.get("split") or {}
                recipe = manifest.get("recipe") or {}
                runner = inputs.get("runner") or {}
                expected = {
                    "dataset_sha256": dataset.get("sha256_bytes"),
                    "rows": (dataset.get("row_facts") or {}).get("rows"),
                    "recipe_sha256": inputs.get("recipe_sha256"),
                    "ledger_sha256": split.get("sha256_ledger"),
                    "audit_manifest_sha256": split.get("sha256_audit"),
                    "exposure": split.get("exposure"),
                    "exposure_ids_sha256": split.get("exposure_ids_sha256"),
                    "tokenizer_config_sha256": recipe.get("tokenizer_config_sha256"),
                    "runner_sha256": runner.get("sha256"),
                    "deps_sha256": runner.get("deps_sha256"),
                }
                binds = doc.get("binds") or {}
                for field, value in expected.items():
                    if binds.get(field) != value:
                        issues.fail("source_review_not_bound",
                                    "review binds.%s is %r, manifest %r"
                                    % (field, binds.get(field), value))
    controls = inputs.get("evaluation_controls")
    if not isinstance(controls, list) or not controls:
        issues.fail("protected_inventory_missing",
                    "manifest.inputs.evaluation_controls is empty")
        return
    reserved = 0
    for entry in controls:
        if not isinstance(entry, dict) or not entry.get("name"):
            issues.fail("protected_inventory_invalid", "an evaluation control has no name")
            continue
        role = entry.get("role")
        if role not in ("open", "reserved", "development"):
            issues.fail("protected_inventory_invalid",
                        "%s has role %r" % (entry["name"], role))
        elif role == "reserved":
            reserved += 1
            count = entry.get("checked_hashes")
            if not isinstance(count, int) or count <= 0:
                issues.fail("protected_inventory_invalid",
                            "%s declares no positive checked_hashes" % entry["name"])
            if not entry.get("attested_by"):
                issues.fail("protected_inventory_unattested",
                            "%s has no attested hash list" % entry["name"])
        elif role == "open":
            count = entry.get("checked_questions")
            if not isinstance(count, int) or count <= 0:
                issues.fail("protected_inventory_invalid",
                            "%s declares no positive checked_questions" % entry["name"])
            if entry.get("near_checked") is not True:
                issues.fail("protected_inventory_invalid",
                            "%s was not near-checked" % entry["name"])
        elif role == "development" and entry.get("checked_hashes") is not None:
            issues.fail("protected_inventory_invalid",
                        "%s is a development surface but claims checked hashes"
                        % entry["name"])
    if reserved == 0:
        issues.fail("protected_inventory_missing",
                    "no reserved control with an attested hash list is bound")


def collect_question_texts(row):
    """Every question variant the approved rows carry; never expected/review."""
    texts = set()
    try:
        for text in _prepare_training().messages_questions(row):
            if text.strip():
                texts.add(text)
        fallback = _prepare_training().messages_user_question(row)
        if fallback.strip():
            texts.add(fallback)
    except Exception:
        pass
    for path in ("meta.question", "meta.asked", "meta.turn1_q", "meta.baseline_question"):
        try:
            value = _prepare_training().lookup(row, path)
        except (KeyError, IndexError):
            continue
        if isinstance(value, str) and value.strip():
            texts.add(value)
    meta = row.get("meta") or {}
    for item in meta.get("history") or []:
        if isinstance(item, dict) and isinstance(item.get("question"), str)                 and item["question"].strip():
            texts.add(item["question"])
    return texts


def verify_inventory(contract, manifest, train_rows, validation_rows, validation_block,
                     issues):
    block = contract.get("protected_inventory") or {}
    if not block:
        issues.fail("protected_inventory_unbound",
                    "contract.protected_inventory is required; a summary is not evidence")
        return {}
    inventory_path = block.get("path")
    fragment_path = block.get("fragment_path")
    if not inventory_path or not Path(inventory_path).exists():
        issues.fail("protected_inventory_unbound",
                    "inventory file %r does not exist" % inventory_path)
        return {}
    if not fragment_path or not Path(fragment_path).exists():
        issues.fail("protected_inventory_unbound",
                    "spec fragment %r does not exist" % fragment_path)
        return {}
    inventory_bytes = Path(inventory_path).read_bytes()
    fragment_bytes = Path(fragment_path).read_bytes()
    if sha256_bytes(inventory_bytes) != block.get("sha256"):
        issues.fail("protected_inventory_hash_mismatch",
                    "inventory bytes %s, contract %r"
                    % (sha256_bytes(inventory_bytes), block.get("sha256")))
    if sha256_bytes(fragment_bytes) != block.get("fragment_sha256"):
        issues.fail("protected_inventory_fragment_mismatch",
                    "fragment bytes %s, contract %r"
                    % (sha256_bytes(fragment_bytes), block.get("fragment_sha256")))
    try:
        inventory = json.loads(inventory_bytes.decode("utf-8"))
        receipt_block = block.get("receipt") or {}
        receipt_path = receipt_block.get("path")
        if not receipt_path or not Path(receipt_path).exists():
            issues.fail("source_review_missing",
                        "approved receipt %r does not exist" % receipt_path)
            return {}
        receipt_bytes = Path(receipt_path).read_bytes()
        if sha256_bytes(receipt_bytes) != receipt_block.get("sha256"):
            issues.fail("source_review_receipt_mismatch",
                        "receipt bytes %s, contract %r"
                        % (sha256_bytes(receipt_bytes), receipt_block.get("sha256")))
        receipt = json.loads(receipt_bytes.decode("utf-8"))
    except Exception as exc:
        issues.fail("protected_inventory_invalid", "inventory/receipt: %s" % exc)
        return {}
    if receipt.get("verdict") != "REVIEW_ACCEPTED":
        issues.fail("source_review_not_accepted",
                    "receipt verdict is %r" % receipt.get("verdict"))
    binding = receipt.get("binding") or {}
    opaque = binding.get("opaque_inventory") or {}
    if opaque.get("inventory_sha256") != block.get("sha256"):
        issues.fail("protected_inventory_unbound",
                    "receipt binds inventory %r, contract %r"
                    % (opaque.get("inventory_sha256"), block.get("sha256")))
    if opaque.get("spec_fragment_sha256") != block.get("fragment_sha256"):
        issues.fail("protected_inventory_unbound",
                    "receipt binds fragment %r, contract %r"
                    % (opaque.get("spec_fragment_sha256"), block.get("fragment_sha256")))
    dataset = (manifest.get("inputs") or {}).get("dataset") or {}
    counts = binding.get("counts") or {}
    checks = (
        ("train_sha256", dataset.get("sha256_bytes")),
        ("validation_sha256", validation_block.get("sha256_bytes")),
        ("train_rows", (dataset.get("row_facts") or {}).get("rows")),
        ("validation_rows", validation_block.get("rows")),
    )
    for field, expected in checks:
        if binding.get(field) != expected:
            issues.fail("source_review_not_bound",
                        "receipt binding.%s is %r, manifest %r"
                        % (field, binding.get(field), expected))
    if counts.get("train") != (dataset.get("row_facts") or {}).get("rows")             or counts.get("validation") != validation_block.get("rows"):
        issues.fail("source_review_not_bound",
                    "receipt counts %r do not match the 429/43 package" % counts)
    controls = inventory.get("controls") or []
    by_name = {entry.get("name"): entry for entry in controls if entry.get("name")}
    required = [str(name) for name in block.get("required_controls") or []]
    for name in required:
        if name not in by_name:
            issues.fail("protected_inventory_missing",
                        "required control %r is absent from the inventory" % name)
    union = set()
    for entry in controls:
        for value in (entry.get("union") or {}).get("hashes") or []:
            union.add(value)
        union_block = entry.get("union") or {}
        if union_block.get("hashes") and union_block.get("list_sha256"):
            if sha256_text("\n".join(sorted(union_block["hashes"]))) != union_block["list_sha256"]:
                issues.fail("protected_inventory_corrupt",
                            "%s union list hash does not cover its hashes" % entry.get("name"))
    declared = (manifest.get("inputs") or {}).get("evaluation_controls") or []
    reserved = 0
    for entry in declared:
        if not isinstance(entry, dict):
            continue
        name, role = entry.get("name"), entry.get("role")
        if role != "reserved":
            continue
        reserved += 1
        actual = by_name.get(name)
        if actual is None:
            issues.fail("protected_control_unknown",
                        "declared control %r is absent from the frozen inventory" % name)
            continue
        actual_role = actual.get("role") or (actual.get("entry") or {}).get("role")
        if actual_role != role:
            issues.fail("protected_control_role",
                        "%r inventory role %r, manifest %r"
                        % (name, actual_role, role))
        unique = (actual.get("union") or {}).get("unique")
        if entry.get("checked_hashes") != unique:
            issues.fail("protected_control_population_mismatch",
                        "%r declares %r hashes, inventory %r"
                        % (name, entry.get("checked_hashes"), unique))
        reviewer = ((actual.get("entry") or {}).get("attestation") or {}).get("reviewer")
        if entry.get("attested_by") != reviewer:
            issues.fail("protected_control_unattested",
                        "%r declares %r, inventory attestation %r"
                        % (name, entry.get("attested_by"), reviewer))
    if reserved == 0:
        issues.fail("protected_inventory_missing",
                    "no declared reserved control can be checked against the inventory")
    texts = set()
    for row in list(train_rows) + list(validation_rows):
        texts.update(collect_question_texts(row))
    hashes = {_prepare_training().question_sha256(text) for text in texts}
    overlaps = sorted(hashes & union)
    if overlaps:
        issues.fail("protected_question_overlap",
                    "%d train/validation question hashes overlap the %d-hash protected union"
                    % (len(overlaps), len(union)))
    return {"path": str(inventory_path), "sha256": sha256_bytes(inventory_bytes),
            "fragment_path": str(fragment_path),
            "fragment_sha256": sha256_bytes(fragment_bytes),
            "receipt_path": str(receipt_path),
            "receipt_sha256": sha256_bytes(receipt_bytes),
            "receipt_verdict": receipt.get("verdict"),
            "controls": len(controls), "required_controls": required,
            "union_hashes": len(union), "question_texts": len(texts),
            "question_hashes": len(hashes), "overlaps": len(overlaps)}


def verify_dataset(manifest, path, issues):
    """The byte hash is the proof; the gate already priced every row fact."""
    declared = (manifest.get("inputs") or {}).get("dataset") or {}
    row_facts = declared.get("row_facts") or {}
    if not path or not Path(path).exists():
        issues.fail("dataset_missing", "%r does not exist" % path)
        return None, None
    facts = _prepare_training().file_facts(path)
    if declared.get("sha256_bytes") != facts["sha256_bytes"]:
        issues.fail("dataset_sha256_mismatch", "declared %r, found %s"
                    % (declared.get("sha256_bytes"), facts["sha256_bytes"]))
    rows = read_jsonl(Path(path).read_bytes())
    if row_facts.get("rows") != len(rows):
        issues.fail("dataset_rows_mismatch", "manifest claims %r rows, file has %d"
                    % (row_facts.get("rows"), len(rows)))
    return rows, {"path": str(path), "bytes": facts["bytes"],
                  "sha256_bytes": facts["sha256_bytes"],
                  "sha256_rows": facts["sha256_rows"], "rows": len(rows)}


def unique_message_entry(row, by_id, issues, code, label):
    digest = row_messages_sha256(row)
    matches = [entry for entry in by_id.values()
               if entry.get("messages_sha256") == digest]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        issues.fail(code, "%s messages hash matches %d frozen entries"
                    % (label, len(matches)))
    return None


def resolve_train_entry(row, number, path_index, by_id, dataset_path, issues,
                        train_row_id_path="meta.ledger_id"):
    """Approved id first; line or unique content hash fallback. Never meta.split."""
    try:
        identifier = _prepare_training().lookup(row, train_row_id_path)
    except (KeyError, IndexError):
        identifier = None
    if isinstance(identifier, str) and identifier:
        entry = by_id.get(identifier)
        if entry is None:
            issues.fail("split_row_unknown", "row %d names unknown ledger id %r"
                        % (number, identifier))
            return None
        if entry.get("messages_sha256") != row_messages_sha256(row):
            issues.fail("split_row_id_content_mismatch",
                        "row %d id %r does not carry the frozen messages" % (number, identifier))
            return None
        return entry
    lookup = getattr(_prepare_training(), "_ledger_lookup", None)
    line_entry = lookup(path_index, dataset_path, number) if lookup else None
    if line_entry is not None \
            and line_entry.get("messages_sha256") == row_messages_sha256(row):
        return line_entry
    entry = unique_message_entry(row, by_id, issues, "split_row_ambiguous",
                                 "train row %d" % number)
    if entry is not None:
        return entry
    if line_entry is not None:
        issues.fail("split_row_hash_mismatch",
                    "row %d (source line %d) does not carry the frozen messages"
                    % (number, number))
    return None


def verify_frozen_split(manifest, rows, ledger_path, audit_path, issues,
                        train_row_id_path="meta.ledger_id"):
    split = (manifest.get("inputs") or {}).get("split") or {}
    facts = {}
    if not ledger_path or not Path(ledger_path).exists():
        issues.fail("split_ledger_missing", "%r does not exist" % ledger_path)
        return None, {}
    if not audit_path or not Path(audit_path).exists():
        issues.fail("split_audit_missing", "%r does not exist" % audit_path)
        return None, {}
    ledger_bytes = Path(ledger_path).read_bytes()
    audit_bytes = Path(audit_path).read_bytes()
    if split.get("sha256_ledger") != sha256_bytes(ledger_bytes):
        issues.fail("split_ledger_sha256_mismatch", "ledger bytes changed")
    if split.get("sha256_audit") != sha256_bytes(audit_bytes):
        issues.fail("split_audit_sha256_mismatch", "audit manifest bytes changed")
    try:
        audit = json.loads(audit_bytes.decode("utf-8"))
    except Exception as exc:
        issues.fail("split_audit_invalid", "%s: %s" % (audit_path, exc))
        return None, {}
    if audit.get("audit") != "training_audit":
        issues.fail("split_audit_wrong_tool", "manifest audit field is %r" % audit.get("audit"))
    config = audit.get("config") or {}
    if config.get("random_assignment") != "none":
        issues.fail("split_random_assignment", "the frozen split must not be random")
    if "component" not in str(config.get("split_policy", "")).lower():
        issues.fail("split_policy_not_component", "split policy is %r"
                    % str(config.get("split_policy"))[:80])

    ledger_index = getattr(_prepare_training(), "_ledger_index", None)
    ledger_lookup = getattr(_prepare_training(), "_ledger_lookup", None)
    if ledger_index is None or ledger_lookup is None:
        issues.fail("prep_api_missing",
                    "prepare_training no longer exposes the ledger index/lookup helpers")
        return None, {}
    ledger = list(ledger_index(ledger_path, issues).values())
    ids = [entry.get("id") for entry in ledger]
    if len(ids) != len(set(ids)):
        issues.fail("split_ledger_duplicate_id", "the ledger repeats an id")

    dataset_path = (manifest.get("inputs") or {}).get("dataset", {}).get("path")
    path_index = {(entry.get("source_path"), entry.get("line")): entry
                  for entry in ledger}
    by_id = {entry.get("id"): entry for entry in ledger}
    resolved_components, resolved_families = set(), set()
    for number, row in enumerate(rows, 1):
        entry = resolve_train_entry(row, number, path_index, by_id, dataset_path, issues,
                                     train_row_id_path)
        if entry is None:
            issues.fail("split_rows_missing", "row %d is absent from the ledger" % number)
            continue
        if entry.get("split") != "train":
            issues.fail("split_rows_not_train", "row %d is %r" % (number, entry.get("split")))
        if entry.get("train_ready") is not True:
            issues.fail("split_rows_not_train_ready", "row %d is train_ready=false" % number)
        if entry.get("role") != split.get("role"):
            issues.fail("split_role_mismatch", "row %d role %r, expected %r"
                        % (number, entry.get("role"), split.get("role")))
        if entry.get("messages_sha256") != row_messages_sha256(row):
            issues.fail("split_row_hash_mismatch",
                        "row %d messages hash differs from the frozen ledger" % number)
        if entry.get("component_id"):
            resolved_components.add(entry["component_id"])
        if entry.get("family_id"):
            resolved_families.add(entry["family_id"])
    facts.update({"ledger": str(ledger_path), "audit": str(audit_path),
                  "sha256_ledger": sha256_bytes(ledger_bytes),
                  "sha256_audit": sha256_bytes(audit_bytes),
                  "train_components": resolved_components,
                  "train_families": resolved_families})
    return ledger, facts


def user_prompt_text(row):
    return next((str(message.get("content", "")) for message in row.get("messages", [])
                 if isinstance(message, dict) and message.get("role") == "user"), "")


def target_text(row):
    messages = row.get("messages") or []
    return str(messages[-1].get("content", "")) if messages else ""


def check_validation_hashes(row, entry, identifier, issues):
    """The id is not the content: hash the actual row against the frozen ledger."""
    expected = entry.get("messages_sha256")
    if not _prepare_training().SHA_RE.match(str(expected or "")):
        issues.fail("validation_ledger_hash_missing",
                    "%r has no approved messages_sha256 in the frozen ledger" % identifier)
    elif row_messages_sha256(row) != expected:
        issues.fail("validation_row_hash_mismatch",
                    "%r messages differ from the frozen ledger" % identifier)
    for field, code, actual in (
            ("user_prompt_sha256", "validation_user_hash_mismatch",
             sha256_text(user_prompt_text(row))),
            ("target_sha256", "validation_target_hash_mismatch",
             sha256_text(target_text(row)))):
        expected = entry.get(field)
        if expected is None:
            continue
        if not _prepare_training().SHA_RE.match(str(expected)):
            issues.fail("validation_ledger_hash_missing",
                        "%r has an invalid %s" % (identifier, field))
        elif actual != expected:
            issues.fail(code, "%r %s differs from the frozen ledger" % (identifier, field))


def verify_validation(block, ledger, audit_facts, issues, validation_path=None):
    if not block:
        issues.fail("validation_missing",
                    "neither manifest.inputs.validation nor contract.validation is present")
        return [], {}
    if block.get("role") != "dev-internal":
        issues.fail("validation_role", "validation.role must be 'dev-internal', found %r"
                    % block.get("role"))
    path = validation_path or block.get("path")
    if not path or not Path(path).exists():
        issues.fail("validation_missing", "validation file %r does not exist" % path)
        return [], {}
    data = Path(path).read_bytes()
    if block.get("sha256_bytes") != sha256_bytes(data):
        issues.fail("validation_sha256_mismatch", "declared %r, found %s"
                    % (block.get("sha256_bytes"), sha256_bytes(data)))
    rows = read_jsonl(data)
    if block.get("rows") != len(rows):
        issues.fail("validation_rows_mismatch", "declared %r, file has %d"
                    % (block.get("rows"), len(rows)))
    if block.get("split_manifest_sha256") != audit_facts.get("sha256_audit"):
        issues.fail("validation_manifest_pin_mismatch",
                    "validation.split_manifest_sha256 is %r, audit is %r"
                    % (block.get("split_manifest_sha256"), audit_facts.get("sha256_audit")))

    id_path = str(block.get("row_id_path") or "meta.ledger_id")
    lookup = _prepare_training().lookup
    by_id = {entry.get("id"): entry for entry in ledger}
    ids, families, components = [], set(), set()
    for index, row in enumerate(rows):
        identifier = None
        try:
            value = lookup(row, id_path)
            if isinstance(value, str) and value:
                identifier = value
        except (KeyError, IndexError):
            identifier = None
        entry = by_id.get(identifier) if identifier else None
        if identifier and entry is None:
            issues.fail("validation_row_unknown",
                        "row %d names unknown ledger id %r" % (index, identifier))
            continue
        if entry is not None and entry.get("messages_sha256") != row_messages_sha256(row):
            issues.fail("validation_row_hash_mismatch",
                        "row %d id %r does not carry the frozen messages" % (index, identifier))
            continue
        if entry is None:
            entry = unique_message_entry(row, by_id, issues, "validation_row_ambiguous",
                                         "validation row %d" % index)
            if entry is None:
                issues.fail("validation_row_hash_missing",
                            "row %d resolves to no unique frozen entry" % index)
                continue
        identifiers = entry.get("id")
        ids.append(identifiers)
        if entry.get("split") != "dev":
            issues.fail("validation_split_not_dev",
                        "%r is %r in the ledger, not dev" % (identifiers, entry.get("split")))
        if not entry.get("family_id") or not entry.get("component_id"):
            issues.fail("validation_row_unkeyed",
                        "%r has no family_id/component_id in the ledger" % identifiers)
        check_validation_hashes(row, entry, identifiers, issues)
        families.add(entry.get("family_id"))
        components.add(entry.get("component_id"))
    if len(set(ids)) != len(ids):
        issues.fail("validation_row_duplicate", "the validation file repeats a ledger id")
    if sorted_hash(ids) != block.get("ledger_ids_sha256"):
        issues.fail("validation_ids_mismatch",
                    "validation.ledger_ids_sha256 does not match the resolved ids")
    if sorted_hash(families) != block.get("family_ids_sha256"):
        issues.fail("validation_family_ids_mismatch",
                    "contract family digest does not match the ledger")
    if sorted_hash(components) != block.get("component_ids_sha256"):
        issues.fail("validation_component_ids_mismatch",
                    "contract component digest does not match the ledger")

    by_component = {}
    for entry in ledger:
        by_component.setdefault(entry.get("component_id"), set()).add(entry.get("id"))
    for component in components:
        members = by_component.get(component) or set()
        if not members <= set(ids):
            issues.fail("validation_component_partial",
                        "component %r has %d ledger rows, the validation file holds %d"
                        % (component, len(members), len(members & set(ids))))

    if components & set(audit_facts.get("train_components") or []):
        issues.fail("split_component_bridge", "a component sits in both train and validation")
    if families & set(audit_facts.get("train_families") or []):
        issues.fail("split_family_bridge", "a family sits in both train and validation")

    for label, key in (("component", "component_id"), ("family", "family_id")):
        groups = {}
        for entry in ledger:
            groups.setdefault(entry.get(key), set()).add(entry.get("split"))
        straddling = [name for name, splits in groups.items()
                      if name and {"train", "dev"} <= splits]
        if straddling:
            issues.fail("split_%s_straddle" % label,
                        "%d %s group(s) hold both train and dev rows"
                        % (len(straddling), label))

    return rows, {"path": str(path), "sha256_bytes": sha256_bytes(data),
                  "rows": len(rows), "role": block.get("role"),
                  "ids": ids, "families": sorted(families),
                  "components": sorted(components)}


def verify_contract_model(contract, recipe, issues):
    model = contract.get("model") or {}
    pad = model.get("pad_token")
    if not isinstance(pad, str) or not pad:
        issues.fail("contract_pad_token_missing", "contract.model.pad_token is required")
    if not isinstance(model.get("thinking_scaffold"), bool):
        issues.fail("contract_thinking_scaffold", "contract.model.thinking_scaffold must be a bool")
    export = contract.get("export") or {}
    if export.get("gguf") != EXPORT_QUANT:
        issues.fail("contract_export_mismatch", "contract.export.gguf must be %r" % EXPORT_QUANT)
    if export.get("merged_16bit") is not True:
        issues.fail("contract_export_mismatch", "contract.export.merged_16bit must be true")
    if model.get("base_model") and model["base_model"] != recipe.get("base_model"):
        issues.fail("contract_base_model_mismatch", "contract %r, manifest %r"
                    % (model["base_model"], recipe.get("base_model")))


def load_package(manifest_path, contract_path, *, dataset=None, ledger=None,
                 audit=None, validation=None, deps=None, review=None):
    package = Package()
    issues = package.issues
    manifest, manifest_bytes = read_json_file(manifest_path, issues, "manifest")
    contract, contract_bytes = read_json_file(contract_path, issues, "contract")
    package.manifest = manifest
    package.contract = contract
    package.manifest_sha256 = sha256_bytes(manifest_bytes) if manifest_bytes else None
    package.contract_sha256 = sha256_bytes(contract_bytes) if contract_bytes else None
    if manifest is None or contract is None:
        return package

    verify_header(manifest, contract, manifest_bytes, contract_bytes, issues)
    deps_facts = verify_runner_binding(manifest, contract, issues, deps)
    recipe = verify_recipe(manifest, issues)
    verify_provenance(manifest, issues, review)
    verify_contract_model(contract, recipe, issues)

    declared_path = ((manifest.get("inputs") or {}).get("dataset") or {}).get("path")
    rows, dataset_facts = verify_dataset(manifest, dataset or declared_path, issues)
    package.rows = rows or []
    split = (manifest.get("inputs") or {}).get("split") or {}
    ledger_rows, split_facts = verify_frozen_split(
        manifest, package.rows, ledger or split.get("ledger"),
        audit or split.get("audit"), issues,
        contract.get("train_row_id_path") or "meta.ledger_id")
    package.ledger = ledger_rows or []
    manifest_block = (manifest.get("inputs") or {}).get("validation") or {}
    contract_block = contract.get("validation") or {}
    if manifest_block and contract_block and manifest_block != contract_block:
        issues.fail("validation_block_conflict",
                    "the manifest and the contract carry different validation blocks")
    package.validation_block = manifest_block or contract_block
    validation_rows, validation_facts = ([], {})
    if package.ledger:
        validation_rows, validation_facts = verify_validation(
            package.validation_block, package.ledger, split_facts, issues, validation)
    package.validation_rows = validation_rows
    inventory_facts = verify_inventory(contract, manifest, package.rows, validation_rows,
                                       package.validation_block, issues)
    package.facts = {"dataset": dataset_facts, "split": {
        key: value for key, value in split_facts.items()
        if key not in ("train_components", "train_families")},
        "validation": validation_facts, "recipe": recipe, "deps": deps_facts,
        "inventory": inventory_facts,
        "controls_sha256": sha256_text(canonical_json(
            (manifest.get("inputs") or {}).get("evaluation_controls"))),
        "manifest_sha256": package.manifest_sha256,
        "contract_sha256": package.contract_sha256,
        "runner_sha256": file_sha256(Path(__file__).resolve())}
    return package


# --------------------------------------------------------------- masking


def render(tokenizer, messages, add_generation_prompt, thinking=None):
    kwargs = {"tokenize": False, "add_generation_prompt": add_generation_prompt}
    if thinking is not None:
        kwargs["enable_thinking"] = thinking
    return tokenizer.apply_chat_template(messages, **kwargs)


def token_ids(tokenizer, text):
    encoded = tokenizer(text, add_special_tokens=False)
    if isinstance(encoded, dict):
        ids = encoded.get("input_ids")
    else:
        ids = getattr(encoded, "input_ids", None)
    if ids is None:
        raise ValueError("tokenizer returned no input_ids")
    return list(ids)


def decode_ids(tokenizer, ids):
    try:
        return tokenizer.decode(ids, skip_special_tokens=False,
                                clean_up_tokenization_spaces=False)
    except TypeError:
        return tokenizer.decode(ids, skip_special_tokens=False)


def verify_tokenizer_sanity(tokenizer, issues):
    """Ordinary text must tokenize to non-empty, distinct ids and decode back.

    transformers 5.17.0 builds a Qwen2Tokenizer with `vocab_size=1` and an
    empty `"ping"` encoding, without raising, when the vocabulary files are
    missing. Nothing downstream can tell that tokenizer from a real one, so
    refuse here, before stop checks or training.
    """
    measured = {"texts": len(TOKENIZER_SANITY_TEXTS), "encodings": []}
    encodings = []
    for number, text in enumerate(TOKENIZER_SANITY_TEXTS, 1):
        try:
            ids = token_ids(tokenizer, text)
        except Exception as exc:
            issues.fail("tokenizer_dead",
                        "ordinary text %d did not tokenize: %s" % (number, exc))
            return measured
        if not isinstance(ids, list) or not ids:
            issues.fail("tokenizer_dead",
                        "ordinary text %d tokenized to %r ids"
                        % (number, len(ids) if isinstance(ids, list) else ids))
            return measured
        try:
            decoded = decode_ids(tokenizer, ids)
        except Exception as exc:
            issues.fail("tokenizer_dead",
                        "ordinary text %d did not decode: %s" % (number, exc))
            return measured
        if not str(decoded).strip():
            issues.fail("tokenizer_dead",
                        "ordinary text %d decoded to empty text" % number)
            return measured
        encodings.append(ids)
        measured["encodings"].append({"text": number, "tokens": len(ids),
                                      "decoded_chars": len(str(decoded))})
    if encodings[0] == encodings[1]:
        issues.fail("tokenizer_dead",
                    "two different ordinary sentences produced the same ids")
    measured["distinct"] = encodings[0] != encodings[1]
    return measured


def measure_rows(rows, tokenizer, recipe, issues, label, require_families=None):
    """Tokenize and mask every row; no truncation, final assistant turn only."""
    eos = str(recipe["assistant_eos"])
    response_part = str(recipe["response_part"])
    max_length = int(recipe["max_seq_length"])
    eos_id = getattr(tokenizer, "eos_token_id", None)
    if not isinstance(eos_id, int):
        issues.fail("tokenizer_eos_id_missing", "tokenizer.eos_token_id is not an integer")
        return None

    total = prompty = prior_rows = eos_total = 0
    family_rows, family_eos = {}, {}
    eos_seen = {}
    lengths, scaffolds, tokenized = [], set(), []
    samples, sample_families = [], set()
    for index, row in enumerate(rows):
        messages = row.get("messages")
        if not isinstance(messages, list) or not messages \
                or not isinstance(messages[-1], dict) \
                or messages[-1].get("role") != "assistant":
            issues.fail("row_schema_invalid", "%s row %d does not end in an assistant turn"
                        % (label, index))
            continue
        label_text = str(messages[-1].get("content", ""))
        if not label_text.strip():
            issues.fail("row_label_empty", "%s row %d has an empty label" % (label, index))
            continue
        if eos in label_text or "<|im_start|>" in label_text:
            issues.fail("row_label_special_token",
                        "%s row %d label carries the assistant EOS or a turn marker"
                        % (label, index))
            continue
        try:
            prefix_text = render(tokenizer, messages[:-1], False)
            full_text = render(tokenizer, messages, False)
        except Exception as exc:
            issues.fail("template_render_failed", "%s row %d: %s" % (label, index, exc))
            continue
        tail = full_text[len(prefix_text):] if full_text.startswith(prefix_text) else ""
        expected = label_text + eos + "\n"
        if not tail.startswith(response_part) or not tail.endswith(expected):
            issues.fail("row_template_shape",
                        "%s row %d: render is not prefix + assistant turn + EOS"
                        % (label, index))
            continue
        scaffold = tail[len(response_part):len(tail) - len(expected)]
        if eos in scaffold or "<|im_start|>" in scaffold:
            issues.fail("row_scaffold_special_token",
                        "%s row %d: the assistant prefix carries a second EOS or turn marker"
                        % (label, index))
            continue
        scaffolds.add(sha256_text(scaffold))
        try:
            prompt_ids = token_ids(tokenizer, prefix_text)
            full_ids = token_ids(tokenizer, full_text)
        except Exception as exc:
            issues.fail("tokenize_failed", "%s row %d: %s" % (label, index, exc))
            continue
        if full_ids[:len(prompt_ids)] != prompt_ids or len(full_ids) <= len(prompt_ids):
            issues.fail("row_token_boundary",
                        "%s row %d: the prompt tokenization is not a strict prefix; tokens "
                        "merge across the assistant boundary" % (label, index))
            continue
        lengths.append(len(full_ids))
        if len(full_ids) > max_length:
            issues.fail("row_too_long",
                        "%s row %d is %d tokens, max_seq_length is %d; refusing to truncate"
                        % (label, index, len(full_ids), max_length))
            continue
        supervised = full_ids[len(prompt_ids):]
        occurrences = sum(1 for token in supervised if token == eos_id)
        if occurrences != 1:
            issues.fail("row_eos_count",
                        "%s row %d supervises %d copies of the assistant EOS"
                        % (label, index, occurrences))
            continue
        labels = [-100] * len(prompt_ids) + supervised
        family = label_family(row)
        family_rows[family] = family_rows.get(family, 0) + 1
        family_eos[family] = family_eos.get(family, 0) + 1
        eos_seen.setdefault(family, set()).add(occurrences)
        total += len(supervised)
        eos_total += occurrences
        prompty += sum(1 for token in labels[:len(prompt_ids)] if token != -100)
        prior = sum(1 for message in messages[:-1]
                    if isinstance(message, dict) and message.get("role") == "assistant")
        prior_rows += 1 if prior else 0
        tokenized.append({"row_index": index, "input_ids": full_ids, "labels": labels,
                          "family": family})
        if family not in sample_families:
            sample_families.add(family)
            samples.append({"row_index": index, "family": family,
                            "supervised": supervised, "tail": tail})

    if prompty:
        issues.fail("mask_prompt_supervised",
                    "%s: %d prompt tokens are supervised" % (label, prompty))
    if len(scaffolds) > 1:
        issues.fail("row_scaffold_varies",
                    "%s: %d different assistant prefixes across rows" % (label, len(scaffolds)))
    if require_families is not None and family_rows != require_families:
        issues.fail("mask_family_mismatch", "measured %r, manifest %r"
                    % (family_rows, require_families))
    eos_map = {family: (1 if values == {1} else 0)
               for family, values in eos_seen.items()}
    spot_checks = []
    for sample in samples:
        try:
            decoded = decode_ids(tokenizer, sample["supervised"])
        except Exception:
            decoded = None
        spot_checks.append({"row_index": sample["row_index"], "family": sample["family"],
                            "supervised_equals_label": decoded == sample["tail"]})
    ordered = sorted(lengths)
    return {
        "rows_checked": len(rows), "mask_rows_checked": len(tokenized),
        "max_tokens": max(lengths) if lengths else 0,
        "p50_tokens": ordered[len(ordered) // 2] if ordered else 0,
        "p90_tokens": ordered[int(0.9 * (len(ordered) - 1))] if ordered else 0,
        "truncated_rows": 0,
        "assistant_label_tokens": total,
        "user_system_supervised_tokens": prompty,
        "prior_assistant_supervised_tokens": 0,
        "prior_assistant_rows": prior_rows,
        "eos_in_supervised": eos_map,
        "eos_total": eos_total,
        "family_rows": family_rows, "family_eos_rows": family_eos,
        "spot_checks": spot_checks,
        "scaffold_sha256": sorted(scaffolds),
        "method": "prefix render (messages[:-1]) is a verified token prefix; labels are "
                  "-100 before it and full ids after it; the final assistant turn only",
        "tokenized": tokenized,
        "row_count": len(rows),
    }


# --------------------------------------------------------------- identity


def verify_identity(tokenizer, recipe, model_conf, resolved, issues):
    """Prove the loaded objects are the pinned public artifacts."""
    measured = {}
    template = getattr(tokenizer, "chat_template", None)
    measured["chat_template_sha256"] = sha256_text(template or "")
    expected_template = str(recipe.get("tokenizer_chat_template_sha256", ""))
    if measured["chat_template_sha256"] != expected_template:
        issues.fail("tokenizer_template_mismatch",
                    "loaded template %s, manifest %s"
                    % (measured["chat_template_sha256"], expected_template))
    name = str(getattr(tokenizer, "name_or_path", ""))
    measured["name_or_path"] = name
    cache_marker = "models--" + str(recipe.get("base_model", "")).replace("/", "--")
    if not (name == recipe.get("base_model") or name.endswith(str(recipe.get("base_model")))
            or cache_marker in name):
        issues.fail("tokenizer_name_mismatch", "%r is not %r" % (name, recipe.get("base_model")))
    measured["eos_token"] = getattr(tokenizer, "eos_token", None)
    if measured["eos_token"] != recipe.get("assistant_eos"):
        issues.fail("tokenizer_eos_mismatch", "loaded %r, manifest %r"
                    % (measured["eos_token"], recipe.get("assistant_eos")))
    pad_token = getattr(tokenizer, "pad_token", None)
    pad_id = getattr(tokenizer, "pad_token_id", None)
    measured.update({"pad_token": pad_token, "pad_token_id": pad_id})
    if pad_token != model_conf.get("pad_token"):
        issues.fail("pad_token_mismatch", "loaded %r, contract %r"
                    % (pad_token, model_conf.get("pad_token")))
    if not isinstance(pad_id, int) or pad_id == 0:
        issues.fail("pad_token_zero", "pad_token_id is %r; token 0 is not a safe pad" % pad_id)
    elif pad_id == getattr(tokenizer, "eos_token_id", None):
        issues.fail("pad_token_equals_eos", "pad_token_id equals eos_token_id")

    commit = resolved.get("commit")
    measured["commit"] = commit
    measured["loader_commit_hash"] = commit or None
    measured["commit_field_present"] = resolved.get("commit_field_present")
    proof = resolved.get("artifact_proof") or {}
    snapshot_path = proof.get("snapshot_path")
    loader_input = resolved.get("loader_input")
    proof_ok = bool(proof.get("status") == "verified" and snapshot_path
                    and same_real_path(loader_input, snapshot_path))
    measured["snapshot_path"] = snapshot_path
    measured["snapshot_revision"] = proof.get("resolved_revision") or proof.get("snapshot_revision")
    measured["snapshot_files"] = {name: item.get("sha256")
                                  for name, item in (proof.get("files") or {}).items()}
    measured["snapshot_used_as_loader_input"] = proof_ok
    measured["loader_input"] = loader_input
    measured["loader_input_argument"] = resolved.get("loader_input_argument")
    measured["weights_index_sha256"] = resolved.get("weights_index_sha256")
    measured["weights_index_shards"] = (proof.get("index") or {}).get("shards")
    expected_index = str(recipe.get("weights_index_sha256") or "") or None
    if measured["weights_index_sha256"] != expected_index:
        issues.fail("weights_index_hash_mismatch",
                    "measured index %r, pin %r"
                    % (measured["weights_index_sha256"], expected_index))
    if not proof_ok:
        issues.fail("base_artifact_unverified",
                    "no verified config+weights snapshot was the loader input")
    if commit:
        if commit != recipe.get("base_revision"):
            issues.fail("base_revision_mismatch", "resolved %r, manifest %r"
                        % (commit, recipe.get("base_revision")))
    elif proof_ok:
        issues.note("loader_commit_hash_absent",
                    "model.config._commit_hash is empty; revision is proven by the "
                    "pinned config+weight sha256 set used as the loader input")
    else:
        issues.fail("base_revision_unresolved",
                    "the loader recorded no resolved commit and no artifact proof stands in")
    snapshot = resolved.get("tokenizer_revision")
    measured["tokenizer_revision"] = snapshot
    if str(recipe.get("base_revision")) != str(recipe.get("tokenizer_revision")):
        issues.fail("tokenizer_revision_unsupported",
                    "the pinned loader takes one revision: base %r, tokenizer %r"
                    % (recipe.get("base_revision"), recipe.get("tokenizer_revision")))
    if snapshot != recipe.get("tokenizer_revision"):
        issues.fail("resolved_revision_mismatch", "cached tokenizer snapshot %r, approved %r"
                    % (snapshot, recipe.get("tokenizer_revision")))
    config_revision = resolved.get("config_revision")
    measured["config_revision"] = config_revision
    if config_revision != recipe.get("base_revision"):
        issues.fail("resolved_config_revision", "cached config snapshot %r, model pin %r"
                    % (config_revision, recipe.get("base_revision")))
    measured["tokenizer_config_sha256"] = resolved.get("tokenizer_config_sha256")
    if measured["tokenizer_config_sha256"] != recipe.get("tokenizer_config_sha256"):
        issues.fail("tokenizer_config_hash_mismatch",
                    "actual file %r, manifest %r"
                    % (measured["tokenizer_config_sha256"],
                       recipe.get("tokenizer_config_sha256")))
    measured["tokenizer_config_path"] = resolved.get("tokenizer_config_path")
    expected_assets = _tokenizer_assets(recipe)
    measured["tokenizer_assets_sha256"] = resolved.get("tokenizer_assets_sha256") or {}
    measured["tokenizer_assets_expected_sha256"] = expected_assets
    if not expected_assets:
        issues.fail("tokenizer_assets_pin_missing",
                    "recipe.tokenizer_assets_sha256 is required to verify the "
                    "tokenizer vocabulary files")
    elif measured["tokenizer_assets_sha256"] != expected_assets:
        issues.fail("tokenizer_asset_hash_mismatch",
                    "actual %r, manifest %r"
                    % (sorted(measured["tokenizer_assets_sha256"]),
                       sorted(expected_assets)))
    measured["config_path"] = resolved.get("config_path")
    measured["config_sha256"] = resolved.get("config_sha256")
    expected_config = str(recipe.get("config_sha256") or "")
    if not expected_config:
        issues.fail("model_config_pin_missing",
                    "recipe.config_sha256 is required to verify the base config")
    elif measured["config_sha256"] != expected_config:
        issues.fail("model_config_hash_mismatch", "actual %r, manifest %r"
                    % (measured["config_sha256"], expected_config))
    expected_weights = _pinned_weights(recipe)
    measured["weights_sha256"] = resolved.get("weights_sha256") or {}
    if not expected_weights:
        issues.fail("base_weights_pin_missing",
                    "recipe.weights_sha256 is required to verify every weight file")
    elif measured["weights_sha256"] != expected_weights:
        issues.fail("base_weights_hash_mismatch",
                    "actual %r, manifest %r"
                    % (measured["weights_sha256"], expected_weights))

    measured["tokenization_sanity"] = verify_tokenizer_sanity(tokenizer, issues)
    probe = [{"role": "user", "content": "ping"}]
    try:
        open_render = render(tokenizer, probe, True, thinking=False)
        think_render = render(tokenizer, probe, True, thinking=True)
    except TypeError as exc:
        issues.fail("template_kwarg_unsupported",
                    "apply_chat_template rejected enable_thinking: %s" % exc)
        return measured
    if model_conf.get("thinking_scaffold"):
        if "</think>" not in open_render:
            issues.fail("template_thinking_missing",
                        "thinking_scaffold is required but the closed scaffold is absent")
        if open_render == think_render:
            issues.fail("template_thinking_unsupported",
                        "enable_thinking changes nothing; the template does not honor it")
    measured["thinking_on_sha256"] = sha256_text(think_render)
    measured["thinking_off_sha256"] = sha256_text(open_render)
    return measured


def resolve_cached(repo, filename, revision, issues, *, stream=False, allow_download=False):
    """Hash the actual cached HF file; no network unless a setup stage opted in."""
    try:
        from huggingface_hub import hf_hub_download
    except Exception as exc:
        issues.fail("hub_missing", "huggingface_hub is unavailable: %s" % exc)
        return None
    kwargs = {"repo_id": repo, "filename": filename, "revision": revision}
    downloaded = False
    try:
        path = Path(hf_hub_download(**kwargs, local_files_only=True))
    except Exception as exc:
        if not allow_download:
            issues.fail("hub_file_missing",
                        "%s at %s is not in the offline cache: %s" % (filename, revision, exc))
            return None
        try:
            path = Path(hf_hub_download(**kwargs, local_files_only=False))
            downloaded = True
        except Exception as retry:
            issues.fail("hub_file_missing",
                        "%s at %s is not cached and the pinned fetch failed: %s"
                        % (filename, revision, retry))
            return None
    resolved = path.parent.name
    if resolved != revision:
        issues.fail("hub_snapshot_mismatch",
                    "%s resolved under %r, not the pinned %r" % (filename, resolved, revision))
    if stream:
        digest, size = stream_file_sha256(path)
    else:
        digest, size = file_sha256(path), path.stat().st_size
    return {"sha256": digest, "path": str(path), "revision": resolved,
            "bytes": size, "downloaded": downloaded}


def _pinned_weights(recipe):
    weights = recipe.get("weights_sha256")
    if not isinstance(weights, dict) or not weights:
        return {}
    return {str(name): str(digest) for name, digest in weights.items()}


def _tokenizer_assets(recipe):
    assets = recipe.get("tokenizer_assets_sha256")
    if not isinstance(assets, dict) or not assets:
        return {}
    return {str(name): str(digest) for name, digest in assets.items()}


def resolve_snapshot(recipe, issues, allow_download=False, on_progress=None):
    """Prove the pinned base bytes before the loader can see them.

    Returns an artifact proof that is also the identity record. `status` is
    `verified` only when every pin matched; the loader refuses anything else.
    `on_progress(partial_proof)` runs after each file so a refusal or an
    unexpected read error still leaves the measured bytes on disk.
    """
    start = len(issues.failures)
    requested = {"base_model": recipe.get("base_model"),
                 "base_revision": recipe.get("base_revision"),
                 "tokenizer_revision": recipe.get("tokenizer_revision")}
    config_pin = str(recipe.get("config_sha256") or "")
    weights = _pinned_weights(recipe)
    assets = _tokenizer_assets(recipe)
    index_pin = str(recipe.get("weights_index_sha256") or "")
    proof = {"status": "failed", "requested": requested,
             "pins": {"config_sha256": config_pin or None,
                      "weights_sha256": weights,
                      "tokenizer_assets_sha256": assets,
                      "weights_index_sha256": index_pin or None},
             "files": {}, "snapshot_path": None, "snapshot_revision": None,
             "index": None}

    def report():
        if on_progress is not None:
            on_progress(proof)

    if not config_pin:
        issues.fail("model_config_pin_missing",
                    "recipe.config_sha256 is required to verify the base config")
    if not weights:
        issues.fail("base_weights_pin_missing",
                    "recipe.weights_sha256 is required to verify every weight file")
    unsafe = [name for name in weights if not _prepare_training().safe_artifact_name(name)]
    if unsafe:
        issues.fail("weights_pin_path_invalid",
                    "weight pins must be plain file names: %s" % ", ".join(sorted(unsafe)))
        report()
        return proof
    unknown = [name for name in assets
               if not _prepare_training().safe_artifact_name(name)
               or name not in _prepare_training().TOKENIZER_ASSET_NAMES]
    if not assets:
        issues.fail("tokenizer_assets_pin_missing",
                    "recipe.tokenizer_assets_sha256 is required: a pinned tokenizer "
                    "without its vocabulary files loads as a dead tokenizer")
        report()
        return proof
    if unknown:
        issues.fail("tokenizer_asset_pin_path_invalid",
                    "tokenizer asset pins must be plain tokenizer file names: %s"
                    % ", ".join(sorted(unknown)))
        report()
        return proof
    bad_assets = [name for name, digest in sorted(assets.items())
                  if not _prepare_training().SHA_RE.match(digest)]
    if bad_assets:
        issues.fail("tokenizer_asset_pin_invalid",
                    "tokenizer asset pins must be sha256: %s" % ", ".join(bad_assets))
        report()
        return proof
    groups = _prepare_training().TOKENIZER_REPRESENTATION_GROUPS
    if not any(set(group) <= set(assets) for group in groups):
        issues.fail("tokenizer_assets_representation_missing",
                    "the tokenizer asset map names no vocabulary representation: "
                    "tokenizer.json, or tokenizer.model, or vocab.json with merges.txt")
        report()
        return proof
    if str(recipe.get("base_revision")) != str(recipe.get("tokenizer_revision")):
        issues.fail("tokenizer_revision_unsupported",
                    "the pinned loader takes one revision: base %r, tokenizer %r"
                    % (recipe.get("base_revision"), recipe.get("tokenizer_revision")))
        report()
        return proof
    index_ok = True
    if weights:
        required_index = _prepare_training().index_pin_required(weights)
        if not index_pin:
            if required_index:
                issues.fail("weights_index_pin_missing",
                            "the pinned weight set is not exactly the canonical "
                            "model.safetensors; recipe.weights_index_sha256 is required")
                index_ok = False
        elif not _prepare_training().SHA_RE.match(index_pin):
            issues.fail("weights_index_pin_invalid",
                        "recipe.weights_index_sha256 must be a sha256, found %r"
                        % (index_pin,))
            index_ok = False
    if not index_ok:
        report()
        return proof
    if not config_pin and not weights:
        report()
        return proof
    report()

    needed = []
    if config_pin:
        needed.append(("config.json", config_pin, False, "model_config_hash_mismatch"))
    needed.append(("tokenizer_config.json", str(recipe.get("tokenizer_config_sha256") or ""),
                   False, "tokenizer_config_hash_mismatch"))
    if index_pin and weights:
        needed.append((_prepare_training().WEIGHTS_INDEX_NAME, index_pin, False,
                       "weights_index_hash_mismatch"))
    needed.extend((name, digest, True, "base_weights_hash_mismatch")
                  for name, digest in sorted(weights.items()))
    needed.extend((name, digest, False, "tokenizer_asset_hash_mismatch")
                  for name, digest in sorted(assets.items()))

    parents = set()
    for name, expected, is_weight, code in needed:
        revision = (recipe["tokenizer_revision"] if name in assets
                    else recipe["base_revision"])
        entry = resolve_cached(recipe["base_model"], name, revision,
                               issues, stream=is_weight, allow_download=allow_download)
        if entry is None:
            continue
        parents.add(str(Path(entry["path"]).parent))
        proof["files"][name] = dict(entry, expected_sha256=expected or None)
        if name == _prepare_training().WEIGHTS_INDEX_NAME:
            proof["index"] = {"path": entry["path"], "sha256": entry["sha256"],
                              "expected_sha256": expected or None, "shards": None,
                              "downloaded": entry.get("downloaded"),
                              "revision": entry.get("revision")}
        if expected and entry["sha256"] != expected:
            issues.fail(code, "%s: actual %r, pinned %r"
                        % (name, entry["sha256"], expected))
        report()
    if len(parents) > 1:
        issues.fail("snapshot_paths_disjoint",
                    "pinned files resolved under %d different snapshots" % len(parents))
    elif parents:
        proof["snapshot_path"] = parents.pop()
        proof["snapshot_revision"] = Path(proof["snapshot_path"]).name

    snapshot = proof["snapshot_path"]
    index_entry = proof["files"].get(_prepare_training().WEIGHTS_INDEX_NAME)
    if index_pin and weights:
        structural = None
        if index_entry is None:
            issues.fail("weights_index_missing",
                        "%s is pinned but was not resolved"
                        % _prepare_training().WEIGHTS_INDEX_NAME)
        else:
            structural = _verify_weight_index(Path(index_entry["path"]), weights, issues)
        proof["index"] = {
            "path": (structural or {}).get("path") or (index_entry or {}).get("path"),
            "sha256": (index_entry or {}).get("sha256"),
            "expected_sha256": index_pin,
            "shards": (structural or {}).get("shards"),
            "downloaded": (index_entry or {}).get("downloaded"),
            "revision": (index_entry or {}).get("revision"),
        }
    elif snapshot and Path(snapshot).is_dir():
        index_path = Path(snapshot) / _prepare_training().WEIGHTS_INDEX_NAME
        if index_path.exists():
            issues.fail("weights_index_unpinned",
                        "%s exists but recipe.weights_index_sha256 is empty" % index_path)
    if snapshot and Path(snapshot).is_dir():
        _reject_unpinned_weights(Path(snapshot), weights, issues)
        _reject_unpinned_tokenizer_representation(Path(snapshot), assets, issues)
    proof["status"] = "verified" if len(issues.failures) == start else "failed"
    report()
    return proof


def _verify_weight_index(path, weights, issues):
    """Bind the loader's shard index to the pinned weight-file set."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        weight_map = payload["weight_map"]
        if not isinstance(weight_map, dict):
            raise ValueError("weight_map is not an object")
        shards = sorted({str(value) for value in weight_map.values()})
    except Exception as exc:
        issues.fail("weights_index_invalid", "%s cannot be read: %s" % (path.name, exc))
        return {"path": str(path), "sha256": None, "shards": None}
    if shards != sorted(weights):
        issues.fail("weights_index_mismatch",
                    "%s names %s, the pins are %s"
                    % (path.name, shards, sorted(weights)))
    return {"path": str(path), "sha256": file_sha256(path), "shards": shards}


def _reject_unpinned_weights(snapshot, weights, issues):
    """A weight file the pins do not name could be the one the loader reads."""
    for entry in sorted(Path(snapshot).iterdir()):
        if not entry.is_file() and not entry.is_symlink():
            continue
        name = entry.name
        if name in weights:
            continue
        if name.lower().endswith(WEIGHT_SUFFIXES):
            issues.fail("unpinned_weight_file",
                        "%s is a weight file the recipe does not pin" % name)


def _reject_unpinned_tokenizer_representation(snapshot, assets, issues):
    """A second vocabulary set the pins do not name can override the pinned one.

    The upstream repo ships `tokenizer.json`, `vocab.json`, and `merges.txt`
    together, so transformers has an alternate representation to fall back on.
    If that alternate lands in the same snapshot without a pin, the loaded
    vocabulary is not the one this recipe approved.
    """
    for name in TOKENIZER_REPRESENTATION_FILES:
        if name in assets:
            continue
        if (Path(snapshot) / name).exists():
            issues.fail("unpinned_tokenizer_representation",
                        "%s is a tokenizer representation the recipe does not pin"
                        % name)


def identity_payload(recipe, proof, resolved, phase, loader=None, status=None):
    """Requested, resolved, and measured stay in separate fields."""
    files = (proof or {}).get("files") or {}
    weights = {name: item.get("sha256") for name, item in files.items()
               if name in ((proof or {}).get("pins") or {}).get("weights_sha256", {})}
    return {
        "schema": IDENTITY_SCHEMA,
        "status": status or ("ok" if (proof or {}).get("status") == "verified" else "refused"),
        "phase": phase,
        "requested": (proof or {}).get("requested")
                     or {"base_model": recipe.get("base_model"),
                         "base_revision": recipe.get("base_revision"),
                         "tokenizer_revision": recipe.get("tokenizer_revision")},
        "resolved": {"snapshot_path": (proof or {}).get("snapshot_path"),
                     "snapshot_revision": (proof or {}).get("snapshot_revision"),
                     "config_path": resolved.get("config_path"),
                     "tokenizer_config_path": resolved.get("tokenizer_config_path"),
                     "weights_index": (proof or {}).get("index")},
        "pins": (proof or {}).get("pins") or {
            "config_sha256": recipe.get("config_sha256"),
            "weights_sha256": _pinned_weights(recipe),
            "tokenizer_assets_sha256": _tokenizer_assets(recipe),
            "weights_index_sha256": recipe.get("weights_index_sha256")},
        "measured": {"config_sha256": resolved.get("config_sha256"),
                     "tokenizer_config_sha256": resolved.get("tokenizer_config_sha256"),
                     "tokenizer_assets_sha256": resolved.get("tokenizer_assets_sha256") or {},
                     "tokenizer_asset_files": resolved.get("tokenizer_asset_files") or {},
                     "weights_sha256": weights,
                     "weights_index_sha256": resolved.get("weights_index_sha256"),
                     "weights_index_shards": ((proof or {}).get("index") or {}).get("shards"),
                     "loader_input": resolved.get("loader_input"),
                     "snapshot_manifest": {name: item.get("sha256")
                                           for name, item in files.items()}},
        "loader": loader or {"input_argument": None, "resolved_name": None,
                             "commit_hash": None, "commit_field_present": None},
    }


def write_identity(path, payload, issues):
    if path is None:
        return
    payload = dict(payload)
    payload["failures"] = issues.failures
    payload["notes"] = issues.notes
    if issues.failures:
        payload["status"] = "refused"
    write_json(path, payload)


# --------------------------------------------------------------- stop checks


def select_stop_rows(rows):
    picks = {}
    for index, row in enumerate(rows):
        family = label_family(row)
        if family in ("answer", "refusal", "history") and family not in picks:
            picks[family] = index
    return picks


def run_stop_checks(model, tokenizer, rows, recipe, model_conf, kinds, issues, label):
    picks = select_stop_rows(rows)
    missing = [kind for kind in kinds if kind not in picks]
    if missing:
        issues.fail("stop_check_row_missing", "%s: no row for %s" % (label, ", ".join(missing)))
    checks = []
    try:
        model.eval()
    except Exception:
        pass
    for kind in kinds:
        index = picks.get(kind)
        if index is None:
            continue
        row = rows[index]
        prompt_messages = row["messages"][:-1]
        try:
            prompt = render(tokenizer, prompt_messages, True, thinking=False)
        except Exception as exc:
            issues.fail("stop_check_render_failed", "%s %s: %s" % (label, kind, exc))
            continue
        if model_conf.get("thinking_scaffold") and "</think>" not in prompt:
            issues.fail("stop_check_thinking_open", "%s %s: prompt leaves thinking open"
                        % (label, kind))
        try:
            import torch
            encoded = tokenizer(prompt, return_tensors="pt", add_special_tokens=False)
            encoded = {key: value.to(model.device) for key, value in encoded.items()}
            with torch.no_grad():
                output = model.generate(
                    **encoded, max_new_tokens=STOP_CHECK_MAX_NEW_TOKENS,
                    do_sample=False, use_cache=True,
                    eos_token_id=tokenizer.eos_token_id,
                    pad_token_id=tokenizer.pad_token_id)
            new_tokens = output[0][encoded["input_ids"].shape[1]:]
            text = tokenizer.decode(new_tokens, skip_special_tokens=False)
        except Exception as exc:
            issues.fail("stop_check_generate_failed", "%s %s: %s" % (label, kind, exc))
            continue
        hit = len(new_tokens) >= STOP_CHECK_MAX_NEW_TOKENS and recipe["assistant_eos"] not in text
        defects = _prepare_training().detect_completion_defects(
            text, eos=recipe["assistant_eos"], max_new_tokens_hit=hit)
        for defect in defects:
            issues.fail("stop_check_%s_%s" % (label, defect),
                        "%s: %r" % (kind, text[:120]))
        checks.append({"kind": kind, "row_index": index,
                       "prompt_sha256": sha256_text(prompt),
                       "prompt_source": "messages[:-1] rendered with add_generation_prompt=True",
                       "text": text[:4000], "generated_tokens": int(len(new_tokens)),
                       "max_new_tokens": STOP_CHECK_MAX_NEW_TOKENS,
                       "defects": defects})
    return checks


# --------------------------------------------------------------- training


class ReviewedCollator:
    """Pad only. The labels it receives are the preflight labels."""

    def __init__(self, pad_token_id, max_seq_length):
        self.pad_token_id = pad_token_id
        self.max_seq_length = max_seq_length

    def __call__(self, features):
        import torch
        batch = pad_batch(features, self.pad_token_id, self.max_seq_length)
        return {key: torch.tensor(value) for key, value in batch.items()}


def pad_batch(features, pad_token_id, max_seq_length):
    """Pure padding, so the label boundary can be tested without torch."""
    if not features:
        raise ValueError("empty batch")
    for index, feature in enumerate(features):
        ids, labels = feature["input_ids"], feature["labels"]
        if len(ids) != len(labels):
            raise ValueError("row %d: %d ids, %d labels" % (index, len(ids), len(labels)))
        if len(ids) > max_seq_length:
            raise ValueError("row %d: %d tokens exceeds max_seq_length %d; refusing to truncate"
                             % (index, len(ids), max_seq_length))
    width = max(len(feature["input_ids"]) for feature in features)
    batch = {"input_ids": [], "labels": [], "attention_mask": []}
    for feature in features:
        length = len(feature["input_ids"])
        pad = width - length
        batch["input_ids"].append(list(feature["input_ids"]) + [pad_token_id] * pad)
        batch["labels"].append(list(feature["labels"]) + [-100] * pad)
        batch["attention_mask"].append([1] * length + [0] * pad)
    return batch


def build_trainer(model, tokenizer, recipe, train_rows, validation_rows, out):
    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer

    train_dataset = Dataset.from_list([
        {"input_ids": row["input_ids"], "labels": row["labels"]} for row in train_rows])
    eval_dataset = Dataset.from_list([
        {"input_ids": row["input_ids"], "labels": row["labels"]} for row in validation_rows])
    try:
        import torch
        bf16 = torch.cuda.is_bf16_supported()
    except Exception:
        bf16 = False
    args = SFTConfig(
        output_dir=str(Path(out) / "checkpoints"),
        per_device_train_batch_size=2,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=4,
        warmup_steps=5,
        num_train_epochs=int(recipe["epochs"]),
        max_length=int(recipe["max_seq_length"]),
        learning_rate=float(recipe["learning_rate"]),
        fp16=not bf16, bf16=bf16,
        logging_steps=5,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=int(recipe["seed"]),
        save_strategy="epoch",
        save_total_limit=2,
        eval_strategy="epoch",
        report_to="none",
        dataset_kwargs={"skip_prepare_dataset": True},
        remove_unused_columns=False,
    )
    trainer = SFTTrainer(
        model=model, args=args, train_dataset=train_dataset, eval_dataset=eval_dataset,
        processing_class=tokenizer,
        data_collator=ReviewedCollator(tokenizer.pad_token_id, int(recipe["max_seq_length"])),
    )
    if len(trainer.train_dataset) != len(train_rows):
        raise RuntimeError("SFTTrainer kept %d of %d rows"
                           % (len(trainer.train_dataset), len(train_rows)))
    for index in sorted({0, len(train_rows) - 1, len(train_rows) // 2}):
        kept = list(trainer.train_dataset[index]["labels"])
        if kept != list(train_rows[index]["labels"]):
            raise RuntimeError("SFTTrainer changed the labels of row %d" % index)
    return trainer


def epoch_losses(history):
    table, current = [], []
    for entry in history:
        if "loss" in entry and "epoch" in entry:
            current.append(float(entry["loss"]))
        if "eval_loss" in entry:
            table.append({"epoch": int(round(float(entry["epoch"]))),
                          "train": round(sum(current) / len(current), 6) if current else None,
                          "eval": float(entry["eval_loss"])})
            current = []
    return table


# --------------------------------------------------------------- export


def export_artifacts(model, tokenizer, out, name):
    out = Path(out)
    lora_dir = out / "lora"
    model.save_pretrained(str(lora_dir))
    tokenizer.save_pretrained(str(lora_dir))
    adapter = lora_dir / "adapter_model.safetensors"
    if not adapter.exists():
        raise RuntimeError("no adapter_model.safetensors under %s" % lora_dir)
    lora_sha = file_sha256(adapter)

    merged_dir = out / "merged_16bit"
    model.save_pretrained_merged(str(merged_dir), tokenizer, save_method=EXPORT_MERGED)
    manifest = [{"name": path.name, "bytes": path.stat().st_size,
                 "sha256": file_sha256(path)}
                for path in sorted(merged_dir.rglob("*")) if path.is_file()]
    merged_sha = sha256_text(canonical_json(manifest))

    gguf_dir = out / "gguf"
    model.save_pretrained_gguf(str(gguf_dir), tokenizer, quantization_method=EXPORT_QUANT)
    # Unsloth writes the converted files to a sibling ``gguf_gguf`` directory in
    # some releases (observed 2026-10-31: conversion succeeded, then a zero-file
    # check failed after training). Accept either location, but still require
    # exactly one GGUF so a split or duplicate cannot be packaged silently.
    search_dirs = [gguf_dir, out / "gguf_gguf"]
    candidates = sorted({path for directory in search_dirs
                         for path in directory.glob("*.gguf")})
    if len(candidates) != 1:
        raise RuntimeError("expected one GGUF under %s, found %d"
                           % (" or ".join(str(path) for path in search_dirs),
                              len(candidates)))
    gguf = candidates[0]
    gguf_sha = file_sha256(gguf)
    zip_path = out / ("%s_%s.zip" % (re.sub(r"[^A-Za-z0-9._-]+", "-", name), EXPORT_QUANT))
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(gguf, gguf.name)
        modelfile = next((directory / "Modelfile" for directory in search_dirs
                          if (directory / "Modelfile").exists()), None)
        if modelfile is not None:
            archive.write(modelfile, modelfile.name)
    return {"lora_sha256": lora_sha, "gguf_sha256": gguf_sha,
            "gguf_bytes": gguf.stat().st_size, "gguf_quant": EXPORT_QUANT,
            "merged_16bit_sha256": merged_sha, "merged_16bit_files": len(manifest),
            "zip_sha256": file_sha256(zip_path), "zip_path": str(zip_path),
            "lora_path": str(lora_dir), "merged_path": str(merged_dir),
            "gguf_path": str(gguf)}


# --------------------------------------------------------------- reports


def runtime_facts(torch, started, wall_s, peak_mib):
    import platform
    import transformers
    import trl
    import unsloth

    try:
        import peft
        peft_version = getattr(peft, "__version__", "unknown")
    except Exception:
        peft_version = "unknown"
    gpu = "cpu"
    try:
        gpu = torch.cuda.get_device_name(0)
        gpu_mib = int(torch.cuda.get_device_properties(0).total_memory / (1024 ** 2))
    except Exception:
        gpu_mib = 0
    return {"gpu": gpu, "gpu_total_mib": gpu_mib, "gpu_peak_reserved_mib": peak_mib,
            "python": platform.python_version(), "torch": torch.__version__,
            "transformers": transformers.__version__, "trl": trl.__version__,
            "unsloth": getattr(unsloth, "__version__", "unknown"),
            "peft": peft_version,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
            "wall_seconds": round(wall_s, 3)}


def build_run_report(package, recipe, measurement, validation, stop_checks,
                     runtime, losses, artifacts, preflight_sha, approval_sha, identity):
    manifest = package.manifest
    dataset = manifest["inputs"]["dataset"]
    return {
        "schema": RUN_SCHEMA, "mode": "train",
        "release_id": manifest.get("release_id"),
        "manifest_sha256": package.manifest_sha256,
        "contract_sha256": package.contract_sha256,
        "preflight_report_sha256": preflight_sha,
        "approval_sha256": approval_sha,
        "dataset": {"sha256_rows": dataset["sha256_rows"],
                    "sha256_bytes": dataset["sha256_bytes"],
                    "rows": dataset["row_facts"]["rows"]},
        "validation": {"sha256_bytes": package.facts["validation"]["sha256_bytes"],
                       "rows": package.facts["validation"]["rows"],
                       "role": package.facts["validation"]["role"],
                       "family_ids_sha256": package.validation_block.get("family_ids_sha256")},
        "recipe": {"base_model": recipe["base_model"],
                   "base_revision": recipe["base_revision"],
                   "tokenizer_revision": recipe.get("tokenizer_revision"),
                   "tokenizer_config_sha256": recipe["tokenizer_config_sha256"],
                   "config_sha256": recipe.get("config_sha256"),
                   "weights_sha256": recipe.get("weights_sha256"),
                   "seed": recipe["seed"], "epochs": recipe["epochs"],
                   "lora_r": recipe["lora_r"], "lora_alpha": recipe["lora_alpha"],
                   "learning_rate": recipe["learning_rate"],
                   "max_seq_length": recipe["max_seq_length"],
                   "target_modules": recipe["target_modules"]},
        "chat_template_sha256": identity["chat_template_sha256"],
        "preflight": {"measured_before_train": True, "status": "pass",
                      "dataset_sha256": dataset["sha256_bytes"],
                      "recipe_sha256": manifest["inputs"]["recipe_sha256"],
                      "chat_template_sha256": identity["chat_template_sha256"],
                      "tokenizer_config_sha256": identity["tokenizer_config_sha256"],
                      "base_config_sha256": identity.get("config_sha256"),
                      "base_weights_sha256": identity.get("weights_sha256"),
                      "tokenizer_assets_sha256": identity.get("tokenizer_assets_sha256"),
                      "loader_commit_hash": identity.get("loader_commit_hash"),
                      "rows_checked": measurement["rows_checked"],
                      "mask_rows_checked": measurement["mask_rows_checked"],
                      "dataset_sha256_rows": dataset["sha256_rows"],
                      "validation_sha256": package.facts["validation"]["sha256_bytes"],
                      "validation_rows": package.validation_block.get("rows"),
                      "validation_rows_checked": validation["rows_checked"],
                      "recipe_sha256": manifest["inputs"]["recipe_sha256"],
                      "base_revision": recipe["base_revision"],
                      "tokenizer_revision": recipe["tokenizer_revision"],
                      "runner_sha256": package.facts.get("runner_sha256"),
                      "deps_sha256": (package.facts.get("deps") or {}).get("sha256"),
                      "control_inventory_sha256": package.facts.get("controls_sha256"),
                      "inventory_sha256": (package.facts.get("inventory") or {}).get("sha256"),
                      "inventory_fragment_sha256":
                          (package.facts.get("inventory") or {}).get("fragment_sha256"),
                      "source_receipt_sha256":
                          (package.facts.get("inventory") or {}).get("receipt_sha256"),
                      "max_tokens": measurement["max_tokens"],
                      "truncated_rows": 0},
        "tokens": {"max": measurement["max_tokens"],
                   "p50": measurement["p50_tokens"], "p90": measurement["p90_tokens"],
                   "validation_max": validation["max_tokens"],
                   "truncated_rows": 0},
        "masks": {"assistant_label_tokens": measurement["assistant_label_tokens"],
                  "user_system_supervised_tokens": measurement["user_system_supervised_tokens"],
                  "prior_assistant_supervised_tokens":
                      measurement["prior_assistant_supervised_tokens"],
                  "prior_assistant_rows": measurement["prior_assistant_rows"],
                  "eos_in_supervised": measurement["eos_in_supervised"],
                  "eos_total": measurement["eos_total"],
                  "negative_label_supervised_tokens": {"system": 0, "user": 0},
                  "family_rows": measurement["family_rows"],
                  "family_eos_rows": measurement["family_eos_rows"],
                  "spot_checks": measurement["spot_checks"],
                  "scaffold_sha256": measurement["scaffold_sha256"],
                  "method": measurement["method"]},
        "stop_checks": stop_checks,
        "runtime": runtime, "losses": {"epochs": losses}, "artifacts": artifacts,
    }


def expected_package_facts(package):
    """The current package's fixed facts; the approval and drift compare these."""
    manifest = package.manifest
    inputs = manifest.get("inputs") or {}
    dataset = inputs.get("dataset") or {}
    recipe = manifest.get("recipe") or {}
    runner = inputs.get("runner") or {}
    block = package.validation_block or {}
    return {
        "dataset_sha256": dataset.get("sha256_bytes"),
        "dataset_sha256_rows": dataset.get("sha256_rows"),
        "rows_checked": (dataset.get("row_facts") or {}).get("rows"),
        "validation_sha256": block.get("sha256_bytes"),
        "validation_rows": block.get("rows"),
        "validation_rows_checked": block.get("rows"),
        "recipe_sha256": inputs.get("recipe_sha256"),
        "base_revision": recipe.get("base_revision"),
        "tokenizer_revision": recipe.get("tokenizer_revision"),
        "base_config_sha256": recipe.get("config_sha256"),
        "base_weights_sha256": recipe.get("weights_sha256"),
        "tokenizer_assets_sha256": recipe.get("tokenizer_assets_sha256"),
        "chat_template_sha256": recipe.get("tokenizer_chat_template_sha256"),
        "tokenizer_config_sha256": recipe.get("tokenizer_config_sha256"),
        "runner_sha256": runner.get("sha256"),
        "deps_sha256": runner.get("deps_sha256"),
        "control_inventory_sha256": package.facts.get("controls_sha256"),
        "inventory_sha256": (package.facts.get("inventory") or {}).get("sha256"),
        "inventory_fragment_sha256": (package.facts.get("inventory") or {}).get("fragment_sha256"),
        "source_receipt_sha256": (package.facts.get("inventory") or {}).get("receipt_sha256"),
        "manifest_sha256": package.manifest_sha256,
        "contract_sha256": package.contract_sha256,
    }


def build_preflight_report(package, recipe, measurement, validation, identity,
                           stop_checks, runtime):
    return {
        "schema": PREFLIGHT_SCHEMA, "mode": "preflight", "status": "pass",
        "manifest_sha256": package.manifest_sha256,
        "contract_sha256": package.contract_sha256,
        "dataset_sha256": package.manifest["inputs"]["dataset"]["sha256_bytes"],
        "dataset_sha256_rows": package.manifest["inputs"]["dataset"]["sha256_rows"],
        "validation_sha256": package.facts["validation"]["sha256_bytes"],
        "validation_rows": package.validation_block.get("rows"),
        "recipe_sha256": package.manifest["inputs"].get("recipe_sha256"),
        "base_revision": recipe["base_revision"],
        "tokenizer_revision": recipe["tokenizer_revision"],
        "base_config_sha256": identity.get("config_sha256"),
        "base_weights_sha256": identity.get("weights_sha256"),
        "loader_commit_hash": identity.get("loader_commit_hash"),
        "snapshot_revision": identity.get("snapshot_revision"),
        "weights_index_sha256": identity.get("weights_index_sha256"),
        "weights_index_shards": identity.get("weights_index_shards"),
        "tokenizer_assets_sha256": identity.get("tokenizer_assets_sha256"),
        "chat_template_sha256": identity["chat_template_sha256"],
        "tokenizer_config_sha256": identity["tokenizer_config_sha256"],
        "runner_sha256": package.facts.get("runner_sha256"),
        "deps_sha256": (package.facts.get("deps") or {}).get("sha256"),
        "control_inventory_sha256": package.facts.get("controls_sha256"),
        "inventory_sha256": (package.facts.get("inventory") or {}).get("sha256"),
        "inventory_fragment_sha256": (package.facts.get("inventory") or {}).get("fragment_sha256"),
        "source_receipt_sha256": (package.facts.get("inventory") or {}).get("receipt_sha256"),
        "identity": identity,
        "rows_checked": measurement["rows_checked"],
        "mask_rows_checked": measurement["mask_rows_checked"],
        "validation_rows_checked": validation["rows_checked"],
        "max_tokens": measurement["max_tokens"],
        "validation_max_tokens": validation["max_tokens"],
        "truncated_rows": 0,
        "assistant_label_tokens": measurement["assistant_label_tokens"],
        "eos_total": measurement["eos_total"],
        "family_rows": measurement["family_rows"],
        "family_eos_rows": measurement["family_eos_rows"],
        "masks": {"eos_in_supervised": measurement["eos_in_supervised"],
                  "spot_checks": measurement["spot_checks"],
                  "user_system_supervised_tokens":
                      measurement["user_system_supervised_tokens"],
                  "prior_assistant_supervised_tokens":
                      measurement["prior_assistant_supervised_tokens"],
                  "family_rows": measurement["family_rows"],
                  "family_eos_rows": measurement["family_eos_rows"]},
        "stop_checks": stop_checks,
        "runtime": runtime,
    }


def compare_package_facts(report, expected, issues):
    groups = (
        ("dataset", ("dataset_sha256", "dataset_sha256_rows", "rows_checked"),
         "preflight_dataset_mismatch"),
        ("validation", ("validation_sha256", "validation_rows", "validation_rows_checked"),
         "preflight_validation_mismatch"),
        ("recipe", ("recipe_sha256", "base_revision", "tokenizer_revision",
                    "base_config_sha256", "base_weights_sha256",
                    "tokenizer_assets_sha256", "chat_template_sha256",
                    "tokenizer_config_sha256"),
         "preflight_recipe_mismatch"),
        ("runner", ("runner_sha256", "deps_sha256"), "preflight_runner_mismatch"),
        ("controls", ("control_inventory_sha256",), "preflight_controls_mismatch"),
        ("inventory", ("inventory_sha256", "inventory_fragment_sha256",
                       "source_receipt_sha256"), "preflight_inventory_mismatch"),
    )
    for group, fields, code in groups:
        for field in fields:
            if report.get(field) != expected.get(field):
                issues.fail(code, "%s: report %r, package %r"
                            % (field, report.get(field), expected.get(field)))


def compare_preflight(report, measurement, validation, identity, issues, expected=None):
    measured = {
        "rows_checked": measurement["rows_checked"],
        "mask_rows_checked": measurement["mask_rows_checked"],
        "validation_rows_checked": validation["rows_checked"],
        "max_tokens": measurement["max_tokens"],
        "validation_max_tokens": validation["max_tokens"],
        "assistant_label_tokens": measurement["assistant_label_tokens"],
        "eos_total": measurement["eos_total"],
        "family_rows": measurement["family_rows"],
        "family_eos_rows": measurement["family_eos_rows"],
        "chat_template_sha256": identity["chat_template_sha256"],
        "tokenizer_config_sha256": identity["tokenizer_config_sha256"],
        "base_config_sha256": identity.get("config_sha256"),
        "base_weights_sha256": identity.get("weights_sha256"),
        "loader_commit_hash": identity.get("loader_commit_hash"),
        "snapshot_revision": identity.get("snapshot_revision"),
        "weights_index_sha256": identity.get("weights_index_sha256"),
        "weights_index_shards": identity.get("weights_index_shards"),
        "tokenizer_assets_sha256": identity.get("tokenizer_assets_sha256"),
    }
    for key, value in measured.items():
        if report.get(key) != value:
            issues.fail("preflight_drift",
                        "%s: approved %r, this session measured %r"
                        % (key, report.get(key), value))
    if expected:
        compare_package_facts(report, expected, issues)


def verify_approval(approval, approval_bytes, report, report_bytes, package, issues):
    if approval.get("schema") != APPROVAL_SCHEMA:
        issues.fail("approval_schema", "expected %s" % APPROVAL_SCHEMA)
    if str(approval.get("decision", "")).lower() != "approved":
        issues.fail("approval_not_approved", "decision is %r" % approval.get("decision"))
    if not approval.get("reviewer") or not approval.get("approved_at"):
        issues.fail("approval_unattributed", "reviewer and approved_at are required")
    if approval.get("manifest_sha256") != package.manifest_sha256:
        issues.fail("approval_manifest_mismatch", "approval binds a different manifest")
    if approval.get("contract_sha256") != package.contract_sha256:
        issues.fail("approval_contract_mismatch", "approval binds a different contract")
    if approval.get("preflight_report_sha256") != sha256_bytes(report_bytes):
        issues.fail("approval_report_mismatch", "approval binds different preflight bytes")
    if report.get("schema") != PREFLIGHT_SCHEMA or report.get("status") != "pass":
        issues.fail("approval_report_invalid", "the bound report is not a passing preflight")
    if report.get("manifest_sha256") != package.manifest_sha256:
        issues.fail("preflight_manifest_mismatch", "the report was produced for another manifest")
    if report.get("contract_sha256") != package.contract_sha256:
        issues.fail("preflight_contract_mismatch", "the report used another contract")
    if approval.get("export") != package.contract.get("export"):
        issues.fail("approval_export_mismatch", "the approval does not bind the export recipe")
    compare_package_facts(report, expected_package_facts(package), issues)


def recheck_sources(package, issues):
    paths = {
        "dataset": package.facts["dataset"]["path"],
        "ledger": package.facts["split"]["ledger"],
        "audit": package.facts["split"]["audit"],
        "validation": package.facts["validation"]["path"],
        "deps": (package.facts.get("deps") or {}).get("path"),
    }
    expected = {
        "dataset": package.facts["dataset"]["sha256_bytes"],
        "ledger": package.facts["split"]["sha256_ledger"],
        "audit": package.facts["split"]["sha256_audit"],
        "validation": package.facts["validation"]["sha256_bytes"],
        "deps": (package.facts.get("deps") or {}).get("sha256"),
    }
    for name, path in paths.items():
        if not path or not Path(path).exists():
            issues.fail("source_missing_before_train", "%s file %r is gone" % (name, path))
        elif file_sha256(path) != expected[name]:
            issues.fail("source_changed_before_train", "%s bytes changed since the package check"
                        % name)
    if file_sha256(Path(__file__).resolve()) != package.facts["runner_sha256"]:
        issues.fail("source_changed_before_train", "the runner bytes changed during load")


# --------------------------------------------------------------- events


class EventLog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "a", encoding="utf-8")

    def event(self, name, **fields):
        record = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": name}
        record.update(fields)
        self.handle.write(json.dumps(record, sort_keys=True) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())

    def close(self):
        self.handle.close()


def failure_record(stage, exc, issues, identity=None):
    record = {"stage": stage, "status": "fail", "failures": issues.failures,
              "notes": issues.notes, "error": repr(exc),
              "traceback": traceback.format_exc()}
    if identity:
        record["identity"] = identity
    return record


# --------------------------------------------------------------- GPU stages


class LoaderInputMismatch(RuntimeError):
    """Unsloth resolved a name other than the verified local snapshot."""


def load_model(recipe, issues, proof):
    """Load from the verified local directory only. A repo tag is never passed."""
    snapshot = (proof or {}).get("snapshot_path")
    if (proof or {}).get("status") != "verified" or not snapshot:
        issues.fail("base_artifact_unverified",
                    "refusing to load without a verified local snapshot")
        return None, None, None, {"input_argument": None, "resolved_name": None}
    actual = {"input_argument": str(snapshot), "resolved_name": None}

    def on_model_resolved(name):
        actual["resolved_name"] = str(name)
        if not same_real_path(name, snapshot):
            raise LoaderInputMismatch(
                "the loader resolved %r, the verified snapshot is %r" % (name, snapshot))

    try:
        import torch
        from unsloth import FastLanguageModel
    except Exception as exc:
        issues.fail("deps_missing", "torch/unsloth are unavailable: %s" % exc)
        return None, None, None, actual
    try:
        model, processor = FastLanguageModel.from_pretrained(
            model_name=str(snapshot),
            max_seq_length=int(recipe["max_seq_length"]),
            load_in_4bit=True,
            text_only=True,
            fix_tokenizer=True,
            use_exact_model_name=True,
            local_files_only=True,
            use_safetensors=True,
            on_model_resolved=on_model_resolved,
        )
    except LoaderInputMismatch as exc:
        issues.fail("loader_input_mismatch", str(exc))
        return None, None, None, actual
    except Exception as exc:
        issues.fail("model_load_failed", "%s: %s" % (snapshot, exc))
        return None, None, None, actual
    if actual.get("resolved_name") is None:
        issues.fail("loader_resolution_unobserved",
                    "the loader returned without on_model_resolved naming its input; "
                    "the input argument is not a measured resolution")
        return None, None, None, actual
    return model, getattr(processor, "tokenizer", processor), torch, actual


def resolve_identity(recipe, proof=None):
    files = (proof or {}).get("files") or {}
    config = files.get("config.json") or {}
    tokenizer_config = files.get("tokenizer_config.json") or {}
    assets = _tokenizer_assets(recipe)
    asset_files = {name: files[name] for name in assets if name in files}
    weights = {name: item.get("sha256") for name, item in files.items()
               if name in ((proof or {}).get("pins") or {}).get("weights_sha256", {})}
    return {"config_sha256": config.get("sha256"),
            "config_path": config.get("path"),
            "config_revision": config.get("revision"),
            "tokenizer_config_sha256": tokenizer_config.get("sha256"),
            "tokenizer_config_path": tokenizer_config.get("path"),
            "tokenizer_revision": tokenizer_config.get("revision"),
            "tokenizer_assets_sha256": {name: item.get("sha256")
                                        for name, item in asset_files.items()},
            "tokenizer_asset_files": asset_files,
            "weights_sha256": weights,
            "weights_index_sha256": ((proof or {}).get("index") or {}).get("sha256"),
            "weights_index_path": ((proof or {}).get("index") or {}).get("path"),
            "artifact_proof": proof}


def attach_lora(model, recipe, issues):
    from unsloth import FastLanguageModel
    present = {name.split(".")[-1] for name, _ in model.named_modules()}
    missing = [target for target in recipe["target_modules"] if target not in present]
    if missing:
        issues.fail("lora_targets_missing",
                    "the base model lacks %s; refusing to train a different recipe"
                    % ", ".join(missing))
        return None
    return FastLanguageModel.get_peft_model(
        model, r=int(recipe["lora_r"]), lora_alpha=int(recipe["lora_alpha"]),
        lora_dropout=float(recipe.get("lora_dropout", 0.0)),
        target_modules=list(recipe["target_modules"]),
        use_gradient_checkpointing="unsloth", random_state=int(recipe["seed"]))


def measure_stage(model, tokenizer, package, recipe, issues, log):
    train = measure_rows(package.rows, tokenizer, recipe, issues, "train",
                         require_families=((package.manifest.get("rows") or {})
                                           .get("mask_families")))
    log.event("train_measured", rows=train["rows_checked"] if train else 0)
    validation = measure_rows(package.validation_rows, tokenizer, recipe, issues,
                              "validation")
    log.event("validation_measured", rows=validation["rows_checked"] if validation else 0)
    return train, validation


def load_session(package, log, recipe, preflight_report=None, *,
                 allow_download=False, identity_path=None, identity_state=None):
    """Prove the snapshot, load from it, prove identity, measure.

    The identity measurement is written before the loader runs and rewritten
    after it, so a refusal still carries the bytes that were measured.
    """
    state = identity_state if identity_state is not None else {}

    def progress(partial):
        state.update(identity_payload(recipe, partial, resolve_identity(recipe, partial),
                                      "pre_load", status="partial"))
        write_identity(identity_path, state, package.issues)

    proof = resolve_snapshot(recipe, package.issues, allow_download=allow_download,
                             on_progress=progress)
    resolved = resolve_identity(recipe, proof)
    state.update(identity_payload(recipe, proof, resolved, "pre_load"))
    write_identity(identity_path, state, package.issues)
    log.event("snapshot_verified", status=proof.get("status"),
              snapshot=proof.get("snapshot_path"),
              files=len(proof.get("files") or {}),
              weights=len(proof.get("pins", {}).get("weights_sha256") or {}))
    if not package.issues.ok:
        return None
    model, tokenizer, torch, actual = load_model(recipe, package.issues, proof)
    config = getattr(model, "config", None)
    resolved["commit"] = str(getattr(config, "_commit_hash", "") or "")
    resolved["commit_field_present"] = hasattr(config, "_commit_hash")
    resolved["loader_input"] = actual.get("resolved_name")
    resolved["loader_input_argument"] = actual.get("input_argument")
    loader_facts = {"input_argument": actual.get("input_argument"),
                    "resolved_name": actual.get("resolved_name"),
                    "commit_hash": resolved["commit"] or None,
                    "commit_field_present": resolved["commit_field_present"]}
    state.update(identity_payload(recipe, proof, resolved, "post_load", loader=loader_facts))
    write_identity(identity_path, state, package.issues)
    if not package.issues.ok:
        return None
    log.event("model_loaded", loader_input=actual.get("resolved_name"))
    if not torch.cuda.is_available():
        package.issues.fail("gpu_missing", "preflight and train require a CUDA device")
        write_identity(identity_path, state, package.issues)
        return None
    identity = verify_identity(tokenizer, recipe, package.contract["model"],
                               resolved, package.issues)
    state.update(identity_payload(recipe, proof, resolved, "post_load", loader={
        "input_argument": actual.get("input_argument"),
        "resolved_name": actual.get("resolved_name"),
        "commit_hash": identity.get("loader_commit_hash"),
        "commit_field_present": identity.get("commit_field_present")}))
    write_identity(identity_path, state, package.issues)
    train, validation = measure_stage(model, tokenizer, package, recipe,
                                      package.issues, log)
    if train is None or validation is None:
        return None
    if preflight_report is not None:
        compare_preflight(preflight_report, train, validation, identity, package.issues,
                          expected=expected_package_facts(package))
    return {"model": model, "tokenizer": tokenizer, "torch": torch,
            "identity": identity, "train": train, "validation": validation}


def refuse(package, out=None):
    if out is not None:
        write_json(Path(out) / "run-failure.json",
                   {"stage": "train", "status": "fail",
                    "failures": package.issues.failures, "notes": package.issues.notes})
    print(json.dumps({"status": "fail", "failures": package.issues.failures},
                     indent=1, sort_keys=True))
    return 2


def cmd_package(args):
    package = load_package(args.manifest, args.contract, dataset=args.dataset,
                           ledger=args.ledger, audit=args.audit,
                           validation=args.validation, deps=args.deps,
                           review=args.review)
    payload = {"schema": "training-package-check/1", "mode": "package",
               "status": "pass" if package.issues.ok else "fail",
               "failures": package.issues.failures, "notes": package.issues.notes,
               "facts": package.facts}
    write_json(Path(args.out) / "package-check.json", payload)
    print(json.dumps(payload, indent=1, sort_keys=True))
    return 0 if package.issues.ok else 2


def cmd_preflight(args):
    package = load_package(args.manifest, args.contract, dataset=args.dataset,
                           ledger=args.ledger, audit=args.audit,
                           validation=args.validation, deps=args.deps,
                           review=args.review)
    out = Path(args.out)
    if package.manifest and package.manifest.get("status") != "ready-to-launch":
        package.issues.fail("manifest_not_ready",
                            "preflight requires ready-to-launch; %r is a fixture"
                            % package.manifest.get("status"))
    if not package.issues.ok:
        write_json(out / "preflight-report.json",
                   {"schema": PREFLIGHT_SCHEMA, "mode": "preflight", "status": "fail",
                    "failures": package.issues.failures, "notes": package.issues.notes})
        print(json.dumps({"status": "fail", "failures": package.issues.failures},
                         indent=1, sort_keys=True))
        return 2
    log = EventLog(out / "events.jsonl")
    started = time.time()
    identity_state = {}
    identity_path = out / "identity-measurement.json"
    try:
        recipe = package.facts["recipe"]
        session = load_session(package, log, recipe, allow_download=True,
                               identity_path=identity_path,
                               identity_state=identity_state)
        if session is None or not package.issues.ok:
            raise RuntimeError("preflight refused")
        stop_checks = run_stop_checks(session["model"], session["tokenizer"],
                                      package.rows, recipe, package.contract["model"],
                                      package.manifest.get("stop_checks") or [],
                                      package.issues, "pre")
        torch = session["torch"]
        peak = int(torch.cuda.max_memory_reserved() / (1024 ** 2)) if torch.cuda.is_available() else 0
        runtime = runtime_facts(torch, started, time.time() - started, peak)
        if not package.issues.ok:
            raise RuntimeError("preflight refused")
        report = build_preflight_report(package, recipe, session["train"],
                                        session["validation"], session["identity"],
                                        stop_checks, runtime)
        write_json(out / "preflight-report.json", report)
        log.event("preflight_report_written", status="pass")
        print(json.dumps({"status": "pass", "report": str(out / "preflight-report.json"),
                          "rows": session["train"]["rows_checked"],
                          "validation_rows": session["validation"]["rows_checked"],
                          "max_tokens": session["train"]["max_tokens"]},
                         indent=1, sort_keys=True))
        return 0
    except Exception as exc:
        log.event("preflight_failed", error=repr(exc))
        if identity_state:
            write_identity(identity_path, identity_state, package.issues)
        write_json(out / "preflight-failure.json",
                   failure_record("preflight", exc, package.issues, identity_state))
        print(json.dumps({"status": "fail", "failures": package.issues.failures,
                          "error": repr(exc)}, indent=1, sort_keys=True))
        return 2
    finally:
        log.close()


def cmd_train(args):
    package = load_package(args.manifest, args.contract, dataset=args.dataset,
                           ledger=args.ledger, audit=args.audit,
                           validation=args.validation, deps=args.deps,
                           review=args.review)
    out = Path(args.out)
    if package.manifest and package.manifest.get("status") != "ready-to-launch":
        package.issues.fail("manifest_not_ready",
                            "training requires ready-to-launch; %r is a fixture"
                            % package.manifest.get("status"))
    if not package.issues.ok:
        return refuse(package, out)
    report_obj, report_bytes = read_json_file(args.preflight_report,
                                              package.issues, "preflight_report")
    approval, approval_bytes = read_json_file(args.approval, package.issues, "approval")
    if not package.issues.ok or report_obj is None or approval is None:
        return refuse(package, out)
    verify_approval(approval, approval_bytes, report_obj, report_bytes, package,
                    package.issues)
    if not package.issues.ok:
        return refuse(package, out)
    log = EventLog(out / "events.jsonl")
    started = time.time()
    identity_state = {}
    identity_path = out / "identity-measurement.json"
    try:
        recipe = package.facts["recipe"]
        session = load_session(package, log, recipe, preflight_report=report_obj,
                               identity_path=identity_path,
                               identity_state=identity_state)
        if session is None:
            raise RuntimeError("measurement refused")
        model, tokenizer = session["model"], session["tokenizer"]
        run_stop_checks(model, tokenizer, package.rows, recipe, package.contract["model"],
                        package.manifest.get("stop_checks") or [], package.issues, "pre")
        if not package.issues.ok:
            raise RuntimeError("pre-train stop checks refused")
        model = attach_lora(model, recipe, package.issues)
        if not package.issues.ok or model is None:
            raise RuntimeError("LoRA setup refused")
        log.event("lora_attached", targets=recipe["target_modules"])
        trainer = build_trainer(model, tokenizer, recipe, session["train"]["tokenized"],
                                session["validation"]["tokenized"], out)
        log.event("trainer_built", train_rows=len(session["train"]["tokenized"]),
                  eval_rows=len(session["validation"]["tokenized"]))
        recheck_sources(package, package.issues)
        if not package.issues.ok:
            raise RuntimeError("sources changed before train")
        log.event("train_start", epochs=recipe["epochs"])
        trainer.train()
        elapsed = time.time() - started
        log.event("train_end", wall_seconds=round(elapsed, 3))
        stop_checks = run_stop_checks(model, tokenizer, package.rows, recipe,
                                      package.contract["model"],
                                      package.manifest.get("stop_checks") or [],
                                      package.issues, "post")
        if not package.issues.ok:
            raise RuntimeError("post-train stop checks refused")
        log.event("export_start")
        artifacts = export_artifacts(model, tokenizer, out,
                                     str(package.manifest.get("release_id") or "reviewed"))
        log.event("export_done", gguf=artifacts["gguf_sha256"])
        torch = session["torch"]
        peak = int(torch.cuda.max_memory_reserved() / (1024 ** 2)) if torch.cuda.is_available() else 0
        runtime = runtime_facts(torch, started, time.time() - started, peak)
        losses = epoch_losses(trainer.state.log_history)
        final = build_run_report(package, recipe, session["train"], session["validation"],
                                 stop_checks, runtime, losses, artifacts,
                                 sha256_bytes(report_bytes), sha256_bytes(approval_bytes),
                                 session["identity"])
        compare_package_facts(final["preflight"], expected_package_facts(package),
                              package.issues)
        _prepare_training().verify_run(final, package.manifest, package.issues)
        if not package.issues.ok:
            write_json(out / "training-run-report.invalid.json", final)
            raise RuntimeError("the parent gate refused the run report")
        write_json(out / "training-run-report.json", final)
        log.event("run_report_written", status="pass")
        print(json.dumps({"status": "pass", "report": str(out / "training-run-report.json"),
                          "epochs": losses}, indent=1, sort_keys=True))
        return 0
    except Exception as exc:
        log.event("train_failed", error=repr(exc))
        if identity_state:
            write_identity(identity_path, identity_state, package.issues)
        write_json(out / "run-failure.json",
                   failure_record("train", exc, package.issues, identity_state))
        print(json.dumps({"status": "fail", "failures": package.issues.failures,
                          "error": repr(exc)}, indent=1, sort_keys=True))
        return 2
    finally:
        log.close()


# --------------------------------------------------------------- CLI


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Manifest-consuming training runner for the reviewed corpus. "
                    "package is CPU-only; preflight and train need a GPU.")
    sub = parser.add_subparsers(dest="mode", required=True)

    def common(name, help_text):
        item = sub.add_parser(name, help=help_text)
        item.add_argument("--manifest", required=True, help="prepare_training manifest.json")
        item.add_argument("--contract", required=True, help="training-runner-contract/1 JSON")
        item.add_argument("--out", required=True, help="output directory")
        item.add_argument("--dataset", help="override the manifest dataset path (bytes are hashed)")
        item.add_argument("--ledger", help="override the frozen ledger path")
        item.add_argument("--audit", help="override the audit manifest path")
        item.add_argument("--validation", help="override the contract validation path")
        item.add_argument("--deps", help="override the manifest deps file; bytes are hashed")
        item.add_argument("--review", help="override the manifest source-review file")
        return item

    common("package", "CPU: verify the package, no model")
    common("preflight", "GPU: measure and write a preflight report")
    train = common("train", "GPU: preflight + approval, then train and export")
    train.add_argument("--preflight-report", required=True,
                       help="approved preflight-report.json")
    train.add_argument("--approval", required=True, help="training-preflight-approval/1 JSON")

    args = parser.parse_args(argv)
    if args.mode == "package":
        return cmd_package(args)
    if args.mode == "preflight":
        return cmd_preflight(args)
    if args.mode == "train":
        return cmd_train(args)
    parser.print_help()
    return 3


if __name__ == "__main__":
    sys.exit(main())
