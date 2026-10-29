"""Capture real local queries, then judge immutable evidence with a calibrated LLM.

capture: --dataset accepts public single-query sets or Adrian/crossbook scenarios.
replay: accepts capture output only; never reconstructs old answers from live search.
Every replay rechecks positive/negative controls. An invalid judge exits 2; model
failures are triage, not a CI quality gate. No cloud calls occur during capture.
"""
import argparse
import copy

import hashlib
import importlib.util
import json

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import behavioral_eval as E


def read_rows(path):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    if isinstance(data, list):
        return data
    for key in ("captures", "items", "rows", "results"):
        if isinstance(data.get(key), list):
            return data[key]
    raise ValueError(f"No recognized item list in {path}")


def git_state():
    def git(*args):
        return subprocess.check_output(["git", "--no-pager", *args], cwd=ROOT,
                                               encoding="utf-8", errors="strict", timeout=20,
                                               stderr=subprocess.PIPE).strip()
    source_files = sorted(set(ROOT.glob("*.py")) | set(HERE.glob("*.py")))
    return {"head": git("rev-parse", "HEAD"), "working_tree": git("status", "--porcelain"),
            "diff_sha256": hashlib.sha256(git("diff", "--no-ext-diff").encode()).hexdigest(),
            "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in source_files}}


def write_output(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path, flush=True)


def capture(args):
    import answer as A
    import observe
    from retrieve import load_index
    spec = importlib.util.spec_from_file_location("reader_scenarios", HERE / "adrian-eval.py")
    if spec is None or spec.loader is None:
        raise ImportError("Could not load the scenario runner")
    scenarios = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scenarios)
    catalog = {b["book_id"]: b for b in json.loads((ROOT / "data/books.json").read_text(encoding="utf-8"))}
    loaded, sources, captures, errors, legacy = {}, [], [], [], []
    reviews = json.loads(args.reviews.read_text(encoding="utf-8")) if args.reviews else []
    for dataset in args.dataset:
        if "sealed" in dataset.name:
            raise ValueError("Sealed suites are not development data")
        rows = read_rows(dataset)
        sources.append({"path": str(dataset), "sha256": hashlib.sha256(dataset.read_bytes()).hexdigest()})
        # Never open a sealed suite as an incidental development source.
        if "sealed" in dataset.name or any(row.get("split") == "locked" for row in rows) and args.split != "dev":
            raise ValueError("Locked/sealed iteration is not supported; use a public development split")
        rows = [r for r in rows if r.get("split", "dev") == args.split]
        if args.ids:
            rows = [r for n, r in enumerate(rows, 1) if str(r.get("id", n)) in args.ids.split(",")]
        if args.limit:
            rows = rows[:args.limit]
        for number, row in enumerate(rows, 1):
            book_id = row.get("book_id") or args.book
            if book_id not in loaded:
                p = ROOT / catalog[book_id]["index_path"]
                loaded[book_id] = (load_index(p), hashlib.sha256(p.read_bytes()).hexdigest())
            index, index_sha = loaded[book_id]
            base = {**row, "id": str(row.get("id", number)), "book_id": book_id}

            original = scenarios.run_direct
            def run_payload(idx, payload, base=base, book_id=book_id,
                            index_sha=index_sha, original=original):
                case = {**base, "id": f'{base["id"]}:{len(captures)+1}',
                        "question": payload.get("question") or "Explain this selection: " + payload.get("selection", ""),
                        "history": payload.get("history") or [], "mode": payload["mode"]}
                for review in reviews:
                    if review.get("question_sha256") == E.digest(case["question"]) and review.get("book_id") == book_id:
                        case["expectation_review"] = review
                with observe.trace(source="reader-eval", mode=payload["mode"], book_id=book_id,
                                   model=A.ANSWER_MODEL, write_log=False) as tr:
                    result = original(idx, payload)
                frozen = E.freeze_result(case, result, idx, tr.to_dict(), index_sha)
                frozen["request"] = copy.deepcopy(payload)
                frozen["dataset_source"] = sources[-1]
                captures.append(frozen)
                write_output(args.output, {"schema_version": 1, "sources": sources,
                                           "git": state, "captures": captures, "capture_errors": errors})
                print(case["id"], "refused" if result.get("refused") else "answered", flush=True)
                return result

            try:
                if "turns" in row:
                    setattr(scenarios, "run_direct", run_payload)
                    legacy.append(scenarios.run_scenario(base, index, use_http=False))
                else:
                    mode = row.get("mode", "answer")
                    payload = {"mode": mode, "question": row["question"]}
                    for key in ("selection", "heading", "history", "chunk_id", "end_chunk_id"):
                        if key in row:
                            payload[key] = row[key]
                    run_payload(index, payload)
            except Exception as exc:
                errors.append({"id": base["id"], "error": f"{type(exc).__name__}: {exc}"})
            finally:
                setattr(scenarios, "run_direct", original)
    write_output(args.output, {"schema_version": 1, "sources": sources, "git": state,
                               "captures": captures, "capture_errors": errors,
                               "legacy_scenario_results_advisory": legacy})
    return 2 if errors or not captures else 0


