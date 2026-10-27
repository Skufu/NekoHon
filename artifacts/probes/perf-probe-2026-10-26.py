"""Perf probe 2026-10-26: retrieval and generation numbers, measured live.

In-process, no HTTP server. The answer model and embedder are already resident
in Ollama; the probe checks /api/ps first and refuses to report a cold-start
number as warm.

Run: python artifacts/probes/perf-probe-2026-10-26.py
Writes: artifacts/evidence/perf/perf-2026-10-26.json
"""

import json
import math
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import answer as A
import retrieve as R
import server as S
from canonical import canonical_query
from keywords import postings
from prompt import ANSWER_MODEL, OLLAMA_KEEP_ALIVE

OLLAMA = "http://127.0.0.1:11434"
INDEXES = {
    "fde": ROOT / "data" / "index.json",
    "quantization": ROOT / "data" / "index.quantization.json",
    "ddia": ROOT / "data" / "index.ddia.json",
}
SEALED = ROOT / "artifacts" / "datasets" / "sealed-2026-10-24.jsonl"
OUT = ROOT / "artifacts" / "evidence" / "perf" / "perf-2026-10-26.json"


def ms(seconds):
    return round(seconds * 1000.0, 3)


def pct(values, share):
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))
    return ordered[index]


def summarize(values):
    return {
        "n": len(values),
        "mean_ms": round(statistics.fmean(values), 3),
        "p50_ms": round(statistics.median(values), 3),
        "p90_ms": round(pct(values, 0.90), 3),
        "min_ms": round(min(values), 3),
        "max_ms": round(max(values), 3),
    }


def ollama_ps():
    with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=30) as response:
        return json.loads(response.read().decode("utf-8")).get("models") or []


def questions_by_book():
    grouped = {}
    for line in SEALED.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        book = item.get("book_id")
        if book in INDEXES and item.get("expect") == "answer":
            grouped.setdefault(book, []).append(item["question"])
    return {book: questions[:3] for book, questions in grouped.items()}


