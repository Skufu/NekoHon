"""Local runtime observability for RAG retrieval and LLM generation.

Captures structured per-request spans (query resolution, retrieval stages,
shown passages, Ollama hardware timings/tokens/VRAM loads, and post-LLM
grounding transforms) via contextvars so concurrent HTTP threads and
in-process evaluation runners stay isolated without changing engine return
contracts.

Stdlib only. Zero network calls. Writes JSONL lines to artifacts/runs/traces.jsonl
when enabled.
"""

import contextlib
import contextvars
import datetime
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_LOG_PATH = ROOT / "artifacts" / "runs" / "traces.jsonl"

_CURRENT_TRACE = contextvars.ContextVar("nekohon_current_trace", default=None)
_LOG_LOCK = threading.Lock()


def is_enabled():
    val = os.environ.get("OBSERVE", "1").strip().lower()
    return val not in ("0", "false", "off", "no")


def resolve_log_path(log_path=None):
    if log_path is not None:
        return Path(log_path)
    env_path = os.environ.get("OBSERVE_LOG", "").strip()
    if env_path:
        p = Path(env_path)
        return p if p.is_absolute() else (ROOT / p)
    return DEFAULT_LOG_PATH


class RequestTrace:
    """In-memory structured trace for a single engine request or eval item."""

    def __init__(self, source="http", mode="ask", book_id="", model="", embedder=""):
        self.trace_id = uuid.uuid4().hex[:12]
        self.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.source = source
        self.mode = mode
        self.book_id = book_id
        self.model = model
        self.embedder = embedder
        self.status = "ok"
        self.error = None
        self.started_at = time.perf_counter()
        self.total_ms = 0.0

        # Query understanding & routing
        self.raw_question = ""
        self.resolved_question = ""
        self.asked_form = ""
        self.has_history = 0
        self.pin_chunk = None
        self.has_selection = False
        self.selection_preview = None
        self.history_preview = []
        self.topic_shift = False
        self.reading_repair = None
        self.guard_blocked = None
        self.shortcut = None

        # Retrieval telemetry
        self.retrieval_ms = 0.0
        self.embed_calls = 0
        self.embed_cache_hits = 0
        self.embed_ms = 0.0
        self.embed_vram_load_ms = 0.0
        self.dense_top5 = []
        self.lexical_top5 = []
        self.pre_rerank_top5 = []
        self.retrieval_stages = []
        self.shown_passages = []

        # LLM generation telemetry
        self.llm_calls = []

        # Post-processing & final response summary
        self.transforms = []
        self.final_refused = None
        self.cited_chunks = []
        self.figures_attached = []
        self.answer_chars = 0
        self.answer_preview = ""
        self.citations_detail = []

    def to_dict(self):
        llm_ms = round(sum(c.get("latency_ms", 0.0) for c in self.llm_calls), 2)
        llm_vram_ms = round(
            sum(c.get("vram_load_ms") or 0.0 for c in self.llm_calls), 2
        )
        total_vram_load_ms = round(self.embed_vram_load_ms + llm_vram_ms, 2)
        prompt_tokens = sum(c.get("prompt_tokens") or 0 for c in self.llm_calls)
        completion_tokens = sum(c.get("completion_tokens") or 0 for c in self.llm_calls)
        decode_ms_sum = sum(c.get("decode_ms") or 0.0 for c in self.llm_calls)
        tok_per_sec = (
            round(completion_tokens / (decode_ms_sum / 1000.0), 1)
            if completion_tokens > 0 and decode_ms_sum > 0
            else None
        )
        first_ttft = next(
            (c.get("ttft_ms") for c in self.llm_calls if c.get("ttft_ms") is not None),
            None,
        )

        anomalies = []
        if self.status == "error" or bool(self.error):
            anomalies.append("error")
        if bool(self.guard_blocked):
            anomalies.append("guard_blocked")
        if not self.shown_passages and not self.guard_blocked and not self.shortcut:
            anomalies.append("empty_retrieval")
        if "parse_refused" in self.transforms or "half_covered_refused" in self.transforms:
            anomalies.append("post_llm_refusal")
        if "retry_uncited" in self.transforms or len(self.llm_calls) > 1:
            anomalies.append("uncited_retry")
        if "citation_aligned" in self.transforms:
            anomalies.append("citation_realigned")
        if total_vram_load_ms >= 100.0:
            anomalies.append("vram_cold_load")
        if first_ttft is not None and first_ttft >= 2000.0:
            anomalies.append("slow_ttft")

        return {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "source": self.source,
            "mode": self.mode,
            "book_id": self.book_id,
            "model": self.model,
            "embedder": self.embedder,
            "status": self.status,
            "error": self.error,
            "total_ms": round(self.total_ms, 2),
            "anomalies": list(anomalies),
            "query": {
                "raw": self.raw_question,
                "resolved": self.resolved_question,
                "asked": self.asked_form,
                "history_turns": self.has_history,
                "pin_chunk": self.pin_chunk,
                "has_selection": self.has_selection,
                "selection_preview": self.selection_preview,
                "history_preview": list(self.history_preview),
                "topic_shift": self.topic_shift,
                "reading_repair": self.reading_repair,
                "guard_blocked": self.guard_blocked,
                "shortcut": self.shortcut,
            },
            "retrieval": {
                "retrieval_ms": round(self.retrieval_ms, 2),
                "embed_calls": self.embed_calls,
                "embed_cache_hits": self.embed_cache_hits,
                "embed_ms": round(self.embed_ms, 2),
                "embed_vram_load_ms": round(self.embed_vram_load_ms, 2),
                "stages": list(self.retrieval_stages),
                "dense_top5": list(self.dense_top5),
                "lexical_top5": list(self.lexical_top5),
                "pre_rerank_top5": list(self.pre_rerank_top5),
                "shown_passages": list(self.shown_passages),
            },
            "llm": {
                "call_count": len(self.llm_calls),
                "llm_ms": llm_ms,
                "ttft_ms": first_ttft,
                "vram_load_ms": llm_vram_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "tok_per_sec": tok_per_sec,
                "calls": list(self.llm_calls),
            },
            "vram_load_ms": total_vram_load_ms,
            "outcome": {
                "transforms": list(self.transforms),
                "final_refused": self.final_refused,
                "cited_chunks": list(self.cited_chunks),
                "figures_attached": list(self.figures_attached),
                "answer_chars": self.answer_chars,
                "answer_preview": self.answer_preview,
                "citations_detail": list(self.citations_detail),
                "anomalies": list(anomalies),
            },
        }


