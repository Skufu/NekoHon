"""Hard Benchmark 2026-10-17: 60-item un-saturated evaluation harness.

Evaluates 6 challenging, un-saturated dimensions (10 items each = 60 items total):
1. multi_turn: Coreference resolution across turns and out-of-book follow-up refusals.
2. varied_comparison: Natural comparisons without 'vs' or 'difference between' (half & fully covered).
3. alphanumeric_acronyms: Alphanumeric and acronym precision (S3, 3NF, 1NF, 2NF, DDR5, Type-2, IOPS, etc.).
4. adversarial_injection: Prompt injection and plausible out-of-book technical refusal traps.
5. hard_explain_anti_boilerplate: Challenging explain() calls scored on verbatim citation and anti-boilerplate gate.
6. zero_shot_unseen_book: Completely unseen 8-chunk textbook on networking and consensus protocols.

Usage:
    python artifacts/harnesses/hard-bench.py [model]
    python artifacts/harnesses/hard-bench.py --model smallbook_x2g --category multi_turn
    python artifacts/harnesses/hard-bench.py --limit 10

Writes evidence to:
    artifacts/evidence/hard-bench/hard-bench-2026-10-17.model-<model>.json
    artifacts/evidence/hard-bench/hard-bench-2026-10-17.model-<model>.log
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
from prompt import ANSWER_MODEL, REFUSAL
from retrieve import INDEX, format_input, load_index, ollama_embed

DATASET_PATH = ROOT / "artifacts" / "datasets" / "hard-bench-2026-10-17.jsonl"
EVIDENCE_DIR = ROOT / "artifacts" / "evidence" / "hard-bench"

FORMULAIC_CRUTCHES = (
    "in this context",
    "the highlighted",
    "refers to",
)

UNSEEN_NETWORKING_CHUNKS = [
    {
        "chunk_id": "net-01",
        "chapter": "1",
        "heading": "TCP Connection Establishment: The Three-Way Handshake",
        "text": (
            "TCP Connection Establishment: The Three-Way Handshake\n"
            "The Transmission Control Protocol (TCP) establishes a reliable, full-duplex "
            "connection using a three-way handshake before any application data can be transferred. "
            "First, the client initiates the connection by sending a SYN packet with an initial "
            "sequence number to the server. Second, upon receiving the SYN, the server responds "
            "with a SYN-ACK packet containing its own sequence number and acknowledging the client "
            "sequence number. Third, the client sends an ACK packet acknowledging the server SYN-ACK, "
            "at which point the connection enters the ESTABLISHED state and bidirectional data transmission begins."
        ),
    },
    {
        "chunk_id": "net-02",
        "chapter": "1",
        "heading": "TCP Congestion Control: AIMD and Congestion Windows",
        "text": (
            "TCP Congestion Control: AIMD and Congestion Windows\n"
            "TCP manages network congestion using the Congestion Window (cwnd), which dictates the "
            "maximum number of unacknowledged bytes permitted in flight. In the congestion avoidance "
            "phase, TCP employs Additive Increase Multiplicative Decrease (AIMD). The congestion window "
            "increases linearly by one Maximum Segment Size (MSS) per round-trip time (RTT) while "
            "acknowledgments arrive smoothly, probing for available network capacity. When packet loss "
            "occurs, signaling buffer saturation or network congestion, the sender halves the congestion "
            "window multiplicatively to rapidly alleviate network strain."
        ),
    },
    {
        "chunk_id": "net-03",
        "chapter": "2",
        "heading": "Domain Name System Resolution Architecture",
        "text": (
            "Domain Name System Resolution Architecture\n"
            "The Domain Name System (DNS) translates human-readable hostnames into numeric IP addresses "
            "through a hierarchical, distributed resolution process. When a local resolver does not hold a "
            "cached record, it first queries a root name server to determine the authoritative Top-Level "
            "Domain (TLD) servers for the target zone. The TLD server directs the recursive resolver to "
            "the authoritative name servers that maintain the canonical zone records. The authoritative name "
            "server returns the requested A or AAAA record, which the recursive resolver caches locally for the "
            "duration specified by the Time-To-Live (TTL) header before delivering it to the operating system."
        ),
    },
    {
        "chunk_id": "net-04",
        "chapter": "2",
        "heading": "Border Gateway Protocol and Autonomous Systems",
        "text": (
            "Border Gateway Protocol and Autonomous Systems\n"
            "The Border Gateway Protocol (BGP) operates as the de facto path-vector routing protocol "
            "interconnecting autonomous systems (AS) across the global internet. Unlike interior gateway "
            "protocols that measure link metrics, BGP makes routing decisions based on network policies, "
            "path vectors, and administrative rule sets. BGP speakers exchange Network Layer Reachability "
            "Information (NLRI) via UPDATE messages containing the AS-Path attribute, which lists every "
            "autonomous system traversed. If a BGP router detects its own autonomous system number inside an "
            "incoming AS-Path attribute, it immediately discards the route to prevent routing loops."
        ),
    },
    {
        "chunk_id": "net-05",
        "chapter": "3",
        "heading": "TLS 1.3 Handshake Protocol",
        "text": (
            "TLS 1.3 Handshake Protocol\n"
            "Transport Layer Security version 1.3 (TLS 1.3) improves performance and security over prior "
            "versions by finalizing cryptographic session establishment in exactly one round-trip time (1-RTT). "
            "During the client hello message, the client presents its supported cipher suites alongside "
            "prospective Diffie-Hellman ephemeral key shares. The server replies with its chosen key share, "
            "server certificate, and encrypted handshake verification messages, enabling symmetric encryption "
            "to begin immediately. Furthermore, TLS 1.3 eliminates vulnerable cryptographic primitives, "
            "discarding RSA key transport, static Diffie-Hellman, and insecure CBC-mode ciphers in favor of "
            "authenticated encryption with associated data (AEAD)."
        ),
    },
    {
        "chunk_id": "net-06",
        "chapter": "4",
        "heading": "Raft Consensus: Leader Election and Randomized Timeouts",
        "text": (
            "Raft Consensus: Leader Election and Randomized Timeouts\n"
            "The Raft consensus algorithm achieves fault-tolerant state machine replication by electing a single "
            "distinguished leader responsible for log management. Cluster nodes operate in one of three states: "
            "leader, follower, or candidate. When a follower node ceases receiving periodic heartbeats from the "
            "active leader before its election timer expires, it transitions to candidate state, increments its "
            "term counter, votes for itself, and broadcasts RequestVote RPCs to cluster peers. To prevent split "
            "votes where multiple candidates divide cluster support equally, Raft assigns randomized election "
            "timeouts between 150 milliseconds and 300 milliseconds to every node."
        ),
    },
    {
        "chunk_id": "net-07",
        "chapter": "4",
        "heading": "Raft Consensus: Log Replication and Safety Invariant",
        "text": (
            "Raft Consensus: Log Replication and Safety Invariant\n"
            "Once a leader is successfully elected in Raft, it services all client write proposals by appending "
            "entries to its local log and replicating them across cluster followers using AppendEntries RPCs. "
            "An entry is committed once it has been replicated onto a strict majority of cluster nodes, after "
            "which the leader applies the entry to its state machine and returns success to the client. Raft enforces "
            "the Log Matching Property: if two logs contain an entry with the same index and term, then the logs "
            "are identical in all entries up through the given index. Followers reject AppendEntries requests that "
            "fail continuity checks with previous log indices."
        ),
    },
    {
        "chunk_id": "net-08",
        "chapter": "4",
        "heading": "Heartbeat Mechanisms in Consensus Clusters",
        "text": (
            "Heartbeat Mechanisms in Consensus Clusters\n"
            "Consensus protocols require robust failure detection mechanisms to distinguish between temporary "
            "network partitions and node crashes. In Raft clusters, the elected leader transmits empty AppendEntries "
            "RPCs as heartbeats at fixed intervals—typically every 50 milliseconds—to all follower nodes to assert "
            "its authority and reset follower election timers. If network partition isolates a leader with a minority "
            "of nodes, followers in the majority partition will trigger a new election once their election timers elapse, "
            "electing a fresh leader with a higher term counter."
        ),
    },
]


def load_dataset(path=DATASET_PATH):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def build_unseen_index():
    chunks = [dict(c) for c in UNSEEN_NETWORKING_CHUNKS]
    inputs = [format_input("nomic-embed-text", "document", c["text"]) for c in chunks]
    vecs = ollama_embed(inputs)
    for c, v in zip(chunks, vecs):
        c["embedding"] = v
    return {
        "embedder": "nomic-embed-text",
        "chunks": chunks,
        "figures": [],
    }


def normalize_text(text):
    return re.sub(r"[\s\"'“”]+", " ", text or "").strip().lower()


def is_quote_in_passage(quote, passage_text):
    norm_q = normalize_text(quote)
    norm_p = normalize_text(passage_text)
    return norm_q in norm_p


def check_anti_boilerplate(quote, answer):
    lines = [line.strip() for line in (answer or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return False, "missing gloss line"
    gloss = lines[1]
    if len(gloss) < 35:
        return False, f"gloss too short ({len(gloss)} < 35 chars)"
    norm_gloss = normalize_text(gloss)
    norm_quote = normalize_text(quote)
    if norm_gloss == norm_quote:
        return False, "gloss repeats quote verbatim"
    gloss_lower = gloss.lower()
    for crutch in FORMULAIC_CRUTCHES:
        if crutch in gloss_lower:
            return False, f"contains formulaic crutch '{crutch}'"
    return True, "pass"


def evaluate_item(item, fde_index, unseen_index, model, chunk_map):
    cat = item["category"]
    expect = item["expect"]
    gold_chunks = item.get("gold_chunks") or []
    key_fact = item.get("key_fact")
    history = item.get("history") or []

    started = time.perf_counter()
    reasons = []

    if cat == "hard_explain_anti_boilerplate":
        chunk_id = item["chunk_id"]
        heading = item.get("heading") or ""
        selection = item["selection"]
        res = A.explain(
            fde_index,
            selection,
            model=model,
            chunk_id=chunk_id,
            heading=heading,
        )
        elapsed = round(time.perf_counter() - started, 3)

        if res.get("refused"):
            reasons.append("unexpected refusal on valid explain selection")

        cites = res.get("citations") or []
        first_cite = cites[0] if cites else None
        first_chunk_id = first_cite.get("chunk_id") if first_cite else None
        first_quote = first_cite.get("quote", "") if first_cite else ""

        if first_chunk_id != chunk_id:
            reasons.append(f"cited chunk '{first_chunk_id}' != expected '{chunk_id}'")

        target_chunk = chunk_map.get(chunk_id)
        if target_chunk and not is_quote_in_passage(first_quote, target_chunk.get("text", "")):
            reasons.append("first citation quote is not verbatim in target chunk")

        bp_ok, bp_reason = check_anti_boilerplate(first_quote, res.get("answer", ""))
        if not bp_ok:
            reasons.append(f"anti-boilerplate failure: {bp_reason}")

    else:
        # ask mode
        question = item["question"]
        idx = unseen_index if cat == "zero_shot_unseen_book" else fde_index
        res = A.ask(
            idx,
            question,
            model=model,
            history=history if history else None,
        )
        elapsed = round(time.perf_counter() - started, 3)

        refused = bool(res.get("refused"))
        answer_text = (res.get("answer") or "").strip()
        cites = res.get("citations") or []
        cited_chunks = [c.get("chunk_id") for c in cites if c.get("chunk_id")]

        if expect == "refuse":
            if not refused:
                reasons.append("expected refusal but got answered")
            if answer_text != REFUSAL:
                reasons.append(f"answer text '{answer_text[:50]}' != exact '{REFUSAL}'")
        else:
            # expect answer
            if refused:
                reasons.append("expected answer but got refusal")
            if gold_chunks:
                if not any(gc in cited_chunks for gc in gold_chunks):
                    reasons.append(
                        f"cited {cited_chunks} does not include expected gold {gold_chunks}"
                    )
            if key_fact:
                if not re.search(key_fact, answer_text, re.IGNORECASE):
                    reasons.append(f"answer missing key_fact regex '{key_fact}'")

    passed = len(reasons) == 0
    return {
        "id": item["id"],
        "category": cat,
        "type": item.get("type"),
        "question": item.get("question") or item.get("selection"),
        "expect": expect,
        "refused": bool(res.get("refused")),
        "passed": passed,
        "latency_sec": elapsed,
        "answer": res.get("answer", ""),
        "citations": res.get("citations") or [],
        "reasons": reasons,
    }


def run_benchmark(model=ANSWER_MODEL, category_filter=None, limit=None):
    items = load_dataset()
    if category_filter:
        items = [it for it in items if it["category"] == category_filter]
    if limit:
        items = items[:limit]

    print(f"Loading FDE index from {INDEX}...")
    fde_index = load_index(INDEX)
    chunk_map = {c["chunk_id"]: c for c in fde_index.get("chunks", [])}

    print("Building zero-shot unseen networking index (8 chunks)...")
    unseen_index = build_unseen_index()

    print(f"\nRunning Hard Benchmark 2026-10-17 on model '{model}' ({len(items)} items)...")
    print("=" * 88)

    results = []
    cat_stats = {}

    for i, item in enumerate(items, 1):
        cat = item["category"]
        if cat not in cat_stats:
            cat_stats[cat] = {"passed": 0, "total": 0, "latencies": []}

        res = evaluate_item(item, fde_index, unseen_index, model, chunk_map)
        results.append(res)

        cat_stats[cat]["total"] += 1
        cat_stats[cat]["latencies"].append(res["latency_sec"])
        status = "PASS" if res["passed"] else "FAIL"
        if res["passed"]:
            cat_stats[cat]["passed"] += 1

        prompt_label = (item.get("question") or item.get("selection") or "")[:42]
        reason_str = f" [{'; '.join(res['reasons'])}]" if res["reasons"] else ""
        print(f"[{i:02d}/{len(items):02d}] {status:<4} [{cat:<27}] {prompt_label:<42} ({res['latency_sec']}s){reason_str}")

    total_passed = sum(cs["passed"] for cs in cat_stats.values())
    total_items = sum(cs["total"] for cs in cat_stats.values())
    all_latencies = [r["latency_sec"] for r in results]
    mean_total_latency = round(sum(all_latencies) / len(all_latencies), 2) if all_latencies else 0.0

    print("\n" + "=" * 88)
    print(f"HARD BENCHMARK REPORT (2026-10-17) — Model: {model}")
    print("=" * 88)
    print(f"{'Category':<32} {'Passed / Total':<18} {'Rate':<12} {'Mean Latency':<15}")
    print("-" * 88)

    categories_order = [
        "multi_turn",
        "varied_comparison",
        "alphanumeric_acronyms",
        "adversarial_injection",
        "hard_explain_anti_boilerplate",
        "zero_shot_unseen_book",
    ]

    for cat in categories_order:
        if cat in cat_stats:
            cs = cat_stats[cat]
            rate = (cs["passed"] / cs["total"] * 100) if cs["total"] else 0.0
            mean_lat = round(sum(cs["latencies"]) / len(cs["latencies"]), 2) if cs["latencies"] else 0.0
            pt_str = f"{cs['passed']} / {cs['total']}"
            rate_str = f"{rate:.1f}%"
            lat_str = f"{mean_lat:.2f}s"
            print(f"{cat:<32} {pt_str:<18} {rate_str:<12} {lat_str:<15}")

    print("-" * 88)
    total_rate = (total_passed / total_items * 100) if total_items else 0.0
    print(f"{'TOTAL':<32} {f'{total_passed} / {total_items}':<18} {f'{total_rate:.1f}%':<12} {f'{mean_total_latency:.2f}s':<15}")
    print("=" * 88)

    # Save evidence
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    slug = model.replace(":", "-").replace("/", "-")
    json_path = EVIDENCE_DIR / f"hard-bench-2026-10-17.model-{slug}.json"
    log_path = EVIDENCE_DIR / f"hard-bench-2026-10-17.model-{slug}.log"

    payload = {
        "date": "2026-10-17",
        "model": model,
        "total_items": total_items,
        "total_passed": total_passed,
        "pass_rate": round(total_rate, 1),
        "mean_latency_sec": mean_total_latency,
        "category_summary": {
            cat: {
                "passed": cat_stats[cat]["passed"],
                "total": cat_stats[cat]["total"],
                "pass_rate": round((cat_stats[cat]["passed"] / cat_stats[cat]["total"] * 100), 1),
                "mean_latency_sec": round(sum(cat_stats[cat]["latencies"]) / len(cat_stats[cat]["latencies"]), 2),
            }
            for cat in categories_order
            if cat in cat_stats
        },
        "results": results,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"HARD BENCHMARK REPORT (2026-10-17) — Model: {model}\n")
        f.write(f"Total: {total_passed}/{total_items} ({total_rate:.1f}%)\n\n")
        for r in results:
            status = "PASS" if r["passed"] else "FAIL"
            reasons = f" [{'; '.join(r['reasons'])}]" if r["reasons"] else ""
            f.write(f"[{r['id']}] {status} [{r['category']}] {r['question']}{reasons}\n")
            f.write(f"  Latency: {r['latency_sec']}s\n")
            f.write(f"  Answer: {r['answer']}\n\n")

    print(f"\nSaved evidence JSON: {json_path}")
    print(f"Saved evidence LOG:  {log_path}")
    return payload


def main():
    parser = argparse.ArgumentParser(description="Hard Benchmark 2026-10-17 (60 items)")
    parser.add_argument("model_pos", nargs="?", default=None, help="Model name (e.g. smallbook_x2g)")
    parser.add_argument("--model", "-m", default=None, help="Model name")
    parser.add_argument("--category", "-c", default=None, help="Filter by category")
    parser.add_argument("--limit", "-l", type=int, default=None, help="Limit number of items")
    args = parser.parse_args()

    model = args.model or args.model_pos or ANSWER_MODEL
    run_benchmark(model=model, category_filter=args.category, limit=args.limit)


if __name__ == "__main__":
    main()