def suite(args):
    import answer as A
    import observe
    from eval_capture import record_engine_calls, protect_evidence
    script = args.script.resolve()
    if script.parent != HERE or script.suffix != ".py" or "sealed" in script.name:
        raise ValueError("Choose a public in-process harness under artifacts/harnesses")
    forwarded = args.suite_args[1:] if args.suite_args[:1] == ["--"] else args.suite_args
    if "--split" in forwarded and forwarded[forwarded.index("--split") + 1:][:1] != ["dev"]:
        raise ValueError("Suite capture is for development splits only")
    if any(a.startswith("--split=") and a != "--split=dev" for a in forwarded):
        raise ValueError("Suite capture is for development splits only")
    payload = {"schema_version": 1, "suite": str(script), "suite_args": forwarded,
               "suite_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
               "git": state, "captures": [], "suite_exit_code": None}
    def emit(capture):
        payload["captures"].append(capture)
        write_output(args.output, payload)
    previous = sys.argv
    code = 0
    try:
        sys.argv = [str(script), *forwarded]
        with protect_evidence(ROOT / "artifacts/evidence"):
            spec = importlib.util.spec_from_file_location("captured_legacy_suite", script)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not load {script}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            historical = (ROOT / "artifacts/evidence").resolve()
            redirects = {}
            for key, value in list(vars(module).items()):
                if isinstance(value, Path) and value.resolve().is_relative_to(historical):
                    redirected = args.output.parent / (args.output.stem + "-legacy") / value.resolve().relative_to(historical)
                    if value.is_dir():
                        redirected.mkdir(parents=True, exist_ok=True)
                    else:
                        redirected.parent.mkdir(parents=True, exist_ok=True)
                    setattr(module, key, redirected)
                    redirects[key] = str(redirected)
            payload["legacy_output_redirects"] = redirects
            with record_engine_calls(A, observe, emit, script.stem):
                module.main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        code = 2
        payload["suite_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        sys.argv = previous
    payload["suite_exit_code"] = code
    if not payload["captures"]:
        payload["capture_error"] = "No in-process engine calls captured; HTTP-only, relevance-only, or unsupported runner. This is not a passing evaluation."
        code = code or 2
    write_output(args.output, payload)
    return code


def replay(args):
    import judge as J
    def complete(system, user):
        raw = J._complete(system, user, J.JUDGE_MODEL, args.timeout)
        return raw, copy.deepcopy(getattr(J, "LAST_CALL", {"requested_judge": J.judge_name()}))
    controls = []
    payload = {"schema_version": 1, "rubric": E.RUBRIC_VERSION, "judge": J.judge_name(),
               "git": state, "valid": False, "controls": controls, "rows": []}
    for control in E.calibration_cases():
        result = E.grade_capture(control["capture"], complete)
        controls.append({"id": control["id"], "expected": control["expected"],
                         "observed": result["status"], "result": result,
                         "capture": control["capture"]})
        write_output(args.output, payload)
        print("control", control["id"], result["status"], flush=True)
    payload["valid"] = E.calibration_valid(controls)
    if not payload["valid"]:
        payload["invalid_reason"] = "Calibration failed; no model-quality score is valid"
        write_output(args.output, payload)
        return 2
    reviews = json.loads(args.reviews.read_text(encoding="utf-8")) if args.reviews else []
    if args.reviews:
        payload["review_overlay"] = {"path": str(args.reviews),
            "sha256": hashlib.sha256(args.reviews.read_bytes()).hexdigest()}
    for source in args.input:
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        for row in read_rows(source):
            original_hash = E.digest(row)
            row = copy.deepcopy(row)
            for review in reviews:
                if (review.get("question_sha256") == E.digest(row.get("question"))
                        and review.get("book_id") == row.get("book_id")
                        and review.get("index_sha256") == row.get("index_sha256")):
                    row["expectation_review"] = review
            if row.get("split") == "locked":
                raise ValueError("Locked replay is not supported in development")
            if row.get("schema_version") != 1 or "original_context_recorded" not in row:
                result = {"id": row.get("id"), "status": "unverifiable",
                          "error": "Legacy answer has no original frozen evidence; recapture it"}
            else:
                result = E.grade_capture(row, complete)
            result["source"] = {"path": str(source), "sha256": source_hash,
                                "original_capture_sha256": original_hash}
            if args.reviews:
                result["review_overlay"] = payload["review_overlay"]
            payload["rows"].append(result)
            payload["summary"] = E.summarize(payload["rows"])
            write_output(args.output, payload)
            print(result["id"], result["status"], flush=True)
    payload["summary"] = E.summarize(payload["rows"])
    write_output(args.output, payload)
    return 2 if not payload["rows"] or payload["summary"]["judge_error"] else 0


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest="command", required=True)
    cap = commands.add_parser("capture")
    cap.add_argument("--dataset", type=Path, action="append", required=True)
    cap.add_argument("--book", default="fde")
    cap.add_argument("--split", choices=["dev"], default="dev")
    cap.add_argument("--ids")
    cap.add_argument("--limit", type=int, default=0)
    cap.add_argument("--reviews", type=Path)
    cap.add_argument("--output", type=Path, required=True)
    old = commands.add_parser("suite", help="Capture actual engine calls made by a public legacy in-process runner")
    old.add_argument("--script", type=Path, required=True)
    old.add_argument("--output", type=Path, required=True)
    old.add_argument("suite_args", nargs=argparse.REMAINDER)
    rep = commands.add_parser("replay")
    rep.add_argument("--input", type=Path, action="append", required=True)
    rep.add_argument("--timeout", type=float, default=90)
    rep.add_argument("--reviews", type=Path, help="Versioned source-reviewed label overlay; does not mutate captured answers")
    rep.add_argument("--output", type=Path, required=True)
    return p


if __name__ == "__main__":
    args = parser().parse_args()
    if args.output.exists():
        raise SystemExit(f"Output already exists; choose a new run label: {args.output}")
    if args.command == "capture" and any("sealed" in p.name for p in args.dataset):
        raise SystemExit("Sealed suites are not development data")
    state = git_state()
    raise SystemExit({"capture": capture, "replay": replay, "suite": suite}[args.command](args))
