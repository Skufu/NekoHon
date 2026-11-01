"""Offline release gate and launch plan for a Colab training job.

The job it guards is a LoRA finetune of a small instruct model on this repo's
quote/refusal corpus. This module does not train, download, or call anything:
it validates the exact bytes that would be trained on, proves the corpus is
the derivative it claims to be, proves no eval question sits inside it, and
only then writes a manifest plus the `colab` command plan. Anything missing is
a hard stop (exit 2), never a warning.

Why it fails closed: the corpus this repo actually trained on has already been
mis-stated twice (a "not located" corpus that was in git, and a claimed sha256
that only reproduces under the original CRLF line endings). A prep step that
shrugs at a hash mismatch would repeat both mistakes with a GPU attached.

Two rules shaped the design:

* LF and CRLF are different bytes and the same rows. Both digests are recorded,
  and the row digest is computed over canonical JSON of each parsed row, so a
  Windows checkout cannot change what "the dataset" means.
* A reserved eval set is hashed, never read. Its questions are supplied as
  sha256 values by whoever is allowed to look. That keeps the locked split
  locked while still enforcing "no training row asks this question".

Modes::

    python artifacts/colab/prepare_training.py --self-check
    python artifacts/colab/prepare_training.py --spec spec.json --out DIR
    python artifacts/colab/prepare_training.py --census --dataset FILE
    python artifacts/colab/prepare_training.py --verify-run report.json --manifest DIR/manifest.json

Exit codes: 0 ready (or a self-check that passed), 2 blocked, 3 bad usage.
Stdlib only. No network, no subprocess, no model identifiers.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA = "prepare-training-spec/1"
MANIFEST_SCHEMA = "prepare-training-manifest/1"
RUN_SCHEMA = "training-run-report/1"
REFUSAL = "Not in this book."
NEAR_RATIO = 0.85
NEAR_CONTENT_JACCARD = 0.6
STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "of", "in", "to", "do", "does",
    "did", "how", "why", "which", "for", "and", "it", "its", "this", "that",
    "these", "those", "was", "were", "be", "by", "on", "with", "can",
}
REPEAT_NGRAM = 4
REPEAT_RATIO = 0.5
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
TAG_RE = re.compile(r"\[Ch\. ([A-Za-z0-9]+)\]")
PART_RE = re.compile(r"([A-Za-z0-9_]+)(?:\[(-?\d+)\])?")
THINK_RE = re.compile(r"(<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>|<\|channel\|>"
                      r"|^\s*assistant\s*:|\bthinking\b)", re.IGNORECASE | re.MULTILINE)

REQUIRED_RECIPE = (
    "base_model",
    "base_revision",
    "tokenizer_revision",
    "tokenizer_chat_template_sha256",
    "tokenizer_config_sha256",
    "tokenizer_assets_sha256",
    "max_seq_length",
    "lora_r",
    "lora_alpha",
    "learning_rate",
    "seed",
    "epochs",
    "instruction_part",
    "response_part",
    "target_modules",
)
ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
WEIGHTS_INDEX_NAME = "model.safetensors.index.json"
CANONICAL_WEIGHT_NAME = "model.safetensors"
TOKENIZER_ASSET_NAMES = frozenset((
    "tokenizer.json", "tokenizer.model", "vocab.json", "merges.txt",
    "special_tokens_map.json", "added_tokens.json",
))
TOKENIZER_REPRESENTATION_GROUPS = (
    ("tokenizer.json",),
    ("tokenizer.model",),
    ("vocab.json", "merges.txt"),
)


class Report:
    """Failures block the package; notes are recorded in the manifest only."""

    def __init__(self):
        self.failures = []
        self.notes = []

    def fail(self, code, detail):
        self.failures.append({"code": code, "detail": detail})

    def note(self, code, detail):
        self.notes.append({"code": code, "detail": detail})

    @property
    def ok(self):
        return not self.failures


# --------------------------------------------------------------- byte facts


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def safe_artifact_name(name):
    """One plain file name. A pin may not point outside the snapshot directory."""
    name = str(name)
    return bool(ARTIFACT_NAME_RE.match(name)) and ".." not in name


def validate_tokenizer_assets(recipe, report):
    """Every file the tokenizer snapshot needs is pinned by its raw bytes."""
    assets = recipe.get("tokenizer_assets_sha256")
    if not isinstance(assets, dict) or not assets:
        report.fail("recipe_missing",
                    "recipe.tokenizer_assets_sha256 must map the tokenizer files "
                    "(vocabulary representation included) to their sha256")
        return
    names = set()
    for name in sorted(str(key) for key in assets):
        digest = assets.get(name)
        names.add(name)
        if not safe_artifact_name(name) or name in ("config.json", "tokenizer_config.json"):
            report.fail("recipe_unpinned",
                        "recipe.tokenizer_assets_sha256 key %r is not a plain "
                        "tokenizer asset file name" % (name,))
            continue
        if name not in TOKENIZER_ASSET_NAMES:
            report.fail("tokenizer_asset_unknown",
                        "recipe.tokenizer_assets_sha256 key %r is not a tokenizer "
                        "file; a notes map cannot stand in for the vocabulary" % (name,))
        if not SHA_RE.match(str(digest or "")):
            report.fail("recipe_unpinned",
                        "recipe.tokenizer_assets_sha256[%r] is not a sha256" % (name,))
    represented = [group for group in TOKENIZER_REPRESENTATION_GROUPS
                   if set(group) <= names]
    if not represented:
        report.fail("tokenizer_assets_representation_missing",
                    "the tokenizer asset map names no vocabulary representation: "
                    "tokenizer.json, or tokenizer.model, or vocab.json with merges.txt")


def validate_artifact_pins(recipe, report):
    """The base snapshot must be pinned by raw bytes: config and every weight file.

    Weights are keyed by file name because the loader may read a shard set; a
    missing or malformed pin is a refusal, never a warning. The index pin is
    structural: it is required whenever the loader would consult
    model.safetensors.index.json (more than one shard, or any name other than
    the canonical single model.safetensors), and its bytes must equal this pin
    when it is present.

    The tokenizer asset map is keyed the same way. It must name an actual
    vocabulary representation (`tokenizer.json`, or `tokenizer.model`, or
    `vocab.json` plus `merges.txt`), never a notes file: a sha256 map that
    omits the vocabulary proves nothing about what the loader tokenizes with.
    """
    config = str(recipe.get("config_sha256") or "")
    if not config:
        report.fail("recipe_missing", "recipe.config_sha256 is required")
    elif not SHA_RE.match(config):
        report.fail("recipe_unpinned", "recipe.config_sha256 must be a sha256")
    validate_tokenizer_assets(recipe, report)
    weights = recipe.get("weights_sha256")
    if not isinstance(weights, dict) or not weights:
        report.fail("recipe_missing",
                    "recipe.weights_sha256 must map every weight file to its sha256")
        return
    for name, digest in sorted(weights.items()):
        if not safe_artifact_name(name):
            report.fail("recipe_unpinned",
                        "recipe.weights_sha256 key %r is not a plain file name" % (name,))
        if not SHA_RE.match(str(digest or "")):
            report.fail("recipe_unpinned",
                        "recipe.weights_sha256[%r] is not a sha256" % (name,))
    index_pin = recipe.get("weights_index_sha256")
    if index_pin in (None, ""):
        if index_pin_required(weights):
            report.fail("recipe_missing",
                        "recipe.weights_index_sha256 is required when the weight set is "
                        "not exactly the canonical model.safetensors")
    elif not isinstance(index_pin, str) or not SHA_RE.match(index_pin):
        report.fail("recipe_unpinned",
                    "recipe.weights_index_sha256 must be a sha256, found %r" % (index_pin,))


def index_pin_required(weights):
    """Transformers reads a lone model.safetensors without consulting an index."""
    return sorted(str(name) for name in weights) != [CANONICAL_WEIGHT_NAME]


def lf_bytes(data):
    """CRLF folded to LF; lone CR left alone (it is not a line ending here)."""
    return data.replace(b"\r\n", b"\n")


def crlf_bytes(data):
    """LF expanded to CRLF, for reproducing a historical Windows digest."""
    return lf_bytes(data).replace(b"\n", b"\r\n")


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def row_digest(row):
    return sha256_bytes(canonical_json(row).encode("utf-8"))


def corpus_digest(rows):
    return sha256_bytes("\n".join(row_digest(r) for r in rows).encode("utf-8"))


def read_jsonl(data):
    """Parse LF-normalized bytes. Blank lines are skipped, a bad line raises."""
    rows = []
    for number, line in enumerate(lf_bytes(data).decode("utf-8").split("\n"), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("line %d is not JSON: %s" % (number, exc))
        if not isinstance(obj, dict):
            raise ValueError("line %d is not an object" % number)
        rows.append(obj)
    return rows


def line_ending(data):
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n")
    if crlf and crlf == lf:
        return "crlf"
    if crlf:
        return "mixed"
    return "lf"


def file_facts(path):
    data = Path(path).read_bytes()
    rows = read_jsonl(data)
    return {
        "path": str(path),
        "bytes": len(data),
        "sha256_bytes": sha256_bytes(data),
        "sha256_lf": sha256_bytes(lf_bytes(data)),
        "sha256_crlf": sha256_bytes(crlf_bytes(data)),
        "sha256_rows": corpus_digest(rows),
        "line_ending": line_ending(data),
        "rows": len(rows),
    }


# --------------------------------------------------------------- row access


def lookup(obj, path):
    """`meta.question`, `messages[-1].content`. Raises KeyError when absent."""
    cur = obj
    for part in path.split("."):
        match = PART_RE.fullmatch(part)
        if not match:
            raise KeyError(path)
        key, index = match.group(1), match.group(2)
        if not isinstance(cur, dict) or key not in cur:
            raise KeyError(path)
        cur = cur[key]
        if index is not None:
            if not isinstance(cur, list) or not cur:
                raise KeyError(path)
            cur = cur[int(index)]
    return cur


def first_value(row, paths, default=None):
    for path in paths:
        try:
            value = lookup(row, path)
        except (KeyError, IndexError):
            continue
        if isinstance(value, str) and value.strip():
            return value
    return default


def question_of(row, paths):
    """Metadata question first; otherwise the `Question:` line in the user turn.

    A row id or any other metadata is never a question: leak checks that ran on
    an id would report a clean corpus that was never compared.
    """
    value = first_value(row, paths, "")
    return value or messages_current_question(row)


def label_of(row, path):
    value = first_value(row, [path], "")
    return value


# --------------------------------------------------------------- questions


def normalize_question(text):
    return re.sub(r"[^a-z0-9 ]+", " ", str(text).lower()).strip()


def content_words(text):
    return {word for word in normalize_question(text).split() if word not in STOPWORDS}


def near_duplicate(left, right):
    """The repo's own rule (tests/test_eval_leakage.py): similar string AND shared content.

    A string-only test calls "what is replication" and "what is location" near
    duplicates; a content-only test calls "what is a data lake" and "data lake
    definition" different questions. Both gates must pass.

    The content floor is 0.6, not the 0.7 used for long eval questions: a
    one-word substitution inside a five-word question scores 4/6 = 0.667, so a
    0.7 floor would never fire on the short questions this corpus is full of.
    """
    first, second = normalize_question(left), normalize_question(right)
    if not first or not second:
        return False
    if difflib.SequenceMatcher(None, first, second).ratio() < NEAR_RATIO:
        return False
    one, two = content_words(left), content_words(right)
    if not one or not two:
        return False
    return len(one & two) / len(one | two) >= NEAR_CONTENT_JACCARD


def question_sha256(text):
    return sha256_bytes(normalize_question(text).encode("utf-8"))


def collect_questions(value, out, key="question"):
    """Every string under a `question`/`questions` key, at any depth."""
    if isinstance(value, dict):
        for name, child in value.items():
            folded = name.lower()
            if folded in ("question", "questions") and isinstance(child, str):
                out.append(child)
            elif folded in ("question", "questions") and isinstance(child, list):
                out.extend(x for x in child if isinstance(x, str))
            else:
                collect_questions(child, out, key)
    elif isinstance(value, list):
        for child in value:
            collect_questions(child, out, key)


def messages_questions(row):
    """Every `Question:` prefix in the user turns, earliest to latest."""
    out = []
    for message in row.get("messages", []):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        match = re.search(r"^Question:\s*(.+?)(?:\n\n|\Z)", str(message.get("content", "")),
                          re.S | re.M)
        if match and match.group(1).strip():
            out.append(match.group(1).strip())
    return out


def messages_current_question(row):
    questions = messages_questions(row)
    return questions[-1] if questions else ""


def messages_user_question(row):
    """Highlight-style rows: the question is the first line of the user turn."""
    for message in row.get("messages", []):
        if isinstance(message, dict) and message.get("role") == "user":
            text = str(message.get("content", ""))
            match = re.search(r"^Question:\s*(.+?)(?:\n\n|\Z)", text, re.S | re.M)
            return match.group(1) if match else text.strip()
    return ""


# --------------------------------------------------------------- row checks


def engine_prompt_prefixes():
    """The two engine system prompts, as prefixes. Empty when not importable."""
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        import prompt  # noqa: PLC0415 - optional, offline, constants only
    except Exception:
        return []
    prefixes = []
    for name in ("SYSTEM", "SYSTEM_ANSWER"):
        text = getattr(prompt, name, "") or ""
        if len(text) >= 40:
            prefixes.append(text[:40])
    return prefixes


def strings_of(value, skip_key=None):
    """Every string inside a nested value, except under `skip_key`."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for name, child in value.items():
            if name == skip_key:
                continue
            yield from strings_of(child, skip_key)
    elif isinstance(value, list):
        for child in value:
            yield from strings_of(child, skip_key)


