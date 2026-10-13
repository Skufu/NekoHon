"""Preflight: is this machine ready to run the engine? Read-only, stdlib.

Run this before anything else, and again whenever something stops working:

    python preflight.py        # Windows
    python3 preflight.py       # macOS

Checks, in order: Python version, the EPUB, the index, Ollama, the two
models, and the index's stored vectors. Prints the first thing to do next.
Exit 0 when ready to serve, 1 otherwise. No model call, no server, no writes.

Every path and model name comes from the engine's own constants, so this
script cannot drift from the app. Works unchanged on Windows and macOS.
"""

import json
import sys
import urllib.error
import urllib.request

from ingest import BOOK, ROOT
from prompt import ANSWER_MODEL
from retrieve import DEFAULT_EMBEDDER, INDEX, load_index
from server import ollama_up
from verify_index import AXES, audit

MINIMUM_PYTHON = (3, 9)
TAGS_URL = "http://127.0.0.1:11434/api/tags"


def version_ok(version, minimum=MINIMUM_PYTHON):
    return version >= minimum


def model_present(names, wanted):
    """A wanted name matches itself, or any tag of it ('name:tag')."""
    return any(name == wanted or name.startswith(wanted + ":") for name in names)


def audit_clean(report):
    """True when verify_index.audit's report has nothing to flag."""
    if report.get("no_declared_dims") or report.get("missing"):
        return False
    return not any(report.get(axis) for axis in AXES)


def ollama_models(timeout=2.0):
    """Tag names on the local Ollama, or None when it cannot be asked."""
    try:
        with urllib.request.urlopen(TAGS_URL, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    return [model.get("name", "") for model in body.get("models", [])]


def next_steps(state):
    """The ordered actions left, one per line. Empty means ready to serve."""
    steps = []
    if not state["python_ok"]:
        steps.append(
            f"install Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}+ "
            "(macOS: brew install python@3.12)"
        )
    if not state["book"]:
        steps.append(f"put the EPUB at {BOOK.relative_to(ROOT)}")
    if not state["index"]:
        steps.append("build the index: python ingest.py, then python retrieve.py")
    if not state["ollama"]:
        steps.append("start Ollama, then run this script again")
    else:
        for name in state["missing_models"]:
            steps.append(f"pull the model: ollama pull {name}")
    if state["audit_clean"] is False:
        steps.append("the index failed its vector audit; re-run python retrieve.py")
    if not steps:
        steps.append("ready: python server.py, then open http://127.0.0.1:8000/")
    return steps


def main():
    version = (sys.version_info.major, sys.version_info.minor)
    state = {
        "python_ok": version_ok(version),
        "book": BOOK.is_file(),
        "index": INDEX.is_file(),
        "ollama": ollama_up(),
        "missing_models": [],
        "audit_clean": None,
    }
    tags = None
    if state["ollama"]:
        tags = ollama_models()
        if tags is None:
            state["ollama"] = False
        else:
            state["missing_models"] = [
                name
                for name in (DEFAULT_EMBEDDER, ANSWER_MODEL)
                if not model_present(tags, name)
            ]
    if state["index"]:
        try:
            report = audit(load_index(INDEX))
        except (OSError, ValueError):
            state["audit_clean"] = False
        else:
            state["audit_clean"] = audit_clean(report)

    print(f"python {sys.version.split()[0]} {'ok' if state['python_ok'] else 'TOO OLD'}")
    print(f"book   {'ok' if state['book'] else 'MISSING'}   {BOOK}")
    print(f"index  {'ok' if state['index'] else 'MISSING'}   {INDEX}")
    print(f"ollama {'ok' if state['ollama'] else 'DOWN'}")
    if tags is not None:
        for name in (DEFAULT_EMBEDDER, ANSWER_MODEL):
            mark = "ok" if model_present(tags, name) else "MISSING"
            print(f"model  {mark:<8}{name}")
    if state["audit_clean"] is not None:
        print(f"vectors {'clean' if state['audit_clean'] else 'DIRTY'}")
    print("next:")
    for step in next_steps(state):
        print(f"  - {step}")

    ready = (
        state["python_ok"]
        and state["book"]
        and state["index"]
        and state["ollama"]
        and not state["missing_models"]
        and state["audit_clean"] is True
    )
    raise SystemExit(0 if ready else 1)


if __name__ == "__main__":
    main()