def current_trace():
    return _CURRENT_TRACE.get()


def append_trace_line(record, log_path=None):
    target = resolve_log_path(log_path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with _LOG_LOCK:
            with target.open("a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception:
        # Telemetry must never crash or stall a live book request.
        pass


@contextlib.contextmanager
def trace(
    source="http",
    mode="ask",
    book_id="",
    model="",
    embedder="",
    write_log=None,
    log_path=None,
):
    """Capture a structured trace across retrieval and LLM generation."""
    tr = RequestTrace(
        source=source,
        mode=mode,
        book_id=book_id,
        model=model,
        embedder=embedder,
    )
    if write_log is None:
        in_unittest = "unittest" in sys.modules and not os.environ.get("OBSERVE_LOG")
        write_log = source in ("http", "http_stream") and not in_unittest
    token = _CURRENT_TRACE.set(tr)
    try:
        yield tr
    except BaseException as exc:
        tr.status = "error"
        tr.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        tr.total_ms = round((time.perf_counter() - tr.started_at) * 1000.0, 2)
        _CURRENT_TRACE.reset(token)
        if write_log and is_enabled():
            append_trace_line(tr.to_dict(), log_path=log_path)


def record_query(
    *,
    raw_question=None,
    resolved_question=None,
    asked_form=None,
    history_turns=None,
    pin_chunk=None,
    has_selection=None,
    topic_shift=None,
    model=None,
    book_id=None,
    selection_text=None,
    history_preview=None,
):
    tr = _CURRENT_TRACE.get()
    if tr is None:
        return
    if raw_question is not None:
        tr.raw_question = str(raw_question)
    if resolved_question is not None:
        tr.resolved_question = str(resolved_question)
    if asked_form is not None:
        tr.asked_form = str(asked_form)
    if history_turns is not None:
        tr.has_history = int(history_turns)
    if pin_chunk is not None:
        tr.pin_chunk = (
            pin_chunk.get("chunk_id") if isinstance(pin_chunk, dict) else str(pin_chunk)
        )
    if has_selection is not None:
        tr.has_selection = bool(has_selection)
    if selection_text is not None and str(selection_text).strip():
        tr.selection_preview = str(selection_text).strip()[:240]
    if history_preview is not None:
        turns = []
        try:
            items = list(history_preview)[-2:]
        except Exception:
            items = []
        for t in items:
            if isinstance(t, dict):
                if "question" in t or "answer" in t:
                    turns.append({
                        "question": str(t.get("question") or "")[:160],
                        "answer": str(t.get("answer") or "")[:160],
                    })
                else:
                    turns.append({
                        "role": str(t.get("role", "")),
                        "text": str(t.get("content") or t.get("text") or "")[:160],
                    })
            elif isinstance(t, str):
                turns.append({"text": t[:160]})
            else:
                turns.append({"text": str(t)[:160]})
        tr.history_preview = turns
    if topic_shift is not None:
        tr.topic_shift = bool(topic_shift)
    if model and not tr.model:
        tr.model = str(model)
    if book_id and not tr.book_id:
        tr.book_id = str(book_id)


def record_reading_repair(method, reading):
    tr = _CURRENT_TRACE.get()
    if tr is None:
        return
    tr.reading_repair = {"method": str(method), "reading": str(reading)}


def record_guard(reason):
    tr = _CURRENT_TRACE.get()
    if tr is None:
        return
    tr.guard_blocked = str(reason)


def record_shortcut(name):
    tr = _CURRENT_TRACE.get()
    if tr is None:
        return
    tr.shortcut = str(name)


def record_embed(*, ms=0.0, vram_load_ms=0.0, cache_hit=False, embedder=None):
    tr = _CURRENT_TRACE.get()
    if tr is None:
        return
    if embedder and not tr.embedder:
        tr.embedder = str(embedder)
    if cache_hit:
        tr.embed_cache_hits += 1
    else:
        tr.embed_calls += 1
        tr.embed_ms += float(ms)
        tr.embed_vram_load_ms += float(vram_load_ms)


def _format_top5(passages):
    if not passages:
        return []
    formatted = []
    for p in passages[:5]:
        if not isinstance(p, dict):
            continue
        score = p.get("score")
        if score is not None:
            try:
                score = round(float(score), 4)
            except (ValueError, TypeError):
                score = None
        formatted.append({
            "chunk_id": p.get("chunk_id"),
            "chapter": p.get("chapter"),
            "score": score,
        })
    return formatted


def record_retrieval(
    *,
    retrieval_ms=0.0,
    dense_top5=None,
    stages=None,
    shown_passages=None,
    embedder=None,
    lexical_top5=None,
    pre_rerank_top5=None,
):
    tr = _CURRENT_TRACE.get()
    if tr is None:
        return
    tr.retrieval_ms += float(retrieval_ms)
    if embedder and not tr.embedder:
        tr.embedder = str(embedder)
    if dense_top5 is not None:
        tr.dense_top5 = _format_top5(dense_top5)
    if lexical_top5 is not None:
        tr.lexical_top5 = _format_top5(lexical_top5)
    if pre_rerank_top5 is not None:
        tr.pre_rerank_top5 = _format_top5(pre_rerank_top5)
    if stages is not None:
        tr.retrieval_stages = list(stages)
    if shown_passages is not None:
        shown = []
        for idx, p in enumerate(shown_passages, start=1):
            entry = {
                "rank": idx,
                "chunk_id": p.get("chunk_id"),
                "chapter": p.get("chapter"),
                "score": round(float(p.get("score", 0.0)), 4) if p.get("score") is not None else None,
            }
            if p.get("rerank_score") is not None:
                entry["rerank_score"] = round(float(p["rerank_score"]), 4)
            if p.get("phrase_score") is not None:
                entry["phrase_score"] = int(p["phrase_score"])
            shown.append(entry)
        tr.shown_passages = shown


def record_llm_call(
    *,
    model="",
    stream=False,
    has_prefill=False,
    latency_ms=0.0,
    ttft_ms=None,
    prompt_tokens=None,
    completion_tokens=None,
    prefill_ms=None,
    decode_ms=None,
    vram_load_ms=None,
    raw_output="",
    purpose="",
):
    tr = _CURRENT_TRACE.get()
    if tr is None:
        return
    if model and not tr.model:
        tr.model = str(model)
    tok_per_sec = None
    if completion_tokens and decode_ms and decode_ms > 0:
        tok_per_sec = round(completion_tokens / (decode_ms / 1000.0), 1)
    stripped = (raw_output or "").strip()
    raw_refused = stripped == "Not in this book." or stripped.startswith("Not in this book.\n")
    call_entry = {
        "call_index": len(tr.llm_calls) + 1,
        "purpose": purpose or ("retry_or_aux" if tr.llm_calls else "primary"),
        "model": str(model),
        "stream": bool(stream),
        "has_prefill": bool(has_prefill),
        "latency_ms": round(float(latency_ms), 2),
        "ttft_ms": round(float(ttft_ms), 2) if ttft_ms is not None else None,
        "prompt_tokens": int(prompt_tokens) if prompt_tokens is not None else None,
        "completion_tokens": int(completion_tokens) if completion_tokens is not None else None,
        "prefill_ms": round(float(prefill_ms), 2) if prefill_ms is not None else None,
        "decode_ms": round(float(decode_ms), 2) if decode_ms is not None else None,
        "vram_load_ms": round(float(vram_load_ms), 2) if vram_load_ms is not None else None,
        "tok_per_sec": tok_per_sec,
        "raw_refused": raw_refused,
        "raw_output_preview": stripped[:600],
    }
    tr.llm_calls.append(call_entry)


def wrap_generate_fn(generate_fn, default_model=""):
    """Ensure custom/mock generate_fn calls are also captured when tracing is active."""
    if getattr(generate_fn, "_observe_wrapped", False):
        return generate_fn

    def _wrapped(system, user, *args, **kwargs):
        tr = _CURRENT_TRACE.get()
        if tr is None:
            return generate_fn(system, user, *args, **kwargs)
        before = len(tr.llm_calls)
        t0 = time.perf_counter()
        out = generate_fn(system, user, *args, **kwargs)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if len(tr.llm_calls) == before:
            model_arg = args[0] if args else kwargs.get("model", default_model)
            prefill_arg = kwargs.get("prefill", "")
            record_llm_call(
                model=model_arg or default_model,
                stream=False,
                has_prefill=bool(prefill_arg),
                latency_ms=elapsed_ms,
                raw_output=out if isinstance(out, str) else "",
            )
        return out

    _wrapped._is_live = getattr(generate_fn, "_is_live", False)
    _wrapped._observe_wrapped = True
    if hasattr(generate_fn, "__name__"):
        _wrapped.__name__ = generate_fn.__name__
    return _wrapped


def record_transform(name):
    tr = _CURRENT_TRACE.get()
    if tr is None:
        return
    tr.transforms.append(str(name))


def finish_body(body):
    tr = _CURRENT_TRACE.get()
    if tr is None or not isinstance(body, dict):
        return body
    tr.final_refused = bool(body.get("refused"))
    tr.cited_chunks = [
        c.get("chunk_id")
        for c in (body.get("citations") or [])
        if isinstance(c, dict) and c.get("chunk_id")
    ]
    tr.figures_attached = [
        f.get("id")
        for f in (body.get("figures") or [])
        if isinstance(f, dict) and f.get("id")
    ]
    tr.answer_chars = len(body.get("answer") or "")
    tr.answer_preview = str(body.get("answer") or "")[:600]
    tr.citations_detail = [
        {
            "chunk_id": c.get("chunk_id"),
            "chapter": c.get("chapter"),
            "quote_preview": str(c.get("quote") or "")[:240],
        }
        for c in (body.get("citations") or [])
        if isinstance(c, dict) and c.get("chunk_id")
    ]
    return body


def main(argv=None):
    import importlib.util

    inspect_path = ROOT / "artifacts" / "harnesses" / "trace_inspect.py"
    if not inspect_path.is_file():
        sys.stderr.write(f"Trace inspector not found at {inspect_path}\n")
        return 1
    spec = importlib.util.spec_from_file_location("trace_inspect", inspect_path)
    if spec is None or spec.loader is None:
        sys.stderr.write(f"Failed to load spec for {inspect_path}\n")
        return 1
    mod = importlib.util.module_from_spec(spec)
    sys.modules["trace_inspect"] = mod
    spec.loader.exec_module(mod)
    inspect_main = getattr(mod, "main", None)
    if not callable(inspect_main):
        sys.stderr.write(f"No main() found in {inspect_path}\n")
        return 1
    try:
        return inspect_main(argv)
    except TypeError:
        return inspect_main()


if __name__ == "__main__":
    raise SystemExit(main())