def validate_rows(rows, spec, report):
    """Label hygiene. Every code here is a defect seen in this repo's corpora."""
    dataset = spec["dataset"]
    label_path = dataset.get("label_path", "messages[-1].content")
    question_paths = dataset.get("question_paths", ["meta.question", "meta.asked"])
    refusal = dataset.get("refusal", REFUSAL)
    untagged_sources = set(dataset.get("allow_untagged_sources", []))
    prompts = engine_prompt_prefixes()
    if not prompts:
        report.note("prompt_guard_unavailable", "prompt.py not importable; label/prompt check skipped")

    refusals = cited = untagged = 0
    seen_full = {}
    for index, row in enumerate(rows):
        messages = row.get("messages")
        if not isinstance(messages, list) or len(messages) < 2:
            report.fail("row_schema_invalid", "row %d has no messages list" % index)
            continue
        roles = [m.get("role") if isinstance(m, dict) else None for m in messages]
        if roles[-1] != "assistant" or any(r not in ("system", "user", "assistant") for r in roles):
            report.fail("row_schema_invalid", "row %d roles %r" % (index, roles))
            continue
        if any(not str(m.get("content", "")).strip() for m in messages):
            report.fail("row_schema_invalid", "row %d has an empty message" % index)
            continue

        label = label_of(row, label_path)
        user_text = " ".join(str(m.get("content", "")) for m in messages if m.get("role") == "user")
        question = question_of(row, question_paths)

        if label == refusal:
            refusals += 1
        elif label.strip() == refusal:
            report.fail("row_refusal_not_exact", "row %d label is the refusal plus %r"
                        % (index, label[len(refusal):][:40]))
        elif label.strip().startswith(refusal):
            report.fail("row_refusal_trailing_text", "row %d refusal keeps talking: %r"
                        % (index, label.strip()[len(refusal):][:40]))
        elif TAG_RE.search(label):
            cited += 1
        else:
            untagged += 1
            source = str(lookup_safe(row, "meta.source", ""))
            if source not in untagged_sources:
                report.fail("row_untagged_label", "row %d has no [Ch. N] tag and source %r "
                            "is not in allow_untagged_sources" % (index, source))

        if not question:
            report.fail("row_question_missing", "row %d yields no question for grouping" % index)
        elif "Question:" not in user_text and "Highlighted text:" not in user_text:
            # The stored keys are pre-canonicalization (`asked` is the raw
            # typing, `question` is a topic, the turn carries the canonical or
            # typo-repaired reading), so identity is not claimed here. What is
            # checked is that the turn carries a prompt at all.
            report.fail("row_prompt_missing", "row %d user turn carries no prompt marker" % index)

        if question and normalize_question(label) == normalize_question(question):
            report.fail("row_label_equals_question", "row %d label repeats the question" % index)

        for prefix in prompts:
            if prefix in label or prefix in user_text:
                report.fail("row_prompt_text", "row %d carries an engine system prompt" % index)
                break

        metadata = {key: value for key, value in row.items() if key != "messages"}
        for value in strings_of(metadata):
            if len(value) >= 40 and value.strip() == label.strip():
                report.fail("row_metadata_duplicates_label",
                            "row %d metadata is a copy of the label" % index)
                break

        full = sha256_bytes(canonical_json(messages).encode("utf-8"))
        seen_full.setdefault(full, []).append(index)

    duplicates = sum(len(v) - 1 for v in seen_full.values() if len(v) > 1)
    allowed = int(dataset.get("allowed_duplicate_rows", 0))
    if duplicates > allowed:
        report.fail("row_duplicate_full_input",
                    "%d duplicate message rows, allowed %d" % (duplicates, allowed))

    declared = dataset.get("rows")
    if declared is not None and declared != len(rows):
        report.fail("dataset_rows_mismatch", "declared %r, found %d" % (declared, len(rows)))
    declared_refusals = dataset.get("refusals")
    if declared_refusals is not None and declared_refusals != refusals:
        report.fail("dataset_refusals_mismatch", "declared %r, found %d"
                    % (declared_refusals, refusals))

    families = {}
    for row in rows:
        family = label_family(row, label_path)
        families[family] = families.get(family, 0) + 1
    return {"rows": len(rows), "refusals": refusals, "cited": cited,
            "untagged": untagged, "duplicate_rows": duplicates,
            "mask_families": families}


