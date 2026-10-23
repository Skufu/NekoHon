import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.ingest import BOOK, ROOT
from engine.answering.prompt import ANSWER_MODEL
from engine.retrieval.retrieve import DEFAULT_EMBEDDER, INDEX, load_index
from engine.server import ollama_up
from scripts.verify_index import AXES, audit

MINIMUM_PYTHON = (3, 9)
TAGS_URL = "http://127.0.0.1:11434/api/tags"
PS_URL = "http://127.0.0.1:11434/api/ps"
HEALTH_URL = "http://127.0.0.1:8000/health"


def resident_models(timeout=2.0):
    try:
        with urllib.request.urlopen(PS_URL, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    return [model.get("name", "") for model in body.get("models", [])]


def wait_for_warmup(server_url=HEALTH_URL, timeout=60.0, poll_interval=0.5):
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            req = urllib.request.Request(server_url, headers={"User-Agent": "preflight-check"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                warm = data.get("warm") or {}
                if warm.get("done"):
                    if warm.get("ok"):
                        return True, warm
                    return False, warm
        except Exception as e:
            last_err = e
        time.sleep(poll_interval)
    return False, {"error": f"timed out waiting for warmup ({last_err})"}


def version_ok(version, minimum=MINIMUM_PYTHON):
    return version >= minimum


def model_present(names, wanted):
    return any(name == wanted or name.startswith(wanted + ":") for name in names)


def audit_clean(report):
    if report.get("no_declared_dims") or report.get("missing"):
        return False
    return not any(report.get(axis) for axis in AXES)


def ollama_models(timeout=2.0):
    try:
        with urllib.request.urlopen(TAGS_URL, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    return [model.get("name", "") for model in body.get("models", [])]


def next_steps(state):
    steps = []
    if not state["python_ok"]:
        steps.append(
            f"install Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}+ "
            "(macOS: brew install python@3.12)"
        )
    if not state["book"]:
        steps.append(f"put the EPUB at {BOOK.relative_to(ROOT)}")
    if not state["index"]:
        steps.append("build the index: python3 -m engine.ingest, then python3 -m engine.retrieval.retrieve")
    if not state["ollama"]:
        steps.append("start Ollama, then run this script again")
    else:
        for name in state["missing_models"]:
            steps.append(f"pull the model: ollama pull {name}")
    if state["audit_clean"] is False:
        steps.append("the index failed its vector audit; re-run python3 -m engine.retrieval.retrieve")
    if not steps:
        steps.append("ready: python3 -m engine.server, then open http://127.0.0.1:8000/")
    return steps


def main():
    if "--wait-warm" in sys.argv:
        port = None
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                try:
                    port = int(sys.argv[i + 1])
                except ValueError:
                    pass
            elif arg.startswith("--port="):
                try:
                    port = int(arg.split("=", 1)[1])
                except ValueError:
                    pass
        if port is None:
            try:
                port = int(os.environ.get("PORT", 8000))
            except ValueError:
                port = 8000
        server_url = f"http://127.0.0.1:{port}/health"
        print(f"waiting for engine warmup on {server_url}...")
        ok, warm = wait_for_warmup(server_url=server_url)
        if ok:
            print(f"engine warm ok ({warm.get('duration_s', 0)}s): {warm.get('answer_model')} + {warm.get('embed_model')} resident")
            raise SystemExit(0)
        else:
            print(f"engine warmup failed or timed out: {warm}")
            raise SystemExit(1)

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
        resident = resident_models()
        for name in (DEFAULT_EMBEDDER, ANSWER_MODEL):
            mark = "ok" if model_present(tags, name) else "MISSING"
            res = " (resident)" if resident and model_present(resident, name) else ""
            print(f"model  {mark:<8}{name}{res}")
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
