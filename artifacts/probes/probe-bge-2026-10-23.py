"""CPU-only cost of a cross-encoder reranker on this box. Read-only.

Loads BAAI/bge-reranker-v2-m3 through sentence_transformers.CrossEncoder on
device=cpu, builds 20 synthetic (query, passage) pairs sized against the
model's own tokenizer (200-300 tokens each), scores them in one predict call,
and reports load seconds, score seconds, and peak RSS.

Nothing is written unless --json names a path. This is a cost probe, not a
retrieval experiment: it answers "what would a rerank stage cost per ask",
it does not claim the reranker helps.

Run:
    python artifacts/probes/probe-bge-2026-10-23.py
    python artifacts/probes/probe-bge-2026-10-23.py --bench 5 --batch-size 8
"""
import argparse
import ctypes
import json
import os
import platform
import random
import sys
import time
from pathlib import Path

MODEL = "BAAI/bge-reranker-v2-m3"
TOKEN_FLOOR = 200
TOKEN_CEIL = 300
PAIRS = 20

# Twenty hand-written synthetic topics: a short core about a plausible system,
# then deterministic padding so every passage lands in the 200-300 token band.
# The vocabulary is deliberately generic; no book text is read.
TOPICS = [
    ("write-ahead log",
     "A write-ahead log appends every mutation to durable storage before the "
     "page itself changes. Recovery replays the log from the last checkpoint, "
     "then discards records older than the oldest live transaction.",
     "Which storage component records changes before the pages are updated?"),
    ("segment compaction",
     "An append-only table stores rows in immutable segments and marks deletes "
     "with tombstones. A background worker merges small segments into larger "
     "ones, dropping tombstoned rows and rewriting the surviving values.",
     "What merges small immutable files and drops deleted rows?"),
    ("quorum replication",
     "Each write is acknowledged by a majority of replicas before the client "
     "sees success. Reads contact a quorum and return the value with the "
     "highest logical version attached to it.",
     "How many replicas must confirm a write before it succeeds?"),
    ("consistent hashing",
     "Keys map onto a ring, and each node owns the arc that precedes it. Adding "
     "a node moves only the keys in the neighbouring arc, so most placements "
     "survive a resize unchanged.",
     "Why does a ring layout move few keys when a node joins?"),
    ("backpressure",
     "A bounded queue between producer and consumer applies backpressure when "
     "it fills, slowing the producer instead of dropping work. The consumer's "
     "rate therefore sets the ceiling for the whole stage.",
     "What happens when the bounded queue between stages fills up?"),
    ("columnar encoding",
     "Values in a column share a type and often repeat, so run-length and "
     "dictionary encodings shrink them far below their row-oriented size. "
     "Predicates skip whole blocks using per-block minimum and maximum "
     "statistics.",
     "Which encoding suits a column whose values repeat often?"),
    ("vector index build",
     "An approximate index groups vectors into clusters and stores a centroid "
     "per cluster. A query visits the nearest centroids first, then scans the "
     "vectors inside them, trading recall for latency.",
     "How does a clustered vector index keep search fast?"),
    ("schema evolution",
     "Adding a nullable column is backward compatible because old readers "
     "ignore fields they do not know. Removing a required field or changing "
     "its type breaks readers still expecting the previous shape.",
     "Which schema change keeps existing readers working?"),
    ("token bucket",
     "A bucket refills at a fixed rate and holds at most its capacity in "
     "credits. Each request spends credit equal to its cost, and requests "
     "arriving with an empty bucket wait or fail immediately.",
     "What limits a client that spends credit faster than the refill rate?"),
    ("two-phase commit",
     "A coordinator asks every participant to prepare, and only when all "
     "answer yes does it ask them to commit. A participant that answers yes "
     "must hold its locks until the decision arrives.",
     "When may a coordinator tell participants to commit?"),
    ("partition skew",
     "A single hot key sends a disproportionate share of traffic to one "
     "partition while the others sit idle. Salting the key with a random "
     "suffix spreads the load across partitions at the cost of fan-out reads.",
     "What causes one partition to receive most of the traffic?"),
    ("checkpoint interval",
     "A periodic checkpoint flushes in-memory state to durable storage so "
     "recovery does not have to replay the entire log. Longer intervals cost "
     "less during normal operation and more after a crash.",
     "What is traded when the checkpoint interval grows longer?"),
    ("bloom filter",
     "A bloom filter answers membership with a bitmap and several hash "
     "functions. It may report a key as present when it is absent, but never "
     "reports present keys as missing.",
     "Can a bloom filter wrongly claim a key exists?"),
    ("cache invalidation",
     "A cache entry carries the version of the record it copied. A reader "
     "discards the entry when the stored version falls behind the source, so "
     "staleness is bounded by how often versions are compared.",
     "How is a stale cache entry detected?"),
    ("shuffle spill",
     "A sort-merge join buffers rows per key until a memory budget is reached, "
     "then writes the remainder to disk and merges the spilled runs later. "
     "Spilling keeps the job alive at the cost of extra disk traffic.",
     "What does an operator do when its memory budget is exhausted?"),
    ("idempotent retry",
     "A client retries a request with the same request key, and the server "
     "returns the stored result of the first attempt rather than applying the "
     "change twice. Duplicate handling therefore lives on the server.",
     "How does a retry avoid applying the same change twice?"),
    ("lease election",
     "Candidates acquire a lease with an expiry and renew it while they are "
     "healthy. If the holder stops renewing, the lease lapses and another "
     "candidate may take leadership without a central arbiter.",
     "What lets another candidate take leadership?"),
    ("watermark lag",
     "An event-time pipeline advances its watermark as the minimum known event "
     "time across inputs. Windows close when the watermark passes their end, "
     "so one slow input delays every downstream result.",
     "Why does one slow input delay every window result?"),
    ("tiered storage",
     "Recent rows live on fast local disks and older rows migrate to cheaper "
     "object storage. Queries that touch cold rows pay a retrieval latency the "
     "planner cannot hide behind caching.",
     "Where do older rows move as they age?"),
    ("admission control",
     "A gateway rejects or queues new work once concurrency reaches a limit, "
     "protecting the serving pool from a queue that grows without bound. The "
     "limit is set below the point where latency degrades sharply.",
     "What protects a serving pool from unbounded queued work?"),
]

