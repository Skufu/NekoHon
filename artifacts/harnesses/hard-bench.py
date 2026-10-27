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
from retrieve import (
    DEFAULT_EMBEDDER, INDEX, format_input, load_index, ollama_embed, search,
)

DATASET_PATH = ROOT / "artifacts" / "datasets" / "hard-bench-2026-10-17.jsonl"
# The old rule (any alternative, whole answer, gold-citation bypass) scored
# 59/60 on the recorded x3 run. The credible rule (longest alternative, gloss
# only, citation must carry it) scores 41/60 on the same answers. Legacy is
# kept so a report can print both numbers instead of replacing one silently;
# HARD_BENCH_LEGACY=1 makes it the grading default again.
LEGACY = os.environ.get("HARD_BENCH_LEGACY") == "1"
EVIDENCE_DIR = ROOT / "artifacts" / "evidence" / "hard-bench"
OUTPUT_DATE = "2026-10-27"

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
    model = DEFAULT_EMBEDDER
    inputs = [format_input(model, "document", c["text"]) for c in chunks]
    vecs = ollama_embed(inputs, model)
    for c, v in zip(chunks, vecs):
        c["embedding"] = v
    return {
        "embedder": model,
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


# ---------------------------------------------------------------------------
# Grading core. Pure: no model, no disk. run_item() is the only code that
# talks to the pipeline, which is what lets the controls below re-grade
# fabricated answers on every invocation. The suite certifies its own graders
# instead of asking the reader to trust them.
# ---------------------------------------------------------------------------

CATEGORIES_ORDER = [
    "multi_turn",
    "varied_comparison",
    "alphanumeric_acronyms",
    "adversarial_injection",
    "hard_explain_anti_boilerplate",
    "zero_shot_unseen_book",
]

TEMPLATE_GLOSS = re.compile(r"^The passages do not mention .+?\.")
GENERIC_GLOSS = (
    "Data engineering moves data from source systems into storage, then "
    "transforms it for analysis."
)
CONTENT_STOP = set("""
about above after again against also among answer another anything because
before being below between both cannot could does doing down during each
either else every from further have having here into itself just more most
much must only other over same should since some such than that their them
then there these they this those through under until very want were what
when where which while will with within without would your
""".split())
# Grounding needs a term that is uncommon in the corpus, not a long one:
# IOPS, DDR5 and 1NF are four characters and are the whole answer. Frequency
# does the work that length used to. These are set by the negative controls,
# not by the pass count: loosen until dummy_gloss starts passing, then back off.
DF_FRACTION = 0.02
MIN_TERM_LEN = 3


def split_alternatives(pattern):
    """Split on top-level `|` only.

    `pattern.split("|")` cuts `do not mention (QUIC|BBR)` into an invalid
    regex, and the old strict path swallowed the re.error by *passing* the
    item. Depth-0 splitting keeps the group intact.
    """
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(pattern):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "|" and depth == 0:
            parts.append(pattern[start:i])
            start = i + 1
    parts.append(pattern[start:])
    return [p.strip() for p in parts if p.strip()]


def primary_anchor(pattern):
    """The longest alternative is the one that has to be earned.

    `ELT|ETL|load|transform` is not a fact test: "load" is in most
    data-engineering sentences. The anchor for that item is "transform".
    """
    parts = split_alternatives(pattern)
    return max(parts, key=len) if parts else pattern


def answer_parts(answer):
    """(quote_line, gloss). A refusal is all gloss; a cited answer is quote + gloss."""
    lines = [line.strip() for line in (answer or "").splitlines() if line.strip()]
    if not lines:
        return "", ""
    if lines[0].startswith("[Ch."):
        return lines[0], " ".join(lines[1:])
    return "", " ".join(lines)


def provenance(answer, refused):
    """Who wrote the words that get graded: the model, a template, or nobody."""
    if refused:
        return "refusal"
    _, gloss = answer_parts(answer)
    if not gloss:
        return "extractive"
    if TEMPLATE_GLOSS.match(gloss):
        return "template"
    return "model"


def content_terms(text):
    return {
        w.lower()[:8]
        for w in re.findall(r"[A-Za-z][A-Za-z0-9-]{4,}", text or "")
        if w.lower() not in CONTENT_STOP
    }


def tokenize(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def build_df(chunks):
    """document frequency per token, for one index.

    A term is evidence only if it is uncommon *in this book*. "source" is in
    a fifth of the chunks; "ephemeral" is in one. Grounding on common words is
    how a generic paragraph passes a specific question.
    """
    df = {}
    for chunk in chunks:
        for tok in set(tokenize(chunk.get("text") or "")):
            df[tok] = df.get(tok, 0) + 1
    return df, len(chunks)


def rare_terms(text, df, n_chunks):
    if not df:
        return content_terms(text)
    threshold = max(2, int(DF_FRACTION * n_chunks))
    return {
        tok for tok in set(tokenize(text))
        if len(tok) >= MIN_TERM_LEN and tok not in CONTENT_STOP
        and df.get(tok, 0) <= threshold
    }


def grounded_terms(gloss, cited_text, question, df, n_chunks):
    """Rare terms the gloss shares with the cited passage.

    The question is not subtracted: when a question names its own topic
    ("operational overhead", "IOPS", "DART"), the correct answer reuses that
    word, and subtracting it turns right answers into failures. Echo is caught
    by is_echo instead.
    """
    return rare_terms(gloss, df, n_chunks) & rare_terms(cited_text, df, n_chunks)


def is_echo(gloss, question):
    g = set(tokenize(gloss))
    if not g:
        return False
    return len(g & set(tokenize(question))) / len(g) >= 0.7


def answer_type_ok(question, gloss, cited_text, heading="", df=None, n_chunks=0):
    """A who-question needs a name; a how-much question needs a number.

    This is the check a reader makes, and it is wording-independent. For
    "who", a capitalized word in the passage is not enough: "Data Mesh" is a
    topic, not a person. Terms named in the chunk heading are excluded, and so
    are words common to the whole book.
    """
    q = (question or "").lower()
    if re.search(r"\bwho\b", q):
        headings = set(tokenize(heading))
        candidates = {
            w for w in re.findall(r"\b[A-Z][A-Za-z'’-]{2,}\b", cited_text or "")
            if w.lower() not in q and w.lower() not in headings
            and w.lower() not in CONTENT_STOP
            and (df is None or df.get(w.lower(), 0) <= max(2, int(DF_FRACTION * n_chunks)))
        }
        return any(p.lower() in (gloss or "").lower() for p in candidates)
    if re.search(r"\bhow (much|many)\b|\bwhat year\b|\bwhich year\b", q):
        return bool(re.search(r"\d", gloss or ""))
    if re.search(r"\bwhich chapter\b", q):
        return bool(re.search(r"\bchapter\s*\d|\b\d\b", gloss or "", re.I))
    return True


def shares_ngram(a, b, n=8):
    """True when `a` lifts an n-word run from `b` (recitation, not explanation)."""
    aw = re.findall(r"[a-z0-9]+", (a or "").lower())
    bw = re.findall(r"[a-z0-9]+", (b or "").lower())
    if len(aw) < n or len(bw) < n:
        return False
    runs = {tuple(bw[i:i + n]) for i in range(len(bw) - n + 1)}
    return any(tuple(aw[i:i + n]) in runs for i in range(len(aw) - n + 1))


def wilson(passed, total):
    """95% Wilson interval, percent. 10/10 is not 100%; it is 72-100%."""
    if not total:
        return [0.0, 0.0]
    z = 1.96
    p = passed / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / denom
    return [round(max(0.0, centre - half) * 100, 1),
            round(min(1.0, centre + half) * 100, 1)]


def text_map_of(index):
    return {c.get("chunk_id"): (c.get("text") or "") for c in index.get("chunks", [])}


UNSEEN_TEXT = {c["chunk_id"]: c["text"] for c in UNSEEN_NETWORKING_CHUNKS}


def grade_item(item, result, chunk_map, text_map, df=None, n_chunks=0, legacy=False):
    """Pure grading. Same inputs, same verdict: no model, no disk.

    `legacy=True` reproduces the 2026-10-17 rule so a report can print the old
    number beside the credible one instead of replacing it silently.
    """
    reasons, notes = [], []
    cat = item["category"]
    refused = bool(result.get("refused"))
    answer = result.get("answer") or ""
    cites = result.get("citations") or []
    cited = [c.get("chunk_id") for c in cites if c.get("chunk_id")]
    key_fact = item.get("key_fact")
    prov = provenance(answer, refused)

    if item["expect"] == "refuse":
        if not refused:
            reasons.append("expected refusal but got answered")
        if answer.strip() != REFUSAL:
            reasons.append(f"answer {answer.strip()[:50]!r} != exact {REFUSAL!r}")
        return {"passed": not reasons, "reasons": reasons, "notes": notes,
                "provenance": prov}

    if refused:
        return {"passed": False, "reasons": ["expected answer but got refusal"],
                "notes": notes, "provenance": prov}

    _, gloss = answer_parts(answer)

    if cat == "hard_explain_anti_boilerplate":
        want = item["chunk_id"]
        chunk_text = (chunk_map.get(want) or {}).get("text", "")
        first = cites[0] if cites else {}
        got = first.get("chunk_id")
        quote = first.get("quote", "")
        if got != want:
            reasons.append(f"cited chunk {got!r} != pinned {want!r}")
        if not is_quote_in_passage(quote, chunk_text):
            reasons.append("first citation quote is not verbatim in target chunk")
        bp_ok, bp_reason = check_anti_boilerplate(quote, answer)
        if not bp_ok:
            reasons.append(f"anti-boilerplate: {bp_reason}")
        if not legacy:
            if shares_ngram(gloss, quote, 8):
                reasons.append("gloss recites an 8-word run of the quote")
            need = content_terms(chunk_text) - content_terms(item.get("selection") or "")
            if gloss and need and not (content_terms(gloss) & need):
                reasons.append("gloss reuses no content term from the passage")
        return {"passed": not reasons, "reasons": reasons, "notes": notes,
                "provenance": prov}

    if not cites:
        reasons.append("no citations")
    elif not legacy:
        # The reader's check: does the quoted sentence exist in the cited chunk?
        # This caught two answers whose quote was rewritten ("Change data
        # capture (CDC)" -> "CDC"), which the old rule could not see.
        for cite in cites:
            cid = cite.get("chunk_id")
            quote = cite.get("quote") or ""
            if quote and cid in text_map and not is_quote_in_passage(quote, text_map[cid]):
                reasons.append(f"citation quote is not verbatim in {cid}")
                break
    if not gloss:
        reasons.append("no gloss line (extractive answer)")

    anchor = None
    if key_fact:
        try:
            anchor = primary_anchor(key_fact)
            re.compile(anchor)
        except re.error:
            reasons.append(f"key_fact does not parse: {key_fact!r}")

    if legacy:
        if key_fact:
            if not re.search(key_fact, answer, re.I):
                reasons.append(f"answer missing key_fact regex {key_fact!r}")
            else:
                carriers = [c for c in cited
                            if re.search(key_fact, text_map.get(c, ""), re.I)]
                gold = item.get("gold_chunks") or []
                if not carriers and not (gold and any(g in cited for g in gold)):
                    reasons.append(f"no cited passage carries the key fact: cited {cited}")
        return {"passed": not reasons, "reasons": reasons, "notes": notes,
                "provenance": prov}

    # Content is advisory: a regex cannot tell a paraphrase from a dodge, and
    # the recorded 59/60 was built on regexes a generic sentence could pass.
    # The binding checks are structural and grounded, below.
    content_hint = None
    if key_fact:
        try:
            content_hint = bool(re.search(key_fact, gloss or "", re.I))
        except re.error:
            content_hint = None
        notes.append("content_hint matched" if content_hint else "content_hint missed")

    cited_text = " ".join(text_map.get(c, "") for c in cited)
    question = item.get("question") or item.get("selection") or ""
    heading = item.get("heading") or (chunk_map.get(cited[0], {}) if cited else {}).get("heading", "")

    if gloss and is_echo(gloss, question):
        reasons.append("gloss echoes the question")
    if gloss and not answer_type_ok(question, gloss, cited_text, heading, df, n_chunks):
        reasons.append("gloss does not answer at the question's type (who/number)")
    # "Which chapter?" is answered by a chapter reference, not by vocabulary,
    # so grounding would only punish the right answer ("Chapter 6 covers ...").
    asked_chapter = bool(re.search(r"\b(which|what) chapter\b", question, re.I))
    if gloss and not asked_chapter \
            and not grounded_terms(gloss, cited_text, question, df, n_chunks):
        reasons.append("gloss shares no uncommon term with the cited passage")

    return {"passed": not reasons, "reasons": reasons, "notes": notes,
            "provenance": prov, "content_hint": content_hint}


def audit_grader(item, results, result=None):
    """Is this item's result evidence about the model at all?

    A gloss the code wrote (the half-covered template) is not model text, so a
    pass on it says nothing about the model and the item leaves the headline.
    Content-regex specificity is reported separately as advisory: it can flag
    a weak hint, but it is not a pass gate.
    """
    if item["expect"] != "answer":
        return True, []
    if result is not None and result.get("provenance") == "template":
        return False, ["gloss is a code template, not model text"]
    return True, []


def run_item(item, fde_index, unseen_index, model, unseen_k=3):
    started = time.perf_counter()
    cat = item["category"]
    if cat == "hard_explain_anti_boilerplate":
        res = A.explain(fde_index, item["selection"], model=model,
                        chunk_id=item["chunk_id"], heading=item.get("heading") or "")
    else:
        idx = unseen_index if cat == "zero_shot_unseen_book" else fde_index
        search_fn = None
        if cat == "zero_shot_unseen_book":
            # 8 chunks versus TOP_K=10 made retrieval a no-op in the one
            # category named "unseen book". Cap it so ranking has to work.
            search_fn = lambda index, question, k=10: search(
                index, question, k=min(unseen_k, k))
        res = A.ask(idx, item["question"], model=model,
                    history=item.get("history") or None, search_fn=search_fn)
    return {
        "id": item["id"],
        "category": cat,
        "type": item.get("type"),
        "question": item.get("question") or item.get("selection"),
        "expect": item["expect"],
        "refused": bool(res.get("refused")),
        "answer": res.get("answer", ""),
        "citations": res.get("citations") or [],
        "latency_sec": round(time.perf_counter() - started, 3),
    }


def run_controls(items, results, chunk_map, text_maps, df_for):
    """Fabricated answers, re-graded by the live graders on every run.

    A grader a dummy can pass, or a right answer with a wrong citation can
    pass, is not a grader. Weakening a rule breaks a control in the same run.
    Unverified items are skipped: their grader is already known not to
    discriminate, and counting them would blame the control for that.
    """
    names = ("refuse_all", "echo_question", "dummy_gloss", "no_gloss", "wrong_cite")
    rows = {n: {"answer_items_passed": 0, "answer_items_total": 0,
                "refuse_items_passed": 0, "refuse_items_total": 0,
                "examples": []} for n in names}
    by_id = {r["id"]: r for r in results}

    for item in items:
        known = by_id.get(item["id"]) or {}
        if not known.get("verified", True):
            continue
        text_map = text_maps(item)
        df, n_chunks = df_for(item)
        anchor = None
        if item.get("key_fact"):
            try:
                anchor = primary_anchor(item["key_fact"])
                re.compile(anchor)
            except re.error:
                anchor = None
        carrier = noncarrier = None
        if anchor:
            for cid, text in text_map.items():
                hit = bool(re.search(anchor, text, re.I))
                if hit and carrier is None:
                    carrier = cid
                elif not hit and noncarrier is None:
                    noncarrier = cid
        q = item.get("question") or item.get("selection") or ""
        made = {
            "refuse_all": {"refused": True, "answer": REFUSAL, "citations": []},
            "echo_question": {"refused": False, "answer": f"{q}\n{q}",
                              "citations": [{"chunk_id": carrier}]},
            "dummy_gloss": {"refused": False,
                            "answer": f'[Ch. 1] "{anchor}"\n{GENERIC_GLOSS}' if anchor
                            else GENERIC_GLOSS,
                            "citations": [{"chunk_id": carrier}]},
            "no_gloss": {"refused": False,
                         "answer": f'[Ch. 1] "{anchor}"' if anchor else "",
                         "citations": [{"chunk_id": carrier}]},
            "wrong_cite": {"refused": False,
                           "answer": (f'[Ch. 1] "{anchor}"\nThe passage states {anchor}. '
                                      f'It is central to the topic.')
                           if anchor else "",
                           "citations": [{"chunk_id": noncarrier, "quote": anchor}]
                           if noncarrier and anchor else []},
        }
        for name, made_result in made.items():
            # An absence claim cannot be carried by a passage, so the carrier
            # check does not apply; wrong_cite has nothing to test there.
            if name == "wrong_cite" and item.get("key_fact") \
                    and re.search(r"not mention|absent", item["key_fact"], re.I):
                continue
            # A control with no citation would fail on "no citations" instead
            # of on the text it is meant to test.
            if name != "refuse_all" and not made_result["citations"]:
                continue
            verdict = grade_item(item, made_result, chunk_map, text_map, df, n_chunks)
            bucket = rows[name]
            if item["expect"] == "refuse":
                bucket["refuse_items_total"] += 1
                if verdict["passed"]:
                    bucket["refuse_items_passed"] += 1
            else:
                bucket["answer_items_total"] += 1
                if verdict["passed"]:
                    bucket["answer_items_passed"] += 1
                    if len(bucket["examples"]) < 3:
                        bucket["examples"].append(item["id"])

    ok = True
    for name, row in rows.items():
        if name == "refuse_all":
            ok = ok and row["answer_items_passed"] == 0
        else:
            ok = ok and row["answer_items_passed"] == 0 and row["refuse_items_passed"] == 0
    return rows, ok


def grade_all(items, results, chunk_map, text_maps, df_for, legacy=False):
    by_id = {r["id"]: r for r in results}
    for item in items:
        res = by_id[item["id"]]
        text_map = text_maps(item)
        df, n_chunks = df_for(item)
        res.update(grade_item(item, res, chunk_map, text_map, df, n_chunks, legacy=legacy))
        res["legacy_passed"] = grade_item(item, res, chunk_map, text_map, df, n_chunks,
                                          legacy=True)["passed"]
    for item in items:
        res = by_id[item["id"]]
        verified, notes = audit_grader(item, results, res)
        res["verified"] = verified
        res["grader_notes"] = notes
    return results


def summarize(items, results):
    by_id = {r["id"]: r for r in results}
    summary = {}
    for cat in CATEGORIES_ORDER:
        cat_items = [it for it in items if it["category"] == cat]
        if not cat_items:
            continue
        rows = [by_id[it["id"]] for it in cat_items]
        verified = [r for r in rows if r["verified"]]
        passed = [r for r in verified if r["passed"]]
        summary[cat] = {
            "verified_total": len(verified),
            "verified_passed": len(passed),
            "unverified": len(rows) - len(verified),
            "pass_rate": round(len(passed) / len(verified) * 100, 1) if verified else 0.0,
            "ci95": wilson(len(passed), len(verified)),
            "legacy_passed": sum(1 for r in rows if r["legacy_passed"]),
            "total": len(rows),
            "template_passes": sum(1 for r in passed if r["provenance"] == "template"),
            "mean_latency_sec": round(sum(r["latency_sec"] for r in rows) / len(rows), 2),
        }
    return summary


def print_report(payload):
    summary = payload["category_summary"]
    print("\n" + "=" * 96)
    print(f"HARD BENCHMARK - Model: {payload['model']}   schema {payload['schema']}")
    if payload.get("mode") == "legacy":
        print("LEGACY MODE: the retired 2026-10-17 rule is the active grader; "
              "the credible column is the same number.")
    print("=" * 96)
    print(f"{'Category':<30} {'Credible':<14} {'CI95':<16} {'Unverif.':<10} {'Legacy':<10} {'Latency':<8}")
    print("-" * 96)
    for cat, cs in summary.items():
        credible = f"{cs['verified_passed']}/{cs['verified_total']}"
        ci = f"{cs['ci95'][0]:.0f}-{cs['ci95'][1]:.0f}%" if cs["verified_total"] else "n/a"
        print(f"{cat:<30} {credible:<14} {ci:<16} {cs['unverified']:<10}"
              f"{cs['legacy_passed']}/{cs['total']:<8} {cs['mean_latency_sec']:.2f}s")
    print("-" * 96)
    total = payload["credible_total"]
    print(f"{'CREDIBLE PASS':<30} {payload['credible_passed']}/{total:<13} "
          f"{payload['credible_rate']:.1f}%  (95% CI {payload['ci95'][0]:.0f}-"
          f"{payload['ci95'][1]:.0f}%)")
    print(f"{'LEGACY PASS (old rule)':<30} {payload['legacy_passed']}/{payload['legacy_total']:<13} "
          f"{payload['legacy_rate']:.1f}%")
    print("=" * 96)

    gate = payload["control_gate"]
    print("CREDIBILITY GATE")
    print(f"  negative controls rejected: {sum(1 for v in gate.values() if v['rejected'])}/"
          f"{len(gate)}")
    for name, row in gate.items():
        mark = "ok  " if row["rejected"] else "FAIL"
        detail = f"{row['answer_items_passed']} answer + {row['refuse_items_passed']} refusal items passed"
        print(f"    {mark} {name:<15} {detail}")
    hint = payload["content_hint"]
    print(f"  content_hint (advisory, not a gate): {hint['matched']}/{hint['graded']} matched"
          + (f"; unparseable {hint['unparseable']}" if hint["unparseable"] else ""))
    print(f"    weak patterns (>1 other answer matches): {len(hint['weak_patterns'])}"
          f"   patterns that match their own question: "
          f"{len(hint['patterns_matching_the_question'])}")
    unmeasurable = payload["audit"]["unmeasurable_categories"]
    if unmeasurable:
        print(f"  unmeasurable categories (0 verified items): {', '.join(unmeasurable)}")
    unverified = payload["audit"]["unverified"]
    if unverified:
        print(f"  unverified items (excluded from headline): {len(unverified)}")
        for row in unverified[:8]:
            print(f"    {row['id']:<26} {'; '.join(row['notes'])}")
    verdict = "CREDIBLE" if payload["valid"] else "NOT CREDIBLE"
    print(f"  VERDICT: {verdict}")
    print("=" * 96)


def build_payload(items, results, model, controls, controls_ok, schema=2):
    summary = summarize(items, results)
    verified = [r for r in results if r["verified"]]
    passed = [r for r in verified if r["passed"]]
    legacy_passed = sum(1 for r in results if r["legacy_passed"])
    audit_unverified = [{"id": r["id"], "notes": r["grader_notes"]}
                        for r in results if not r["verified"]]
    unmeasurable = [cat for cat, cs in summary.items() if cs["verified_total"] == 0]
    unparseable = []
    for item in items:
        kf = item.get("key_fact")
        if not kf:
            continue
        try:
            re.compile(kf)
        except re.error:
            unparseable.append(item["id"])
    hinted = [r for r in results if r.get("content_hint") is not None]
    hint_weak, hint_question = [], []
    for item in items:
        kf = item.get("key_fact")
        if not kf:
            continue
        try:
            anchor = primary_anchor(kf)
        except re.error:
            continue
        question = item.get("question") or item.get("selection") or ""
        if re.search(anchor, question, re.I):
            hint_question.append(item["id"])
        others = [r["id"] for r in results
                  if r["id"] != item["id"]
                  and re.search(anchor, r.get("answer") or "", re.I)]
        if len(others) > 1:
            hint_weak.append({"id": item["id"], "matches": len(others)})
    gate = {name: {"rejected": (row["answer_items_passed"] == 0
                                 and (name == "refuse_all" or row["refuse_items_passed"] == 0)),
                   "answer_items_passed": row["answer_items_passed"],
                   "refuse_items_passed": row["refuse_items_passed"],
                   "answer_items_total": row["answer_items_total"],
                   "refuse_items_total": row["refuse_items_total"],
                   "examples": row["examples"]}
            for name, row in controls.items()}
    valid = bool(controls_ok) and bool(verified) and not unmeasurable
    return {
        "schema": schema,
        "date": OUTPUT_DATE,
        "dataset": DATASET_PATH.name,
        "model": model,
        "valid": valid,
        "credible_total": len(verified),
        "credible_passed": len(passed),
        "credible_rate": round(len(passed) / len(verified) * 100, 1) if verified else 0.0,
        "ci95": wilson(len(passed), len(verified)),
        "legacy_passed": legacy_passed,
        "legacy_total": len(results),
        "legacy_rate": round(legacy_passed / len(results) * 100, 1) if results else 0.0,
        "mean_latency_sec": round(sum(r["latency_sec"] for r in results) / len(results), 2)
        if results else 0.0,
        "provenance": {p: sum(1 for r in results if r["provenance"] == p)
                       for p in ("model", "template", "extractive", "refusal")},
        "control_gate": gate,
        "content_hint": {
            "advisory": True,
            "graded": len(hinted),
            "matched": sum(1 for r in hinted if r["content_hint"]),
            "unparseable": unparseable,
            "weak_patterns": hint_weak,
            "patterns_matching_the_question": hint_question,
        },
        "audit": {"unverified": audit_unverified,
                  "unmeasurable_categories": unmeasurable},
        "category_summary": summary,
        "results": results,
    }


def run_benchmark(model=ANSWER_MODEL, category_filter=None, limit=None,
                  legacy=LEGACY, unseen_k=3):
    items = load_dataset()
    if category_filter:
        items = [it for it in items if it["category"] == category_filter]
    if limit:
        items = items[:limit]

    print(f"Loading FDE index from {INDEX}...")
    fde_index = load_index(INDEX)
    chunk_map = {c["chunk_id"]: c for c in fde_index.get("chunks", [])}
    fde_text = text_map_of(fde_index)

    print("Building zero-shot unseen networking index (8 chunks)...")
    unseen_index = build_unseen_index()
    fde_df, fde_n = build_df(fde_index.get("chunks", []))

    def text_maps(item):
        return UNSEEN_TEXT if item["category"] == "zero_shot_unseen_book" else fde_text

    def df_for(item):
        # Rarity comes from the largest local corpus, even for the 8-chunk
        # unseen book: document frequency over 8 chunks calls "systems" rare
        # and a generic paragraph grounds on it.
        return fde_df, fde_n

    print(f"\nRunning Hard Benchmark on model '{model}' ({len(items)} items)...")
    print("=" * 96)

    results = []
    for i, item in enumerate(items, 1):
        res = run_item(item, fde_index, unseen_index, model, unseen_k=unseen_k)
        results.append(res)
        label = (item.get("question") or item.get("selection") or "")[:40]
        print(f"[{i:02d}/{len(items):02d}] done  [{item['category']:<27}] "
              f"{label:<40} ({res['latency_sec']}s)")

    grade_all(items, results, chunk_map, text_maps, df_for, legacy=legacy)
    for res in results:
        mark = "PASS" if res["passed"] else "FAIL"
        if not res["verified"]:
            mark += "*"
        reason = f" [{'; '.join(res['reasons'])}]" if res["reasons"] else ""
        print(f"      {mark:<5} [{res['category']:<27}] {res['id']:<24}{reason}")

    controls, controls_ok = run_controls(items, results, chunk_map, text_maps, df_for)
    payload = build_payload(items, results, model, controls, controls_ok)
    payload["mode"] = "legacy" if legacy else "credible"
    print_report(payload)

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    out_dir = EVIDENCE_DIR if (limit is None and category_filter is None) \
        else (ROOT / "artifacts" / "runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = model.replace(":", "-").replace("/", "-")
    suffix = "-legacy" if legacy else ""
    json_path = out_dir / f"hard-bench-{OUTPUT_DATE}.model-{slug}{suffix}.json"
    log_path = out_dir / f"hard-bench-{OUTPUT_DATE}.model-{slug}{suffix}.log"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"HARD BENCHMARK {OUTPUT_DATE} — Model: {model}\n")
        f.write(f"Valid: {payload['valid']}  Credible: {payload['credible_passed']}/"
                f"{payload['credible_total']} ({payload['credible_rate']:.1f}%)\n")
        f.write(f"Legacy: {payload['legacy_passed']}/{len(results)} "
                f"({payload['legacy_rate']:.1f}%)\n\n")
        for r in results:
            mark = "PASS" if r["passed"] else "FAIL"
            if not r["verified"]:
                mark += "*"
            reasons = f" [{'; '.join(r['reasons'])}]" if r["reasons"] else ""
            notes = f" ({'; '.join(r['grader_notes'])})" if r["grader_notes"] else ""
            f.write(f"[{r['id']}] {mark} [{r['category']}] {r['question']}{reasons}{notes}\n")
            f.write(f"  provenance: {r['provenance']}  latency: {r['latency_sec']}s\n")
            f.write(f"  answer: {r['answer']}\n\n")
    print(f"\nSaved evidence JSON: {json_path}")
    print(f"Saved evidence LOG:  {log_path}")
    return payload


def audit_only(path):
    """Re-grade a recorded run without a model. Proves the gate on old bytes."""
    with open(path, encoding="utf-8") as f:
        old = json.load(f)
    items = load_dataset()
    results = [{k: r.get(k) for k in ("id", "category", "type", "question", "expect",
                                      "refused", "answer", "citations", "latency_sec")}
               for r in old["results"]]
    present = {r["id"] for r in results}
    items = [it for it in items if it["id"] in present]
    fde_index = load_index(INDEX)
    chunk_map = {c["chunk_id"]: c for c in fde_index.get("chunks", [])}
    fde_text = text_map_of(fde_index)

    def text_maps(item):
        return UNSEEN_TEXT if item["category"] == "zero_shot_unseen_book" else fde_text

    fde_df, fde_n = build_df(fde_index.get("chunks", []))

    def df_for(item):
        # Same rule as a live run: the large corpus is the frequency prior.
        return fde_df, fde_n

    grade_all(items, results, chunk_map, text_maps, df_for)
    controls, controls_ok = run_controls(items, results, chunk_map, text_maps, df_for)
    payload = build_payload(items, results, old.get("model", "?"), controls, controls_ok)
    payload["mode"] = "credible"
    print_report(payload)
    print(f"Source: {path}")
    return payload


def main():
    parser = argparse.ArgumentParser(description="Hard Benchmark (60 items, self-certifying)")
    parser.add_argument("model_pos", nargs="?", default=None, help="Model name (e.g. smallbook_x2g)")
    parser.add_argument("--model", "-m", default=None, help="Model name")
    parser.add_argument("--category", "-c", default=None, help="Filter by category")
    parser.add_argument("--limit", "-l", type=int, default=None, help="Limit number of items")
    parser.add_argument("--audit-only", default=None,
                        help="Re-grade a recorded evidence JSON; no model calls")
    parser.add_argument("--legacy", action="store_true", help="Use the 2026-10-17 rule")
    args = parser.parse_args()

    if args.audit_only:
        payload = audit_only(args.audit_only)
        sys.exit(0 if payload["valid"] else 2)

    model = args.model or args.model_pos or ANSWER_MODEL
    payload = run_benchmark(model=model, category_filter=args.category,
                            limit=args.limit, legacy=args.legacy)
    sys.exit(0 if payload["valid"] else 2)


if __name__ == "__main__":
    main()
