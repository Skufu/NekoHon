"""Process-local instrumentation for legacy in-process evaluation entrypoints.

The engine functions and their return values stay unchanged. Only top-level
calls are captured; respond -> ask delegation must not double-count a query.
This is not used by the server and makes no network requests itself.
"""
import contextlib
import copy
import functools
import inspect
import os
import sys
from pathlib import Path

import behavioral_eval as E


@contextlib.contextmanager
def protect_evidence(directory):
    """Legacy entrypoints may not overwrite historical evidence in this process."""
    protected = Path(directory).resolve()
    active = True
    def inside(value):
        if not isinstance(value, (str, bytes, os.PathLike)):
            return False
        return Path(os.fsdecode(value)).resolve().is_relative_to(protected)
    def audit(event, args):
        if not active:
            return
        paths = []
        if event == "open":
            filename, mode, flags = args
            if (mode and any(c in mode for c in "wax+")) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                paths = [filename]
        elif event in ("os.remove", "os.rmdir", "os.mkdir"):
            paths = args[:1]
        elif event in ("os.rename", "os.link"):
            paths = args[:2]
        if any(inside(p) for p in paths):
            raise PermissionError("Legacy suite attempted to change protected historical evidence")
    sys.addaudithook(audit)
    try:
        yield
    finally:
        active = False


@contextlib.contextmanager
def record_engine_calls(engine, observe, emit, suite):
    originals = {name: getattr(engine, name) for name in ("ask", "respond", "explain")}
    depth = 0
    sequence = 0

    def wrap(name, original):
        @functools.wraps(original)
        def call(index, *args, **kwargs):
            nonlocal depth, sequence
            if depth:
                return original(index, *args, **kwargs)
            depth += 1
            sequence += 1
            try:
                bound = inspect.signature(original).bind(index, *args, **kwargs).arguments
                selection = bound.get("selection", "")
                question = bound.get("question") or "Explain this selection: " + selection
                book_id = index.get("book_id") or "unidentified-local-index"
                case = {"id": f"{suite}:{sequence}", "book_id": book_id,
                        "question": question, "history": bound.get("history") or [],
                        "mode": "answer" if name == "respond" else name}
                # Hash the corpus bytes, not transient embedding/postings caches.
                source = [{k: c.get(k) for k in ("chunk_id", "chapter", "text")}
                          for c in index["chunks"]]
                fingerprint = E.digest(source)
                existing = observe.current_trace()
                context = contextlib.nullcontext(existing) if existing is not None else observe.trace(
                    source=suite, mode=case["mode"], book_id=book_id,
                    model=bound.get("model") or getattr(engine, "ANSWER_MODEL", ""), write_log=False)
                with context as trace:
                    assert trace is not None
                    result = original(index, *args, **kwargs)
                frozen = E.freeze_result(case, result, index, trace.to_dict(), fingerprint)
                frozen["index_hash_scope"] = "ordered chunk_id/chapter/text corpus; excludes transient caches"
                frozen["request"] = {"selection": selection, "question": bound.get("question"),
                                     "chunk_id": bound.get("chunk_id") or bound.get("pin_chunk"),
                                     "heading": bound.get("heading"), "history": case["history"]}
                frozen["request"] = copy.deepcopy(frozen["request"])
                emit(frozen)
                return result
            finally:
                depth -= 1
        return call

    try:
        for name, original in originals.items():
            setattr(engine, name, wrap(name, original))
        yield
    finally:
        for name, original in originals.items():
            setattr(engine, name, original)
