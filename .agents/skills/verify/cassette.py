import argparse
import difflib
import hashlib
import importlib.util
import json
import random
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import answer
import captions
import retrieve
import server

OUT_DIR = ROOT / "data" / "verify"
CASSETTE = OUT_DIR / "cassette.json"
SEED = 20261023
NAMES = ("ollama_generate", "ollama_generate_stream", "ollama_embed")
REAL = {
    "ollama_generate": answer.ollama_generate,
    "ollama_generate_stream": answer.ollama_generate_stream,
    "ollama_embed": retrieve.ollama_embed,
}
ROOT_MODULES = ("answer", "retrieve", "captions", "server", "readings", "fusion", "intent", "agentic")


class CassetteMiss(Exception):
    def __init__(self, readable, near):
        super().__init__(readable)
        self.readable = readable
        self.near = near


def load_battery():
    path = ROOT / "artifacts" / "harnesses" / "step2-battery.py"
    spec = importlib.util.spec_from_file_location("step2_battery", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def key_of(name, args, kwargs):
    readable = json.dumps({"fn": name, "args": args, "kwargs": kwargs},
                          sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(readable.encode("utf-8")).hexdigest(), readable


class Tape:
    def __init__(self, mode, data=None):
        self.mode = mode
        self.data = data if data is not None else {}
        self.lock = threading.Lock()
        self.calls = 0

    def fake(self, name):
        real = REAL[name]

        def fn(*args, **kwargs):
            on_token = kwargs.get("on_token")
            call_kwargs = {k: v for k, v in kwargs.items() if k != "on_token"}
            key, readable = key_of(name, list(args), call_kwargs)
            with self.lock:
                self.calls += 1
            if self.mode == "record":
                pieces = []

                def tap(text):
                    pieces.append(text)
                    if on_token is not None:
                        on_token(text)

                if name == "ollama_generate_stream":
                    out = real(*args, on_token=tap, **call_kwargs)
                else:
                    out = real(*args, **call_kwargs)
                with self.lock:
                    self.data.setdefault(key, {"request": readable, "output": out, "pieces": pieces})
                return out
            entry = self.data.get(key)
            if entry is None:
                marker = f'"fn": "{name}"'
                near = [e["request"] for e in self.data.values() if marker in e["request"]]
                raise CassetteMiss(readable, near[:1])
            if on_token is not None:
                for piece in entry["pieces"]:
                    on_token(piece)
            return entry["output"]

        fn._is_live = True
        fn.__name__ = name
        return fn


def patch(fakes):
    for modname in ROOT_MODULES:
        mod = sys.modules.get(modname)
        if mod is None:
            continue
        for n in NAMES:
            if hasattr(mod, n):
                setattr(mod, n, fakes[n])


def install(tape):
    patch({n: tape.fake(n) for n in NAMES})


def uninstall():
    patch(REAL)


def build_cases(book):
    bat = load_battery()
    questions = [q for q, _ in bat.GOLDEN_PINS]
    for group in (bat.TYPOS, bat.PROBES, bat.COHERENCE):
        questions += [row[0] for row in group]
    questions.append(bat.FRANCE)
    cases = []
    for q in dict.fromkeys(questions):
        for mode in ("ask", "answer"):
            cases.append({"id": f"{mode}::{q}", "kind": mode, "question": q})
    chunks = [c for c in book["chunks"]
              if str(c.get("chapter", "")).isdigit() and len(c.get("text", "")) > 400]
    for i in range(5):
        c = chunks[(i + 1) * len(chunks) // 6]
        text = c["text"]
        start = text.find(" ", len(text) // 4) + 1
        end = text.find(" ", start + 100)
        cases.append({"id": f"explain::{c['chunk_id']}", "kind": "explain",
                      "selection": text[start:end], "chunk_id": c["chunk_id"]})
    for i in range(3):
        cases.append({"id": f"quiz::{i}", "kind": "quiz", "seed": SEED + i})
    cases.append({"id": "multi::watermark", "kind": "multi", "mode": "answer",
                  "turns": ["What is a watermark?", "Why does it matter?"]})
    cases.append({"id": "multi::crud", "kind": "multi", "mode": "ask",
                  "turns": ["What is CRUD?", "Give an example"]})
    cases.append({"id": "stream::watermark", "kind": "stream", "question": "What is a watermark?"})
    return cases


def run_stream(case):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        body = json.dumps({"book_id": "fde", "mode": "answer",
                           "question": case["question"], "stream": 1}).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/ask", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            text = resp.read().decode("utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    finally:
        srv.shutdown()
        srv.server_close()


def run_case(book, case):
    kind = case["kind"]
    random.seed(SEED)
    if kind == "ask":
        return answer.ask(book, case["question"], history=[], selection="", heading="")
    if kind == "answer":
        return answer.respond(book, case["question"], history=[], selection="", heading="")
    if kind == "explain":
        return answer.explain(book, case["selection"], chunk_id=case["chunk_id"], heading="")
    if kind == "quiz":
        return answer.quiz(book, rng=random.Random(case["seed"]))
    if kind == "multi":
        fn = answer.ask if case["mode"] == "ask" else answer.respond
        first = fn(book, case["turns"][0], history=[], selection="", heading="")
        history = answer.sanitize_history([{"question": case["turns"][0], "answer": first["answer"]}])
        return {"t1": first, "t2": fn(book, case["turns"][1], history=history, selection="", heading="")}
    return run_stream(case)


def run_all(book, cases):
    results, times = {}, {}
    for case in cases:
        t0 = time.perf_counter()
        try:
            results[case["id"]] = run_case(book, case)
        except CassetteMiss as miss:
            results[case["id"]] = {"__miss__": miss.readable, "__near__": miss.near}
        times[case["id"]] = time.perf_counter() - t0
    return results, times


def dump(obj):
    return json.dumps(obj, sort_keys=True, indent=1, default=str, ensure_ascii=False)


def write_timing(path, book, cases, tape_data):
    install(Tape("replay", tape_data))
    try:
        runs = [run_all(book, cases)[1] for _ in range(3)]
    finally:
        uninstall()
    out = {
        "reps": 3,
        "total_s": [round(sum(r.values()), 4) for r in runs],
        "per_case_s": {cid: round(sum(r[cid] for r in runs) / 3, 4) for cid in runs[0]},
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(out, indent=1))
    return out


def cmd_record(args):
    book = server.get_book_index("fde")
    cases = build_cases(book)
    tape = Tape("record")
    install(tape)
    try:
        results, _ = run_all(book, cases)
    finally:
        uninstall()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CASSETTE.write_text(json.dumps({"seed": SEED, "tape": tape.data, "results": results},
                                   ensure_ascii=False))
    print(f"recorded {len(cases)} cases, {len(tape.data)} unique ollama calls ({tape.calls} total)")
    out = write_timing(OUT_DIR / "timing-before.json", book, cases, tape.data)
    print(f"timing-before: totals {out['total_s']}")
    return 0


def cmd_replay(args):
    saved = json.loads(CASSETTE.read_text())
    book = server.get_book_index("fde")
    cases = build_cases(book)
    install(Tape("replay", saved["tape"]))
    try:
        results, _ = run_all(book, cases)
    finally:
        uninstall()
    miss = diff = 0
    for cid, got in results.items():
        if "__miss__" in got:
            miss += 1
            print(f"MISS {cid}\n  request: {got['__miss__'][:600]}\n"
                  f"  nearest: {(got['__near__'] or ['-'])[0][:600]}")
            continue
        a, b = dump(saved["results"].get(cid)), dump(got)
        if a != b:
            diff += 1
            print(f"DIFF {cid}")
            print("\n".join(difflib.unified_diff(a.splitlines(), b.splitlines(),
                                                 "recorded", "replayed", lineterm="", n=2)))
    if miss:
        print(f"cassette: {miss} miss(es), {diff} diff(s)")
        return 2
    if diff:
        print(f"cassette: {diff} of {len(cases)} cases differ")
        return 1
    print(f"cassette: {len(cases)} cases identical")
    return 0


def cmd_timing(args):
    saved = json.loads(CASSETTE.read_text())
    book = server.get_book_index("fde")
    out = write_timing(args.out, book, build_cases(book), saved["tape"])
    print(f"timing: totals {out['total_s']} -> {args.out}")
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("record")
    sub.add_parser("replay")
    sub.add_parser("timing").add_argument("--out", default=str(OUT_DIR / "timing.json"))
    args = p.parse_args()
    sys.exit({"record": cmd_record, "replay": cmd_replay, "timing": cmd_timing}[args.cmd](args))


if __name__ == "__main__":
    main()