# Padding clauses: neutral technical sentences, cycled with a per-topic offset
# so no two passages read alike.
FILLER = [
    "Operators tune the parameters against production traffic rather than the synthetic benchmark, because the two distributions differ in ways that matter.",
    "A dashboard tracks the ratio between the two rates so a regression shows up before users report it.",
    "The team documented the failure mode and the recovery steps in the same runbook that pages the on-call engineer.",
    "Instrumentation records the elapsed time of each stage, which makes the slow one obvious under load.",
    "Configuration is versioned with the code, so a rollback restores the previous limits as well as the previous build.",
    "Load tests replay a recorded trace instead of generating uniform requests, since real traffic is bursty and skewed.",
    "Capacity is provisioned for the peak hour with headroom, and the autoscaler reacts to sustained saturation rather than single spikes.",
    "Alerting thresholds sit far enough from normal variation that routine variance does not page anyone.",
    "Costs are attributed per tenant so a noisy neighbour is visible in the billing report as well as in the latency chart.",
    "A staged rollout limits the blast radius, and the comparison between the old and new cohorts decides whether it continues.",
    "Data retention is set per table, because the audit trail and the serving copy have different legal lifetimes.",
    "The interface is versioned so a consumer on an older schema keeps receiving the fields it expects.",
    "Failures are injected deliberately in staging, which is the only way to know the retry budget is sufficient.",
    "Every decision above was reviewed after the incident, and the review changed the defaults rather than the prose.",
]


