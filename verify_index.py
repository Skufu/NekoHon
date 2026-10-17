"""Audit the index's stored vectors. Read-only.

Non-finite / all-zero / width-drift / missing vectors, every offender named.
Exit 0 when clean, exit 1 when dirty. Stdlib only; no model calls.
"""

import argparse
import math
from collections import Counter
from pathlib import Path

from retrieve import INDEX, load_index

AXES = ("nonfinite", "zero_norm", "dim_drift")


def _label(kind, record, position):
    name = record.get("chunk_id") if kind == "chunk" else record.get("id")
    return f"{kind} {name}" if name else f"{kind} #{position}"


def audit(index):
    """A report dict; every problem list is empty on a clean index."""
    rows = [
        ("chunk", record, position)
        for position, record in enumerate(index.get("chunks", []))
    ]
    rows += [
        ("figure", record, position)
        for position, record in enumerate(index.get("figures", []))
    ]
    vectors = [
        (kind, record, position, record.get("embedding"))
        for kind, record, position in rows
        if isinstance(record.get("embedding"), list)
    ]
    declared = index.get("embedding_dims")
    report = {
        "embedder": index.get("embedder"),
        "declared_dims": declared,
        "no_declared_dims": bool(vectors) and not declared,
        "chunks": len(index.get("chunks", [])),
        "figures": len(index.get("figures", [])),
        "vectors": len(vectors),
        "widths": dict(Counter(len(vector) for _, _, _, vector in vectors)),
        "missing": [
            _label(kind, record, position)
            for kind, record, position in rows
            if not isinstance(record.get("embedding"), list)
        ],
        "nonfinite": [],
        "zero_norm": [],
        "dim_drift": [],
    }
    for kind, record, position, vector in vectors:
        label = _label(kind, record, position)
        if not vector or any(not math.isfinite(value) for value in vector):
            report["nonfinite"].append(label)
        if vector and all(value == 0.0 for value in vector):
            report["zero_norm"].append(label)
        if declared and len(vector) != declared:
            report["dim_drift"].append(f"{label} ({len(vector)} wide)")
    return report


def exit_code(report):
    """0 when clean, 1 when any stored vector is bad or missing.

    Matches the module docstring and preflight.audit_clean: a chunk or figure
    with no vector is dirty, not a warning the CLI can ignore.
    """
    if report["missing"] or report["no_declared_dims"]:
        return 1
    if any(report[axis] for axis in AXES):
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Audit the index's stored vectors. Read-only."
    )
    parser.add_argument("--index", default=str(INDEX))
    parser.add_argument("--book-id", default=None, help="Book ID to audit")
    args = parser.parse_args()

    if args.book_id is not None and args.index == str(INDEX):
        book_index = INDEX.parent / f"index.{args.book_id}.json"
        if book_index.exists():
            index_path = book_index
        else:
            index_path = INDEX
    else:
        index_path = Path(args.index)

    report = audit(load_index(index_path))
    print(f"embedder {report['embedder']} declared_dims {report['declared_dims']}")
    print(
        f"chunks {report['chunks']} figures {report['figures']} "
        f"vectors {report['vectors']}"
    )
    print(f"vector_lengths {report['widths']}")
    print(f"missing_vectors {len(report['missing'])} {report['missing'][:5]}")
    for axis in AXES:
        print(f"{axis}_vectors {len(report[axis])} {report[axis][:5]}")
    code = exit_code(report)
    if code:
        print("dirty")
        raise SystemExit(code)
    print("clean")


if __name__ == "__main__":
    main()