def label_family(row, label_path="messages[-1].content"):
    """The shape of the label that must be supervised. Derived from the data."""
    label = label_of(row, label_path)
    assistants = [m for m in row.get("messages", [])
                  if isinstance(m, dict) and m.get("role") == "assistant"]
    # History is serialized inside the user turn in this corpus; a prior
    # assistant message is the other shape. Both must prove coverage, and
    # neither may be supervised as a label.
    if len(assistants) > 1 or lookup_safe(row, "meta.turn1_a", None):
        return "history"
    if label == REFUSAL:
        return "refusal"
    if not TAG_RE.search(label or ""):
        return "gloss"
    return "answer"


def lookup_safe(obj, path, default):
    try:
        return lookup(obj, path)
    except (KeyError, IndexError):
        return default


# --------------------------------------------------------------- lineage


def verify_lineage(rows, parents, report):
    """A child corpus must be an ordered, exact subset of each parent it names."""
    details = []
    digests = [row_digest(r) for r in rows]
    for parent in parents:
        path = Path(parent["path"])
        if not path.exists():
            report.fail("lineage_missing", "parent %s does not exist" % path)
            continue
        facts = file_facts(path)
        if parent.get("sha256_crlf_historical") \
                and parent["sha256_crlf_historical"] != facts["sha256_crlf"]:
            report.fail("lineage_crlf_history_mismatch",
                        "%s: the historical CRLF digest does not reproduce" % path.name)
        for field in ("sha256_bytes", "sha256_rows"):
            if parent.get(field) and parent[field] != facts[field]:
                report.fail("lineage_sha256_mismatch", "%s %s: declared %s, found %s"
                            % (path.name, field, parent[field], facts[field]))
        parent_rows = read_jsonl(path.read_bytes())
        parent_digests = [row_digest(r) for r in parent_rows]
        relation = parent.get("relation", "order_preserving_subset")
        removed = []
        if relation == "order_preserving_subset":
            cursor = 0
            for digest in digests:
                while cursor < len(parent_digests) and parent_digests[cursor] != digest:
                    cursor += 1
                if cursor == len(parent_digests):
                    report.fail("lineage_relation_mismatch",
                                "%s is not an ordered subset of %s" % (path.name, parent["path"]))
                    break
                cursor += 1
            else:
                present = set(digests)
                removed = [r for r in parent_rows if row_digest(r) not in present]
        elif relation == "identical_content":
            if parent_digests != digests:
                report.fail("lineage_relation_mismatch", "%s content differs" % path.name)
        else:
            report.fail("lineage_relation_unknown", "relation %r" % relation)

        refusal = parent.get("refusal", REFUSAL)
        counts = {
            "cited": sum(1 for r in removed
                         if TAG_RE.search(label_of(r, "messages[-1].content", ) or "")),
            "refusal": sum(1 for r in removed
                           if (label_of(r, "messages[-1].content") or "") == refusal),
        }
        declared = parent.get("removed_rows")
        if declared:
            for key, value in declared.items():
                if counts.get(key) != value:
                    report.fail("lineage_removed_counts_mismatch",
                                "%s removed %s: declared %r, found %r"
                                % (path.name, key, value, counts.get(key)))
        details.append({"path": parent["path"], "relation": relation,
                        "parent_rows": len(parent_rows), "removed_rows": counts,
                        "sha256_bytes": facts["sha256_bytes"],
                        "sha256_rows": facts["sha256_rows"]})
    return details


# --------------------------------------------------------------- split


def census(rows, question_paths, dataset_path):
    """Read-only counts. It assigns nothing: the split is the corpus worker's."""
    families = {}
    questions = {}
    history = support = refusal = 0
    for row in rows:
        source = str(lookup_safe(row, "meta.source", "unknown"))
        families[source] = families.get(source, 0) + 1
        key = normalize_question(question_of(row, question_paths))
        questions[key] = questions.get(key, 0) + 1
        if lookup_safe(row, "meta.cited", None):
            support += 1
        if lookup_safe(row, "meta.turn1_a", None):
            history += 1
        if (label_of(row, "messages[-1].content") or "") == REFUSAL:
            refusal += 1
    return {
        "dataset": dataset_path,
        "rows": len(rows),
        "source_families": len(families),
        "families": families,
        "distinct_questions": len(questions),
        "duplicate_question_rows": sum(count - 1 for count in questions.values() if count > 1),
        "rows_with_support_keys": support,
        "rows_with_history": history,
        "refusals": refusal,
        "assignment": None,
        "note": "census only; the split is frozen by artifacts/harnesses/training_audit.py",
    }


def _ledger_index(path, report):
    """(source_path, line) -> ledger entry. Streams the 20 MB ledger once."""
    index = {}
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                report.fail("split_ledger_invalid", "ledger line %d is not JSON" % number)
                return {}
            key = (str(entry.get("source_path")), entry.get("line"))
            if key in index:
                report.fail("split_row_duplicate", "ledger repeats %s line %s" % key)
            index[key] = entry
    return index


def _ledger_lookup(index, dataset_path, line):
    for key, entry in index.items():
        if key[1] == line and (key[0] == dataset_path or key[0].endswith(dataset_path)
                               or dataset_path.endswith(key[0])):
            return entry
    return None