def peak_rss_bytes():
    """Peak resident set size of this process, in bytes."""
    if os.name == "nt":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        # psapi.GetProcessMemoryInfo fails here with errno 0; the kernel32
        # re-export (K32...) works and needs explicit argtypes on 64-bit.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.K32GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        ok = kernel32.K32GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        if not ok:
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo")
        return counters.PeakWorkingSetSize
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def build_pairs(tokenizer):
    """20 pairs, each passage inside the token band, verified by tokenizer."""
    pairs = []
    for index, (topic, core, query) in enumerate(TOPICS):
        rng = random.Random(1000 + index)
        sentences = [core]
        cursor = index % len(FILLER)
        while True:
            ids = tokenizer([f"{topic.title()}. {' '.join(sentences)}"],
                            padding=False, truncation=False)["input_ids"][0]
            if len(ids) >= TOKEN_FLOOR + 20:
                break
            sentences.append(FILLER[cursor % len(FILLER)])
            cursor += 1
        passage = f"{topic.title()}. {' '.join(sentences)}"
        count = len(tokenizer([passage], padding=False,
                              truncation=False)["input_ids"][0])
        if not TOKEN_FLOOR <= count <= TOKEN_CEIL:
            raise SystemExit(
                f"passage for {topic!r} is {count} tokens, outside "
                f"{TOKEN_FLOOR}-{TOKEN_CEIL}; adjust the filler pool")
        pairs.append({"topic": topic, "query": query, "passage": passage,
                      "tokens": count})
    return pairs


def shuffled(pairs):
    """Mismatched pairs: pair i's query with pair i+1's passage."""
    return [(p["query"], pairs[(i + 1) % len(pairs)]["passage"])
            for i, p in enumerate(pairs)]