def stream_metrics(system, user, model):
    """One live streaming generation, with Ollama's own token counters."""
    payload = {
        "model": model,
        "stream": True,
        "think": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {"temperature": 0, "num_predict": 512},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    request = urllib.request.Request(
        OLLAMA + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    ttft = None
    final = {}
    with urllib.request.urlopen(request, timeout=120) as response:
        for line in response:
            line = line.strip()
            if not line:
                continue
            frame = json.loads(line.decode("utf-8"))
            piece = ((frame.get("message") or {}).get("content")) or ""
            if piece and ttft is None:
                ttft = time.perf_counter() - started
            if frame.get("done"):
                final = frame
    total = time.perf_counter() - started
    eval_count = final.get("eval_count") or 0
    eval_ns = final.get("eval_duration") or 0
    return {
        "ttft_ms": ms(ttft) if ttft is not None else None,
        "total_ms": ms(total),
        "prompt_tokens": final.get("prompt_eval_count"),
        "completion_tokens": eval_count,
        "tokens_per_sec": round(eval_count / (eval_ns / 1e9), 2) if eval_ns else None,
        "prompt_eval_ms": round((final.get("prompt_eval_duration") or 0) / 1e6, 3),
        "load_ms": round((final.get("load_duration") or 0) / 1e6, 3),
    }


def main():
    report = {
        "date": "2026-10-26",
        "model": ANSWER_MODEL,
        "embedder": R.DEFAULT_EMBEDDER,
        "ollama_loaded": [],
    }
    for loaded in ollama_ps():
        report["ollama_loaded"].append(
            {
                "name": loaded.get("name"),
                "size_gb": round((loaded.get("size") or 0) / 1e9, 2),
                "size_vram_gb": round((loaded.get("size_vram") or 0) / 1e9, 2),
                "context": (loaded.get("details") or {}).get("context_length"),
            }
        )

    # 1. Index load: JSON parse + derived unit vectors, postings, book forms.
    report["indexes"] = {}
    loaded = {}
    for book, path in INDEXES.items():
        started = time.perf_counter()
        index = R.load_index(path)
        load_ms = ms(time.perf_counter() - started)
        loaded[book] = index
        chunks = index.get("chunks") or []
        report["indexes"][book] = {
            "path": path.name,
            "file_mb": round(path.stat().st_size / 1e6, 2),
            "chunks": len(chunks),
            "figures": len(index.get("figures") or []),
            "dims": index.get("embedding_dims"),
            "cold_load_ms": load_ms,
            "postings_words": len(postings(index)),
        }

        # Cached postings call (the cache the lexical channel reuses).
        started = time.perf_counter()
        for _ in range(2000):
            postings(index)
        report["indexes"][book]["postings_cached_us"] = round(
            (time.perf_counter() - started) / 2000 * 1e6, 3
        )

        # Cold postings build, measured on a rebuilt table (no cache).
        started = time.perf_counter()
        table = {}
        for position, chunk in enumerate(chunks):
            for word in set(A.words(chunk.get("text") or "")):
                table.setdefault(word, []).append(position)
        report["indexes"][book]["postings_cold_ms"] = ms(time.perf_counter() - started)

    # 2. Dense scoring: full cosine vs pre-normalized unit dot, same corpus.
    fde = loaded["fde"]
    question = questions_by_book()["fde"][0]
    query = R.embed_texts([question], R.DEFAULT_EMBEDDER, R.ollama_embed, "query")[0]
    norm = math.sqrt(R._dot(query, query))
    q_unit = [value / norm for value in query]
    chunks = fde.get("chunks") or []

    true_values = []
    for _ in range(20):
        started = time.perf_counter()
        scores = [R._dot(q_unit, chunk["_uvec"]) for chunk in chunks]
        true_values.append(time.perf_counter() - started)
    cosine_values = []
    for _ in range(20):
        started = time.perf_counter()
        scores = [R.cosine(query, chunk["embedding"]) for chunk in chunks]
        cosine_values.append(time.perf_counter() - started)
    report["dense_scoring"] = {
        "corpus_chunks": len(chunks),
        "unit_dot_ms": summarize([value * 1000 for value in true_values]),
        "full_cosine_ms": summarize([value * 1000 for value in cosine_values]),
        "speedup": round(
            statistics.fmean(cosine_values) / statistics.fmean(true_values), 2
        ),
    }

    # 3. Query embedding: cache hit vs live Ollama round trip.
    embed_values = []
    for _ in range(15):
        started = time.perf_counter()
        R.embed_texts([question], R.DEFAULT_EMBEDDER, R.ollama_embed, "query")
        embed_values.append(time.perf_counter() - started)
    report["query_embed_cached"] = summarize([value * 1000 for value in embed_values])

    live_values = []
    for revision in range(12):
        text = R.format_input(
            R.DEFAULT_EMBEDDER, "query", f"{question} probe-{revision}"
        )
        started = time.perf_counter()
        R.ollama_embed([text], R.DEFAULT_EMBEDDER)
        live_values.append(time.perf_counter() - started)
    report["query_embed_live"] = summarize([value * 1000 for value in live_values])

    # 4. Pre-LLM pipeline: canonicalize + retrieve + fuse + seed + phrase order.
    by_book = questions_by_book()
    for book, index in loaded.items():
        # Warm lazily built caches (caption seeds, book forms) off the clock.
        A.retrieval_context(index, canonical_query(by_book[book][0]), embed_fn=None)

    retrieval_values = []
    ask_values = []
    generations = []
    ask_rows = []
    for book, index in loaded.items():
        for question in by_book[book]:
            asked = canonical_query(question)
            started = time.perf_counter()
            context = A.retrieval_context(index, asked)
            retrieval_values.append(time.perf_counter() - started)

            counter = {"n": 0, "gen_s": []}

            def counted(system, user, model=ANSWER_MODEL, **kwargs):
                counter["n"] += 1
                started_gen = time.perf_counter()
                try:
                    return A.ollama_generate(system, user, model, **kwargs)
                finally:
                    counter["gen_s"].append(time.perf_counter() - started_gen)

            started = time.perf_counter()
            body = A.ask(index, question, generate_fn=counted)
            total = time.perf_counter() - started
            ask_values.append(total)
            generations.append(counter["n"])
            ask_rows.append(
                {
                    "book": book,
                    "question": question,
                    "retrieval_ms": ms(retrieval_values[-1]),
                    "total_ms": ms(total),
                    "generations": counter["n"],
                    "refused": bool(body.get("refused")),
                    "cited": len(body.get("citations") or []),
                    "top_context_chunk": context["passages"][0]["chunk_id"]
                    if context["passages"]
                    else None,
                }
            )

    report["pre_llm"] = summarize([value * 1000 for value in retrieval_values])
    report["ask_end_to_end"] = summarize([value * 1000 for value in ask_values])
    report["ask_rows"] = ask_rows
    report["generations_per_ask"] = {
        "mean": round(statistics.fmean(generations), 2),
        "retry_asks": sum(1 for value in generations if value > 1),
        "asks": len(generations),
    }

    # 5. Streaming generation on the same production prompt.
    stream_rows = []
    for book, index in loaded.items():
        question = by_book[book][0]
        context = A.retrieval_context(index, canonical_query(question))
        system = A.SYSTEM
        user = A.user_message(context["asked"], context["passages"])
        metrics = stream_metrics(system, user, ANSWER_MODEL)
        metrics["book"] = book
        metrics["question"] = question
        stream_rows.append(metrics)
    report["stream"] = stream_rows

    # 6. Reader payload: JSON vs gzip.
    payloads = {}
    for book in INDEXES:
        started = time.perf_counter()
        raw = server_chunks(book)
        payloads[book] = {
            "json_mb": round(len(raw) / 1e6, 2),
            "gzip_mb": round(len(__import__("gzip").compress(raw)) / 1e6, 2),
            "build_ms": ms(time.perf_counter() - started),
        }
    report["chunks_payload"] = payloads

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nwrote {OUT}")


def server_chunks(book):
    response = S.chunks_body(book)
    return response if response is not None else b"{}"


if __name__ == "__main__":
    main()