def verify_frozen_split(rows, spec, report):
    """Consume the audit's ledger + manifest. Never assign a row to a split."""
    frozen = spec.get("frozen_split") or {}
    ledger_path = Path(frozen.get("ledger", ""))
    audit_path = Path(frozen.get("manifest", ""))
    if not ledger_path.exists():
        report.fail("split_ledger_missing", "%s does not exist" % ledger_path)
        return None
    if not audit_path.exists():
        report.fail("split_audit_missing", "%s does not exist" % audit_path)
        return None
    for label, path in (("ledger", ledger_path), ("audit", audit_path)):
        declared = frozen.get("sha256_" + label)
        actual = sha256_bytes(path.read_bytes())
        if declared and declared != actual:
            report.fail("split_%s_sha256_mismatch" % label, "%s bytes changed" % label)

    audit = safe_json(audit_path)
    if audit.get("audit") != "training_audit":
        report.fail("split_audit_wrong_tool", "manifest audit field is %r" % audit.get("audit"))
    config = audit.get("config") or {}
    if config.get("random_assignment") != "none":
        report.fail("split_random_assignment", "the frozen split must not be random, found %r"
                    % config.get("random_assignment"))
    policy = str(config.get("split_policy") or "")
    if "component" not in policy.lower():
        report.fail("split_policy_not_component",
                    "the frozen split must group by connected components, found %r" % policy[:80])
    if "question" in policy.lower() and "family" not in policy.lower():
        report.fail("split_question_only", "a question-only split is not source-family disjoint")

    dataset = spec["dataset"]
    dataset_path = str(dataset.get("path"))
    role = str(frozen.get("role") or "derived_historical_train")
    index = _ledger_index(ledger_path, report)

    missing = duplicated = not_train = not_ready = 0
    families = {}
    components = {}
    for number, _row in enumerate(rows, 1):
        entry = _ledger_lookup(index, dataset_path, number)
        if entry is None:
            missing += 1
            continue
        if entry.get("split") != "train":
            not_train += 1
        if entry.get("role") != role:
            report.fail("split_role_mismatch", "line %d role is %r, expected %r"
                        % (number, entry.get("role"), role))
        if entry.get("train_ready") is not True:
            not_ready += 1
        families.setdefault(entry.get("family_id"), set()).add(entry.get("split"))
        if entry.get("component_id"):
            components.setdefault(entry["component_id"], set()).add(entry.get("split"))
    if missing:
        report.fail("split_rows_missing", "%d of %d corpus rows are absent from the ledger"
                    % (missing, len(rows)))
    if duplicated:
        report.fail("split_row_duplicate", "%d rows appear twice" % duplicated)
    if not_train:
        report.fail("split_rows_not_train", "%d rows are not marked train in the frozen ledger"
                    % not_train)
    if not_ready:
        report.fail("split_rows_not_train_ready",
                    "%d of %d rows are train_ready=false in the audit (mechanical or review pending)"
                    % (not_ready, len(rows)))

    straddling = [key for key, splits in families.items() if len(splits) > 1]
    if straddling:
        report.fail("split_family_straddles",
                    "%d families sit in more than one split" % len(straddling))

    # Components and findings are read from the whole ledger, not inferred from
    # the release rows: a dev row can share a component with a train row and
    # still be absent from `rows`.
    corpus_ids = {entry.get("id") for entry in
                  (_ledger_lookup(index, dataset_path, number) for number in range(1, len(rows) + 1))
                  if entry and entry.get("id")}
    all_components = {}
    for entry in index.values():
        if entry.get("component_id"):
            all_components.setdefault(entry["component_id"], []).append(entry)
    corpus_straddles = []
    pending_straddles = []
    for component, members in all_components.items():
        splits = {member.get("split") for member in members}
        if len(splits) < 2:
            continue
        ids = {member.get("id") for member in members}
        if ids & corpus_ids:
            corpus_straddles.append(component)
        else:
            pending_straddles.append(component)
    if corpus_straddles:
        report.fail("split_component_straddles",
                    "%d components containing release rows span splits" % len(corpus_straddles))
    if pending_straddles:
        report.note("split_pending_component_straddles",
                    "%d components outside the release rows span splits (review/train)"
                    % len(pending_straddles))

    declared_findings = {(item.get("code"), item.get("key"))
                         for item in spec.get("accepted_split_findings") or []}
    observed_findings = set()
    for finding in audit.get("split_findings") or []:
        splits = set(finding.get("splits") or [])
        ids = finding.get("ids") or {}
        pair = (finding.get("code"), finding.get("key"))
        touches_release = bool(set(ids.get("train") or []) & corpus_ids)
        if {"dev", "train"} <= splits and touches_release:
            observed_findings.add(pair)
            if pair not in declared_findings:
                report.fail("split_finding_undeclared",
                            "%s on %r crosses dev/train and touches release rows"
                            % (pair[0], pair[1]))
        else:
            report.note("split_pending_finding",
                        "%s on %r is outside the release rows (%s)"
                        % (pair[0], pair[1], ",".join(sorted(splits))))
    for pair in declared_findings - observed_findings:
        report.fail("split_finding_declared_stale",
                    "%s on %r no longer crosses dev/train" % pair)

    exposure = (audit.get("exposure") or {}).get(frozen.get("exposure_key") or "")
    if not exposure:
        report.fail("split_exposure_missing",
                    "the audit manifest has no exposure for %r" % frozen.get("exposure_key"))

    declared = spec.get("accepted_exposure") or {}
    exposure_ids = []
    measured = {}
    if exposure:
        measured = {key: exposure.get(key) for key in
                    ("dev_support_exposed", "dev_context_seen", "dev_source_unseen")}
        if declared != measured:
            report.fail("split_exposure_mismatch", "declared %r, audit measured %r"
                        % (declared, measured))
        if declared.get("dev_support_exposed") == 0 and measured.get("dev_support_exposed"):
            report.fail("split_exposure_claimed_clean", "exposure is not zero")
        for field, prefix in (("support_exposed_ids", "support"),
                              ("context_seen_ids", "context"),
                              ("exact_question_ids", "question")):
            for item in exposure.get(field) or []:
                exposure_ids.append("%s:%s" % (prefix, item))
    exposure_ids_sha256 = sha256_bytes("\n".join(sorted(exposure_ids)).encode("utf-8"))

    return {
        "ledger": str(ledger_path), "audit": str(audit_path),
        "sha256_ledger": sha256_bytes(ledger_path.read_bytes()),
        "sha256_audit": sha256_bytes(audit_path.read_bytes()),
        "role": role, "rows": len(rows), "train_ready": len(rows) - not_ready,
        "families": len(families), "components": len(components),
        "families_straddling": len(straddling), "splits": sorted({s for v in families.values() for s in v}),
        "exposure_key": frozen.get("exposure_key"),
        "exposure": {key: exposure.get(key) for key in
                     ("dev_support_exposed", "dev_context_seen", "dev_source_unseen")},
        "exposure_detail": exposure,
        "exposure_ids_sha256": exposure_ids_sha256,
        "findings_in_scope": len(observed_findings),
        "assignment": "read from the frozen ledger; this gate assigns nothing",
    }


# --------------------------------------------------------------- controls


def load_control(entry, report, required_names):
    """Return (metadata, payload). Reserved is hashes; development is a hash only."""
    path = Path(entry.get("path", ""))
    name = entry.get("name") or path.stem
    role = entry.get("role") or ("reserved" if entry.get("reserved") else "open")
    if role not in ("reserved", "development", "open"):
        report.fail("control_role_unknown", "%s has role %r" % (name, role))
        return None
    if not path.exists():
        report.fail("control_missing", "%s does not exist" % path)
        return None
    data = path.read_bytes()
    digest = sha256_bytes(data)
    declared = entry.get("sha256")
    if declared and declared != digest:
        report.fail("control_sha256_mismatch", "%s: declared %s, found %s"
                    % (path.name, declared, digest))
    required = name in required_names
    meta = {"name": name, "role": role, "path": str(path),
            "sha256_bytes": digest, "reserved": role == "reserved",
            "required": required}
    if required and role != "reserved":
        report.fail("required_control_not_protected",
                    "%s is required but supplied as %r, not a protected surface"
                    % (name, role))
        return None

    if role == "development":
        meta["questions"] = None
        meta["matching"] = "hash only; a legacy selection gate is not a protected surface"
        return meta, None

    if role == "reserved":
        hashes = [h for h in (entry.get("questions_sha256") or []) if isinstance(h, str)]
        meta["questions"] = len(hashes)
        meta["matching"] = "exact-normalized-hash only (text is never read)"
        if not required:
            report.note("control_not_required",
                        "%s is reserved but not in required_controls; no hash list enforced" % name)
            return meta, hashes
        count = entry.get("questions_count")
        if not isinstance(count, int) or count <= 0:
            report.fail("control_population_mismatch",
                        "%s declares no positive questions_count" % name)
        elif len(hashes) != count:
            report.fail("control_population_mismatch",
                        "%s declares %d questions and supplied %d hashes"
                        % (name, count, len(hashes)))
        wanted = sha256_bytes("\n".join(sorted(hashes)).encode("utf-8"))
        if entry.get("list_sha256") != wanted:
            report.fail("control_hash_list_unattested",
                        "%s list_sha256 does not cover the supplied hashes" % name)
        attestation = entry.get("attestation") or {}
        if attestation.get("complete") is not True or not attestation.get("reviewer") \
                or not attestation.get("method"):
            report.fail("control_attestation_missing",
                        "%s needs a complete attested hash list (reviewer, method)" % name)
        meta["attested_by"] = attestation.get("reviewer")
        return meta, hashes

    text = data.decode("utf-8")
    questions = []
    if entry.get("question_extraction") == "messages_user":
        questions = [messages_user_question(json.loads(line))
                     for line in text.splitlines() if line.strip()]
    elif path.suffix == ".jsonl":
        for line in text.splitlines():
            if line.strip():
                collect_questions(json.loads(line), questions)
    else:
        collect_questions(json.loads(text), questions)
    questions = [q for q in questions if q and q.strip()]
    if not questions:
        report.fail("control_questions_empty", "%s yielded no questions; schema drift?" % path.name)
    meta["questions"] = len(questions)
    return meta, questions