def model_bytes():
    """Bytes on disk for the model snapshot, if the cache is discoverable.

    Hugging Face caches store a blob plus a symlink per snapshot file, so the
    same bytes appear twice under rglob; dedupe on the resolved path.
    """
    from huggingface_hub.constants import HF_HUB_CACHE
    folder = Path(HF_HUB_CACHE) / ("models--" + MODEL.replace("/", "--"))
    if not folder.exists():
        return None, str(folder)
    seen = {}
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix != ".lock":
            real = path.resolve()
            try:
                seen[real] = real.stat().st_size
            except OSError:
                continue
    return sum(seen.values()), str(folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bench", type=int, default=0,
                        help="extra predict calls over the same pairs (warm)")
    parser.add_argument("--batch-size", type=int, default=20,
                        help="predict batch size (default: all 20 in one batch)")
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"),
                        help="inference device (cuda uses fp16)")
    parser.add_argument("--json", type=Path, default=None,
                        help="write the measurements as JSON to this path")
    args = parser.parse_args()

    import sentence_transformers
    import torch
    import transformers
    from sentence_transformers import CrossEncoder

    rss_start = peak_rss_bytes()

    print(f"python           {platform.python_version()} ({platform.machine()})")
    print(f"torch            {torch.__version__}  cuda_available={torch.cuda.is_available()}")
    print(f"sentence_transformers {sentence_transformers.__version__}")
    print(f"transformers     {transformers.__version__}")
    print(f"threads          torch={torch.get_num_threads()}")
    print(f"rss at import    {rss_start / 2**20:.1f} MiB")

    load_start = time.perf_counter()
    from huggingface_hub.constants import HF_HUB_CACHE
    cached_before = (Path(HF_HUB_CACHE)
                     / ("models--" + MODEL.replace("/", "--"))).exists()
    model = CrossEncoder(MODEL, device=args.device, max_length=512)
    if args.device == "cuda":
        model.model.half()
    load_seconds = time.perf_counter() - load_start
    rss_loaded = peak_rss_bytes()

    pairs = build_pairs(model.tokenizer)
    tokens = [p["tokens"] for p in pairs]
    print(f"\npairs            {len(pairs)}  tokens min/median/max "
          f"{min(tokens)}/{sorted(tokens)[len(tokens) // 2]}/{max(tokens)}")

    inputs = [(p["query"], p["passage"]) for p in pairs]
    controls = shuffled(pairs)

    score_start = time.perf_counter()
    scores = model.predict(inputs, batch_size=args.batch_size,
                           show_progress_bar=False, convert_to_numpy=True)
    first_seconds = time.perf_counter() - score_start
    rss_scored = peak_rss_bytes()

    control_start = time.perf_counter()
    control_scores = model.predict(controls, batch_size=args.batch_size,
                                   show_progress_bar=False, convert_to_numpy=True)
    control_seconds = time.perf_counter() - control_start

    warm = []
    for _ in range(args.bench):
        started = time.perf_counter()
        model.predict(inputs, batch_size=args.batch_size,
                      show_progress_bar=False, convert_to_numpy=True)
        warm.append(time.perf_counter() - started)

    matched = [float(s) for s in scores]
    mismatched = [float(s) for s in control_scores]
    pairs_per_second = len(pairs) / first_seconds
    tokens_scored = sum(tokens) + sum(len(q.split()) for q in
                                       (p["query"] for p in pairs))
    origin = "weights on disk" if cached_before else "includes the download"

    print(f"\nmodel load       {load_seconds:8.2f} s   (device={args.device}, {origin})")
    print(f"predict #1       {first_seconds:8.2f} s   {pairs_per_second:5.2f} pairs/s"
          f"  batch={args.batch_size}  ({first_seconds / len(pairs) * 1000:.1f} ms/pair)")
    print(f"                 ~{sum(tokens) / first_seconds:6.0f} scored tokens/s"
          f"  ({sum(tokens)} passage tokens, {tokens_scored} incl. queries)")
    print(f"predict controls {control_seconds:8.2f} s   (same 20 pairs, mismatched)")
    if warm:
        mean = sum(warm) / len(warm)
        print(f"predict warm x{len(warm)}  mean {mean:6.2f} s   "
              f"min {min(warm):.2f}  max {max(warm):.2f}")
    print(f"\nscore spread     same-topic   {min(matched):+.3f} .. {max(matched):+.3f}"
          f"  mean {sum(matched) / len(matched):+.3f}")
    print(f"                 mismatched   {min(mismatched):+.3f} .. {max(mismatched):+.3f}"
          f"  mean {sum(mismatched) / len(mismatched):+.3f}")
    print(f"                 ranking intact "
          f"{sum(1 for a, b in zip(matched, mismatched) if a > b)}/{len(pairs)}")

    print(f"\npeak rss         import {rss_start / 2**20:.0f} MiB"
          f" -> loaded {rss_loaded / 2**20:.0f} MiB"
          f" -> scored {rss_scored / 2**20:.0f} MiB")
    size, where = model_bytes()
    if size is None:
        print(f"model on disk    not found under {where}")
    else:
        print(f"model on disk    {size / 2**20:.0f} MiB  ({where})")

    if args.json:
        payload = {
            "date": "2026-10-23",
            "model": MODEL,
            "device": "cpu",
            "python": platform.python_version(),
            "torch": torch.__version__,
            "sentence_transformers": sentence_transformers.__version__,
            "transformers": transformers.__version__,
            "pairs": len(pairs),
            "tokens": {"min": min(tokens),
                       "median": sorted(tokens)[len(tokens) // 2],
                       "max": max(tokens)},
            "load_seconds": round(load_seconds, 3),
            "predict_seconds": round(first_seconds, 3),
            "predict_control_seconds": round(control_seconds, 3),
            "pairs_per_second": round(pairs_per_second, 3),
            "warm_seconds": [round(w, 3) for w in warm],
            "rss_mib": {"import": round(rss_start / 2**20, 1),
                        "loaded": round(rss_loaded / 2**20, 1),
                        "scored": round(rss_scored / 2**20, 1)},
            "model_mib": None if size is None else round(size / 2**20, 1),
            "scores": {"same_topic_mean": round(sum(matched) / len(matched), 4),
                       "mismatched_mean": round(sum(mismatched) / len(mismatched), 4),
                       "ranking_intact": sum(
                           1 for a, b in zip(matched, mismatched) if a > b)},
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2) + "\n",
                             encoding="utf-8")
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    sys.exit(main())