def leak_scan(rows, controls, spec, report, question_paths):
    train = {}
    grams = {}
    for index, row in enumerate(rows):
        variants = {question_of(row, question_paths)}
        variants.update(messages_questions(row))
        variants.update(first_value(row, [path], "") for path in question_paths)
        for question in variants:
            if not question or not question.strip():
                continue
            digest = question_sha256(question)
            train.setdefault(digest, []).append(index)
            grams.setdefault(digest, question)

    declared = {(item.get("control"), item.get("question_sha256"))
                for item in spec.get("expected_seen_collisions") or []}
    declared_near = {(item.get("control"), item.get("question_sha256"))
                     for item in spec.get("expected_seen_near") or []}
    seen_near = set()
    observed = set()
    summary = []
    def record(control, digest):
        observed.add((control, digest))
        if (control, digest) in declared:
            return 1
        report.fail("eval_leak_exact", "%s asks a training question (row %s)"
                    % (control, train[digest][:3]))
        return 0

    for meta, payload in controls:
        if payload is None:
            summary.append({"name": meta["name"], "role": meta["role"],
                            "checked_hashes": None, "near_checked": False,
                            "limit": "legacy selection gate: hashed only, not a protected surface"})
            continue
        if meta["reserved"]:
            hits = sorted({h for h in payload} & set(train))
            declared_hits = sum(record(meta["name"], digest) for digest in hits)
            summary.append({"name": meta["name"], "role": "reserved",
                            "checked_hashes": meta["questions"],
                            "exact_hits": len(hits) - declared_hits,
                            "declared_hits": declared_hits, "near_checked": False,
                            "attested_by": meta.get("attested_by"),
                            "limit": "reserved text is never read, so near-duplicates "
                                     "cannot be detected there; exact hashes only"})
            continue

        exact_hashes = {question_sha256(q) for q in payload}
        hits = sorted(exact_hashes & set(train))
        declared_hits = sum(record(meta["name"], digest) for digest in hits)
        near = 0
        for question in payload:
            if question_sha256(question) in exact_hashes & set(train):
                continue  # already counted exact above, declared or not
            if any(near_duplicate(question, other) for other in grams.values()):
                pair = (meta["name"], question_sha256(question))
                seen_near.add(pair)
                if pair in declared_near:
                    continue
                near += 1
                report.fail("eval_leak_near", "%s: %r overlaps a training question"
                            % (meta["name"], question[:60]))
        summary.append({"name": meta["name"], "role": "open",
                        "checked_questions": meta["questions"],
                        "exact_hits": len(hits) - declared_hits, "declared_hits": declared_hits,
                        "near_hits": near, "near_checked": True})

    for item in spec.get("expected_seen_collisions") or []:
        pair = (item.get("control"), item.get("question_sha256"))
        if pair not in observed:
            report.fail("declared_collision_stale", "%s no longer collides; remove the claim"
                        % (pair[0],))
    for item in spec.get("expected_seen_near") or []:
        pair = (item.get("control"), item.get("question_sha256"))
        if pair not in seen_near:
            report.fail("declared_near_stale", "%s no longer overlaps; remove the claim"
                        % (pair[0],))
    return summary


# --------------------------------------------------------------- manifest


def load_review_artifact(path, report):
    """The review FILE is authoritative. Unknown shapes fail closed."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(doc, dict):
        return None
    required = {"status", "reviewer", "criteria_version", "decisions", "binds"}
    if not required <= set(doc):
        return None
    decisions = doc.get("decisions") or {}
    for key in ("corpus", "split", "controls"):
        if str(decisions.get(key, "")).lower() not in ("accepted", "certified"):
            report.fail("source_review_decision_rejected",
                        "review decisions.%s is %r" % (key, decisions.get(key)))
    if str(doc.get("status", "")).lower() not in ("accepted", "certified"):
        report.fail("source_review_not_accepted", "review file status is %r" % doc.get("status"))
    if not doc.get("reviewer") or not doc.get("criteria_version"):
        report.fail("source_review_unattributed",
                    "the review file names no reviewer or criteria version")
    return doc


def verify_runner(spec, report):
    runner = spec.get("runner") or {}
    path = Path(runner.get("path", ""))
    deps = Path(runner.get("deps", ""))
    if not path.exists():
        report.fail("runner_missing", "%s does not exist" % path)
        return None
    if not deps.exists():
        report.fail("deps_missing", "%s does not exist" % deps)
        return None
    data, dep_data = path.read_bytes(), deps.read_bytes()
    if not runner.get("sha256"):
        report.fail("runner_sha256_missing", "runner.sha256 is required")
    elif runner["sha256"] != sha256_bytes(data):
        report.fail("runner_sha256_mismatch", "runner bytes differ from the reviewed hash")
    if not runner.get("deps_sha256"):
        report.fail("deps_sha256_missing", "runner.deps_sha256 is required")
    elif runner["deps_sha256"] != sha256_bytes(dep_data):
        report.fail("deps_sha256_mismatch", "deps bytes differ from the reviewed hash")
    return {"path": str(path), "sha256": sha256_bytes(data),
            "deps": str(deps), "deps_sha256": sha256_bytes(dep_data),
            "consumes_frozen_inputs": bool(runner.get("consumes_frozen_inputs")),
            "preflight_gate": bool(runner.get("preflight_gate"))}


def build_manifest(spec, root, report=None):
    report = report or Report()
    spec_status = str(spec.get("status", "")).lower()
    if spec_status != "certified":
        report.fail("spec_not_certified", "spec.status is %r; a draft cannot produce a package"
                    % spec.get("status"))

    dataset = spec.get("dataset") or {}
    path = Path(dataset.get("path", ""))
    if not path.exists():
        report.fail("dataset_missing", "%s does not exist" % path)
        return {"schema": MANIFEST_SCHEMA, "status": "blocked",
                "failures": report.failures, "notes": report.notes}, report

    facts = file_facts(path)
    for field in ("sha256_bytes", "sha256_rows"):
        wanted = dataset.get(field)
        if wanted and wanted != facts[field]:
            report.fail("dataset_sha256_mismatch", "%s: declared %s, found %s"
                        % (field, wanted, facts[field]))
    if dataset.get("line_ending") and dataset["line_ending"] != facts["line_ending"]:
        report.fail("dataset_line_ending_mismatch", "declared %r, found %r"
                    % (dataset["line_ending"], facts["line_ending"]))
    if dataset.get("sha256_crlf_historical") \
            and dataset["sha256_crlf_historical"] != facts["sha256_crlf"]:
        report.fail("dataset_crlf_history_mismatch", "the historical CRLF digest does not reproduce")

    rows = read_jsonl(path.read_bytes())
    question_paths = dataset.get("question_paths", ["meta.question", "meta.asked"])
    row_facts = validate_rows(rows, spec, report)

    lineage = verify_lineage(rows, spec.get("lineage") or [], report)

    split_facts = verify_frozen_split(rows, spec, report)
    runner_facts = verify_runner(spec, report)
    recipe_digest = sha256_bytes(canonical_json(spec.get("recipe") or {}).encode("utf-8"))

    review = spec.get("source_review") or {}
    review_path = Path(review.get("path", ""))
    review_facts = None
    review_doc = None
    if not review_path.exists():
        report.fail("source_review_missing", "%s does not exist" % review_path)
    else:
        review_facts = {"path": str(review_path),
                        "sha256_bytes": sha256_bytes(review_path.read_bytes())}
        if review.get("sha256") and review_facts["sha256_bytes"] != review["sha256"]:
            report.fail("source_review_sha256_mismatch", "review bytes changed")
        review_doc = load_review_artifact(review_path, report)
        if review_doc is None:
            report.fail("source_review_format_unknown",
                        "%s does not carry status/reviewer/criteria_version/decisions/binds"
                        % review_path.name)

    # A signature that does not name the bytes it approved is not a review.
    binds = (review_doc or {}).get("binds") or {}
    expected = {
        "dataset_sha256": facts["sha256_bytes"],
        "rows": len(rows),
        "recipe_sha256": recipe_digest,
        "ledger_sha256": (split_facts or {}).get("sha256_ledger"),
        "audit_manifest_sha256": (split_facts or {}).get("sha256_audit"),
        "exposure": (split_facts or {}).get("exposure"),
        "exposure_ids_sha256": (split_facts or {}).get("exposure_ids_sha256"),
        "tokenizer_config_sha256": (spec.get("recipe") or {}).get("tokenizer_config_sha256"),
        "runner_sha256": runner_facts.get("sha256") if runner_facts else None,
        "deps_sha256": runner_facts.get("deps_sha256") if runner_facts else None,
    }
    for field, value in expected.items():
        if binds.get(field) != value:
            report.fail("review_not_bound",
                        "binds.%s is %r, measured %r" % (field, binds.get(field), value))
    if review_doc is not None:
        for field in ("status", "reviewer", "criteria_version"):
            if str(review.get(field, "")) != str(review_doc.get(field, "")):
                report.fail("source_review_spec_mismatch",
                            "spec.%s %r, review file %r"
                            % (field, review.get(field), review_doc.get(field)))
        if (review.get("binds") or {}) != (review_doc.get("binds") or {}):
            report.fail("source_review_spec_mismatch",
                        "spec binds differ from the review file's binds")
    if not review.get("reviewer") or not review.get("criteria_version"):
        report.fail("source_review_unattributed",
                    "reviewer and criteria_version are both required")

    required = [str(name) for name in spec.get("required_controls") or []]
    controls = []
    for entry in spec.get("evaluation_controls") or []:
        loaded = load_control(entry, report, set(required))
        if loaded:
            controls.append(loaded)
    present = {meta["name"] for meta, _payload in controls}
    for name in required:
        if name not in present:
            report.fail("required_control_missing",
                        "required protected surface %r is absent from evaluation_controls" % name)
    inventory = spec.get("protected_inventory") or {}
    inventory_names = [str(name) for name in inventory.get("names") or []]
    if not required and not inventory_names:
        if inventory.get("status") == "none-attested" and inventory.get("reviewer") \
                and inventory.get("no_heldout_claim") is True:
            report.note("protected_inventory_none",
                        "explicitly attested empty inventory by %s" % inventory.get("reviewer"))
        else:
            report.fail("required_inventory_empty",
                        "no required protected surface and no attested empty inventory")
    for name in inventory_names:
        if name not in required:
            report.fail("protected_inventory_incomplete",
                        "inventory names %r but required_controls omits it" % name)
    leak_summary = leak_scan(rows, controls, spec, report, question_paths)

    recipe = spec.get("recipe") or {}
    for field in REQUIRED_RECIPE:
        if recipe.get(field) in (None, "", []):
            report.fail("recipe_missing", "recipe.%s is required" % field)
    for field in ("base_revision", "tokenizer_revision"):
        value = str(recipe.get(field, ""))
        if value and not COMMIT_RE.match(value):
            report.fail("recipe_unpinned", "recipe.%s must be a 40-hex commit, found %r"
                        % (field, value))
    for field in ("tokenizer_chat_template_sha256",):
        value = str(recipe.get(field, ""))
        if value and not SHA_RE.match(value):
            report.fail("recipe_unpinned", "recipe.%s must be a sha256" % field)
    validate_artifact_pins(recipe, report)

    families = {}
    for row in rows:
        source = str(lookup_safe(row, "meta.source", "unknown"))
        families[source] = families.get(source, 0) + 1

    runner_ready = bool(runner_facts and runner_facts["consumes_frozen_inputs"]
                        and runner_facts["preflight_gate"])
    if not report.ok:
        status = "blocked"
    elif runner_ready:
        status = "ready-to-launch"
    else:
        status = "blocked_runner"
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "release_id": spec.get("release_id"),
        "generator": "artifacts/colab/prepare_training.py",
        "status": status,
        "failures": report.failures,
        "notes": report.notes,
        "inputs": {
            "dataset": {"path": facts["path"], "bytes": facts["bytes"],
                        "sha256_bytes": facts["sha256_bytes"],
                        "sha256_lf": facts["sha256_lf"],
                        "sha256_crlf": facts["sha256_crlf"],
                        "sha256_rows": facts["sha256_rows"],
                        "line_ending": facts["line_ending"],
                        "row_facts": row_facts},
            "lineage": lineage,
            "source_review": review_facts,
            "split": split_facts,
            "runner": runner_facts,
            "recipe_sha256": recipe_digest,
            "evaluation_controls": [c for c in (leak_summary or [])],
        },
        "rows": {"families": families,
                 "mask_families": row_facts["mask_families"]},
        "split_rule": {
            "train": "rows the frozen audit ledger marks train; this gate assigns nothing",
            "dev-internal": "diagnostic dev slice from the frozen ledger; declared collisions and "
                             "support exposure are listed, it is not unseen and not a selection holdout",
            "dev-external": "staged diagnostic items; may be seen, never called unseen",
            "reserved": "sealed/locked/final sets; hashed only, never selected on, never quoted",
        },
        "recipe": recipe,
        "runtime": spec.get("runtime") or {},
        "stop_checks": spec.get("stop_checks") or ["answer", "refusal", "history"],
        "token_histogram": {"status": "unmeasured", "source": "run preflight"},
        "mask_policy": {"instruction_part": recipe.get("instruction_part"),
                        "response_part": recipe.get("response_part"),
                        "assistant_eos": recipe.get("assistant_eos", "<|im_end|>"),
                        "require_single_eos": True,
                        "negative_labels_must_be_masked": True},
    }
    return manifest, report


def safe_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


# --------------------------------------------------------------- run report


def detect_completion_defects(text, eos="<|im_end|>", max_new_tokens_hit=False):
    """Mechanical checks on one generated completion. Independent codes."""
    defects = []
    body = str(text)
    cut = body.split(eos, 1)[0] if eos in body else body
    if not cut.strip():
        defects.append("empty")
    if eos not in body and not max_new_tokens_hit:
        defects.append("missing_stop")
    if max_new_tokens_hit:
        defects.append("cap_hit")
    if THINK_RE.search(cut):
        defects.append("thinking_leak")
    words = normalize_question(cut).split()
    if len(words) >= REPEAT_NGRAM * 4:
        grams = [" ".join(words[i:i + REPEAT_NGRAM])
                 for i in range(len(words) - REPEAT_NGRAM + 1)]
        repeated = sum(grams.count(gram) for gram in set(grams) if grams.count(gram) > 1)
        if repeated / len(grams) >= REPEAT_RATIO:
            defects.append("repetition")
    stripped = cut.strip()
    if stripped.startswith(REFUSAL) and stripped != REFUSAL:
        defects.append("refusal_trailing")
    return defects


def verify_run(report_obj, manifest, report):
    if manifest.get("status") != "ready-to-launch":
        report.fail("manifest_not_ready", "manifest status %r" % manifest.get("status"))
        return {"losses": []}
    if report_obj.get("schema") != RUN_SCHEMA:
        report.fail("run_schema", "expected %s" % RUN_SCHEMA)

    dataset = report_obj.get("dataset") or {}
    want = manifest["inputs"]["dataset"]
    for field in ("sha256_rows", "rows"):
        got = dataset.get(field)
        expected = want.get("sha256_rows") if field == "sha256_rows" else want["row_facts"]["rows"]
        if got != expected:
            report.fail("run_dataset_mismatch", "%s: expected %r, found %r"
                        % (field, expected, got))

    recipe = manifest["recipe"]
    run_recipe = report_obj.get("recipe") or {}
    for field in ("base_model", "seed", "epochs", "lora_r", "lora_alpha"):
        if run_recipe.get(field) != recipe.get(field):
            report.fail("run_recipe_mismatch", "%s: expected %r, found %r"
                        % (field, recipe.get(field), run_recipe.get(field)))
    if str(run_recipe.get("base_revision")) != str(recipe.get("base_revision")):
        report.fail("run_recipe_mismatch", "base_revision differs")
    if report_obj.get("chat_template_sha256") != recipe.get("tokenizer_chat_template_sha256"):
        report.fail("run_template_mismatch", "chat template hash differs")

    tokens = report_obj.get("tokens") or {}
    if not isinstance(tokens.get("max"), int):
        report.fail("run_tokens_unmeasured", "tokens.max is required")
    elif tokens["max"] > recipe.get("max_seq_length", 0):
        report.fail("run_truncation", "max token length %d exceeds max_seq_length %r"
                    % (tokens["max"], recipe.get("max_seq_length")))
    if tokens.get("truncated_rows"):
        report.fail("run_truncation", "%d rows truncated" % tokens["truncated_rows"])

    masks = report_obj.get("masks") or {}
    required_masks = ("assistant_label_tokens", "user_system_supervised_tokens",
                      "eos_in_supervised", "negative_label_supervised_tokens",
                      "spot_checks")
    missing_masks = [key for key in required_masks if key not in masks]
    if missing_masks:
        report.fail("run_masks_unmeasured",
                    "mask report is missing %s" % ", ".join(missing_masks))
    if masks.get("assistant_label_tokens") in (None, 0):
        report.fail("run_label_coverage_missing",
                    "no assistant label tokens were supervised")
    if masks.get("user_system_supervised_tokens") not in (0,):
        report.fail("run_mask_leak", "user/system tokens are supervised: %r"
                    % masks.get("user_system_supervised_tokens"))
    expected_families = (manifest.get("rows") or {}).get("mask_families") or {}
    family_rows = masks.get("family_rows") or {}
    missing_families = sorted(set(expected_families) - set(family_rows))
    if missing_families:
        report.fail("run_family_missing",
                    "no mask proof for families %s" % ", ".join(missing_families))
    for family, count in expected_families.items():
        if family in family_rows and family_rows[family] != count:
            report.fail("run_family_count_mismatch",
                        "%s: report %r rows, dataset %d" % (family, family_rows[family], count))
    family_eos = masks.get("family_eos_rows") or {}
    for family, count in family_rows.items():
        if family_eos.get(family) != count:
            report.fail("run_eos_count",
                        "%s: %r rows carry an EOS, %r rows expected"
                        % (family, family_eos.get(family), count))
    if masks.get("prior_assistant_supervised_tokens") not in (0,):
        report.fail("run_prior_history_supervised",
                    "prior assistant turns are supervised: %r"
                    % masks.get("prior_assistant_supervised_tokens"))
    eos = masks.get("eos_in_supervised") or {}
    if not eos:
        report.fail("run_masks_unmeasured", "eos_in_supervised is empty")
    for name, count in eos.items():
        if count != 1:
            report.fail("run_eos_count", "%s supervised %r copies of the assistant EOS" % (name, count))
    negative = masks.get("negative_label_supervised_tokens") or {}
    if not negative:
        report.fail("run_masks_unmeasured", "negative_label_supervised_tokens is empty")
    for name, count in negative.items():
        if count != 0:
            report.fail("run_mask_leak", "%s carries %r supervised tokens" % (name, count))
    spots = masks.get("spot_checks") or []
    if not spots:
        report.fail("run_masks_unmeasured", "no mask spot checks were reported")
    elif not all(m.get("supervised_equals_label") for m in spots):
        report.fail("run_mask_spot_check", "a supervised span does not equal its label")

    preflight = report_obj.get("preflight") or {}
    if not preflight:
        report.fail("run_preflight_missing", "no preflight section in the run report")
    else:
        if preflight.get("measured_before_train") is not True or preflight.get("status") != "pass":
            report.fail("run_preflight_not_before_train",
                        "preflight was not measured and passed before training")
        rows_expected = (manifest.get("inputs", {}).get("dataset", {})
                         .get("row_facts", {}).get("rows"))
        proof = {
            "dataset_sha256": manifest["inputs"]["dataset"]["sha256_bytes"],
            "recipe_sha256": manifest["inputs"].get("recipe_sha256"),
            "chat_template_sha256": manifest["recipe"].get("tokenizer_chat_template_sha256"),
        }
        for field, value in proof.items():
            if preflight.get(field) != value:
                report.fail("run_preflight_incomplete",
                            "preflight.%s is %r, expected %r"
                            % (field, preflight.get(field), value))
        runtime_tokenizer = str(preflight.get("tokenizer_config_sha256", ""))
        approved_tokenizer = str(manifest["recipe"].get("tokenizer_config_sha256", ""))
        if not SHA_RE.match(runtime_tokenizer):
            report.fail("run_preflight_incomplete",
                        "preflight.tokenizer_config_sha256 is not a sha256")
        elif runtime_tokenizer != approved_tokenizer:
            report.fail("run_tokenizer_config_mismatch",
                        "runtime tokenizer_config sha256 %s, approved %s"
                        % (runtime_tokenizer[:12], approved_tokenizer[:12]))
        runtime_assets = preflight.get("tokenizer_assets_sha256")
        approved_assets = manifest["recipe"].get("tokenizer_assets_sha256")
        if not isinstance(runtime_assets, dict) or not runtime_assets:
            report.fail("run_preflight_incomplete",
                        "preflight.tokenizer_assets_sha256 is not a measured file map")
        elif runtime_assets != approved_assets:
            report.fail("run_tokenizer_asset_mismatch",
                        "runtime tokenizer assets %r, approved %r"
                        % (sorted(runtime_assets), sorted(approved_assets or {})))
        if preflight.get("rows_checked") != rows_expected \
                or preflight.get("mask_rows_checked") != rows_expected:
            report.fail("run_preflight_incomplete",
                        "preflight checked %r/%r rows, dataset has %r"
                        % (preflight.get("rows_checked"),
                           preflight.get("mask_rows_checked"), rows_expected))
        measured_max = preflight.get("max_tokens")
        if not isinstance(measured_max, int) or measured_max <= 0:
            report.fail("run_preflight_incomplete", "preflight.max_tokens is not measured")
        elif measured_max > manifest["recipe"].get("max_seq_length", 0):
            report.fail("run_truncation", "preflight max %d exceeds max_seq_length" % measured_max)
        if preflight.get("truncated_rows") not in (0,):
            report.fail("run_truncation", "preflight truncated %r rows"
                        % preflight.get("truncated_rows"))

    if report_obj.get("mode") == "preflight-only":
        report.fail("run_train_not_proven",
                    "preflight-only report: masks and lengths are measured, training is not")
        return {"status": "preflight-only", "losses": []}

    kinds = {check.get("kind") for check in report_obj.get("stop_checks") or []}
    for required_kind in manifest.get("stop_checks") or []:
        if required_kind not in kinds:
            report.fail("run_stop_check_missing", "no %r stop check" % required_kind)
    for check in report_obj.get("stop_checks") or []:
        for defect in detect_completion_defects(
                check.get("text", ""),
                max_new_tokens_hit=bool(check.get("max_new_tokens_hit"))):
            report.fail("run_stop_check_" + defect,
                        "%s: %r" % (check.get("kind"), str(check.get("text"))[:80]))

    runtime = report_obj.get("runtime") or {}
    for field in ("gpu", "python", "torch", "transformers", "trl", "unsloth"):
        if not runtime.get(field):
            report.fail("run_runtime_unrecorded", "runtime.%s is empty" % field)

    losses = (report_obj.get("losses") or {}).get("epochs") or []
    if not losses:
        report.fail("run_losses_missing", "no epoch losses recorded")
    for entry in losses:
        if not isinstance(entry.get("train"), (int, float)):
            report.fail("run_losses_missing", "epoch %r has no train loss" % entry.get("epoch"))

    artifacts = report_obj.get("artifacts") or {}
    for field in ("lora_sha256", "gguf_sha256"):
        if not SHA_RE.match(str(artifacts.get(field, ""))):
            report.fail("run_artifact_hash_missing", "artifacts.%s is not a sha256" % field)
    return {"losses": losses}


# --------------------------------------------------------------- launch plan


def launch_plan(manifest, spec):
    session = str(spec.get("session", "askbook-train"))
    runner = str((spec.get("runner") or {}).get("path", "artifacts/colab/qwen35_train_v2.py"))
    deps = str((spec.get("runner") or {}).get("deps", "artifacts/colab/install_train_deps.py"))
    gpu = str((spec.get("runtime") or {}).get("gpu", "A100"))
    dataset = manifest["inputs"]["dataset"]["path"]
    remote_dataset = "/content/" + Path(dataset).name
    timeout = int((spec.get("runtime") or {}).get("exec_timeout_s", 14400))
    env = {
        "EXPECTED_ROWS": str(manifest["inputs"]["dataset"]["row_facts"]["rows"]),
        "EXPECT_DATA_SHA256": manifest["inputs"]["dataset"]["sha256_bytes"],
    }
    env_args = " ".join("--env %s=%s" % (key, value) for key, value in sorted(env.items()))
    consuming = bool((spec.get("runner") or {}).get("consumes_frozen_inputs")) \
        and bool((spec.get("runner") or {}).get("preflight_gate"))
    runnable = bool(consuming and manifest.get("status") == "ready-to-launch")
    return {
        "runnable": runnable,
        "blocked_reason": None if runnable else (
            "the runner does not consume the frozen manifest/split/pins or does not gate on "
            "preflight before trainer.train; these commands are illustrative"),
        "cli": {"package": "google-colab-cli",
                "version": (spec.get("runtime") or {}).get("colab_cli_version"),
                "session": session, "gpu": gpu},
        "why_not_ephemeral": [
            "`colab run` defaults to a 30 s exec timeout and releases the VM when the script ends.",
            "A finetune cannot finish in that budget, and the GGUF would be lost before download.",
        ],
        "commands": [
            ["colab", "new", "-s", session, "--gpu", gpu],
            ["colab", "exec", "-s", session, "-f", deps, "--timeout", str(min(timeout, 1800))],
            ["colab", "upload", "-s", session, dataset, remote_dataset],
            ["colab", "upload", "-s", session, runner, "/content/" + Path(runner).name],
            ["colab", "exec", "-s", session, "-f", runner, "--timeout", str(timeout), *env_args.split()],
            ["colab", "download", "-s", session,
             "/content/<export>_q4_k_m.zip", str(Path(spec.get("download_dir", "artifacts/runs/data-release/downloads")) / "<export>_q4_k_m.zip")],
            ["colab", "download", "-s", session, "/content/training-run-report.json",
             str(Path(spec.get("download_dir", "artifacts/runs/data-release/downloads")) / "training-run-report.json")],
            ["colab", "stop", "-s", session],
        ],
        "cost": "Colab bills compute units by accelerator and runtime; check `colab usage` "
                "before and after. No price is asserted here.",
        "after_download": [
            "python artifacts/colab/prepare_training.py --verify-run <report>.json "
            "--manifest <out>/manifest.json",
            "Only then import the GGUF and run the gates (battery, pins, sealed, hard-mt).",
        ],
    }


# --------------------------------------------------------------- CLI


def load_spec(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_spec(spec_path, out_dir):
    spec = load_spec(spec_path)
    manifest, report = build_manifest(spec, Path.cwd())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n",
                                       encoding="utf-8")
    if report.ok:
        (out / "launch-plan.json").write_text(
            json.dumps(launch_plan(manifest, spec), indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
    payload = {"status": manifest["status"], "failures": report.failures,
               "notes": report.notes, "manifest": str(out / "manifest.json")}
    print(json.dumps(payload, indent=1, sort_keys=True))
    return 0 if report.ok else 2


def run_census(dataset, question_paths):
    """Counts only. Deliberately returns no assignment: the split is frozen elsewhere."""
    rows = read_jsonl(Path(dataset).read_bytes())
    print(json.dumps(census(rows, question_paths, dataset), indent=1, sort_keys=True))
    return 0


def run_verify_run(run_path, manifest_path):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    report_obj = json.loads(Path(run_path).read_text(encoding="utf-8"))
    report = Report()
    details = verify_run(report_obj, manifest, report)
    print(json.dumps({"status": "pass" if report.ok else "fail",
                      "failures": report.failures, "details": details},
                     indent=1, sort_keys=True))
    return 0 if report.ok else 2


def hygiene_report(source_path=None):
    """Imports and literals this module must never gain.

    The scan skips its own function bodies, so the banned words can be named
    here without the check flagging itself.
    """
    tree = ast.parse(Path(source_path or __file__).read_bytes())
    own = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ("self_check", "hygiene_report"):
            own.update(id(child) for child in ast.walk(node))
    banned = {"socket", "urllib", "http", "requests", "subprocess", "ftplib", "ssl"}
    imported = set()
    for node in ast.walk(tree):
        if id(node) in own:
            continue
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    literals = {node.value for node in ast.walk(tree)
                if id(node) not in own and isinstance(node, ast.Constant)
                and isinstance(node.value, str)}
    flagged = sorted(s for s in literals
                     if "nekohon" in s or "smallbook" in s or "ollama" in s
                     or s.startswith("http://") or s.startswith("https://"))
    return {"banned_imports": sorted(imported & banned), "disallowed_literals": flagged}


def self_check():
    """Fast invariants; the real gate is tests/test_prepare_training.py."""
    checks = []
    rows = [{"messages": [{"role": "user", "content": "Question: What is a watermark?\n\nPassages: x"},
                          {"role": "assistant", "content": "[Ch. 8] \"A watermark is a threshold.\""}],
             "meta": {"question": "What is a watermark?", "source": "synthetic"}}]
    data = b'{"a":1}\n{"b":2}\n'
    checks.append(("crlf_roundtrip", crlf_bytes(lf_bytes(crlf_bytes(data))) == crlf_bytes(data)))
    checks.append(("lf_differs_from_crlf", sha256_bytes(data) != sha256_bytes(crlf_bytes(data))))
    checks.append(("row_digest_stable", row_digest(rows[0]) == row_digest(json.loads(canonical_json(rows[0])))))
    checks.append(("lookup_negative_index", lookup(rows[0], "messages[-1].content").startswith("[Ch. 8]")))
    report_facts = census(rows, ["meta.question"], "x.jsonl")
    checks.append(("census_assigns_nothing", report_facts.get("assignment") is None))
    checks.append(("census_counts_rows", report_facts["rows"] == 1))
    checks.append(("clean_completion", detect_completion_defects('ok <|im_end|>') == []))
    checks.append(("thinking_leak_detected",
                   "thinking_leak" in detect_completion_defects("<|im_start|>assistant hi <|im_end|>")))
    checks.append(("cap_hit_detected", "cap_hit" in detect_completion_defects("partial", max_new_tokens_hit=True)))
    hygiene = hygiene_report()
    checks.append(("no_network_or_subprocess", not hygiene["banned_imports"]))
    checks.append(("no_model_identifiers", not hygiene["disallowed_literals"]))
    failed = [name for name, ok in checks if not ok]
    print(json.dumps({"checks": len(checks), "failed": failed,
                      "status": "SELF-CHECK OK" if not failed else "SELF-CHECK FAILED"},
                     indent=1, sort_keys=True))
    return 0 if not failed else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline training-release gate and Colab plan.")
    parser.add_argument("--spec", help="release spec JSON")
    parser.add_argument("--out", default="artifacts/runs/data-release/training-package",
                        help="where manifest.json (and launch-plan.json when ready) are written")
    parser.add_argument("--census", action="store_true",
                        help="print row/family/exposure counts; assigns nothing")
    parser.add_argument("--dataset", help="dataset path for --census")
    parser.add_argument("--question-paths", default="meta.question,meta.asked")
    parser.add_argument("--verify-run", help="training run report JSON to check against a manifest")
    parser.add_argument("--manifest", help="manifest.json for --verify-run")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args(argv)

    if args.self_check:
        return self_check()
    if args.verify_run:
        if not args.manifest:
            parser.error("--verify-run needs --manifest")
        return run_verify_run(args.verify_run, args.manifest)
    if args.census:
        if not args.dataset:
            parser.error("--census needs --dataset")
        paths = [p.strip() for p in args.question_paths.split(",") if p.strip()]
        return run_census(args.dataset, paths)
    if args.spec:
        return run_spec(args.spec, args.out)
    parser.print_help()
    return 3


if __name__ == "__main__":
    sys.exit(main())
