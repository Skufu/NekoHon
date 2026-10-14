"""Multi-hop hunt: does the agentic loop surface evidence the single-shot path misses?

Read-only over data/index.json. For each candidate question, two retrieval paths:

- single-shot: `answer.retrieval_context(index, question)["passages"]` -- exactly
  what the answer model would be shown (top-5, after reading repair, fusion,
  and caption seeding).
- agentic: `agentic.agentic_search(index, question)` -- up to 3 model-picked
  tool calls, merged passages uncapped.

Ground truth per question: a fixed list of chunk ids that together carry the
evidence. Established by grepping the index (see `multihop-explore.py`) and
recorded in `multihop-report.md`; "surfaced" means every needed chunk id is in
the path's passages. Also recorded: the needed chunks' dense rank (full
ranking), the loop's merge position of each needed chunk, and whether the
needed set is inside the loop's first five merged passages (the cut a wired
consumer would have to make, since tool-local scores are not comparable).

Cost is measured as model calls and loop steps. Wall-clock seconds are written
to the JSON but marked unreliable: other processes share the Ollama server.

Run: python artifacts/probes/multihop-probe.py
"""

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "probes"))

from agentic import agentic_search  # noqa: E402
from answer import ollama_generate, retrieval_context  # noqa: E402
from retrieve import rank_chunks  # noqa: E402

# needed: minimal chunk set carrying both halves of the question.
# note: why these chunks; kept short, mirrors the report.
CANDIDATES = [
    {
        "label": "data-contract-sla",
        "question": "What is a data contract, and how do data contracts relate "
                    "to SLAs in the serving stage?",
        "needed": ["ch05-071", "ch09-004"],
        "note": "definition with storage/format rules; ch9 'Trust' cross-ref: "
                "SLAs/SLOs may take the form of data contracts (see Chapter 5)",
    },
    {
        "label": "cdc-database-logs",
        "question": "What is change data capture, and which database mechanism "
                    "does the book say it relies on?",
        "needed": ["ch05-013", "ch05-018"],
        "note": "CDC definition cross-refs 'Database Logs'; ch05-018 explains "
                "write-ahead logs",
    },
    {
        "label": "normal-forms-columnar",
        "question": "How do Codd's normal forms relate to the book's advice "
                    "about denormalizing data for columnar databases?",
        "needed": ["ch08-051", "ch06-067"],
        "note": "normal forms + Codd objectives; ch6 columnar joins advice, "
                "cross-refs Chapter 8. ch08-056 (denormalization in OLAP) "
                "supports the relation",
    },
    {
        "label": "lakehouse-object-storage",
        "question": "What is a data lakehouse, and what does the book say "
                    "object storage has to do with it?",
        "needed": ["ch03-082", "ch06-045"],
        "note": "lakehouse definition (Ch 3); ch6: update management for "
                "object storage is the central idea behind the lakehouse",
    },
    {
        "label": "multicloud-motivation-advice",
        "question": "What motivates companies to adopt multicloud, and what "
                    "does the book advise about choosing a multicloud strategy?",
        "needed": ["ch04-036", "ch04-041"],
        "note": "motivations; advice: don't choose complex multicloud unless "
                "there is a compelling reason",
    },
    {
        "label": "base-object-consistency",
        "question": "What does BASE stand for, and how does eventual "
                    "consistency show up in object storage?",
        "needed": ["ch06-023", "ch06-049"],
        "note": "BASE = basically available, soft-state, eventual consistency; "
                "ch06-049 object stores' consistency and versioning",
    },
    {
        "label": "pii-transform-access",
        "question": "What does the book say data engineers must do about "
                    "personally identifiable information during transformation, "
                    "and in access control?",
        "needed": ["ch02-066", "ch10-011"],
        "note": "ethics/privacy: mask PII, track bias in transformed datasets; "
                "least privilege: masking + views + broken glass",
    },
    {
        "label": "mdm-governance",
        "question": "What is master data management, and how does the book "
                    "connect it to data governance?",
        "needed": ["ch02-059", "ch02-013"],
        "note": "MDM/golden records definition; storage key questions tie "
                "master data/golden records tracking to data governance. "
                "ch02-046 (data management practices filtering down) is a "
                "supporting alternative for the governance half",
    },
    {
        "label": "reverse-etl-serving",
        "question": "What is reverse ETL, and how does the book describe it in "
                    "the serving stage?",
        "needed": ["ch02-040", "ch09-055"],
        "note": "definition in the lifecycle (Ch 2); serving-stage definition "
                "(load data from an OLAP database back into a source system)",
    },
    {
        "label": "streaming-decision-unbounded",
        "question": "What questions does the book suggest asking before "
                    "choosing streaming ingestion, and what does it say "
                    "streaming ingestion preserves about data?",
        "needed": ["ch02-020", "ch07-007"],
        "note": "decision questions (Ch 2); Ch 7: streaming ingestion is a "
                "tool for preserving the unbounded nature of data",
    },
]


def merged_positions(ids, needed):
    positions = {}
    for chunk_id in needed:
        try:
            positions[chunk_id] = ids.index(chunk_id) + 1
        except ValueError:
            positions[chunk_id] = None
    return positions


def all_present(ids, needed):
    return all(chunk_id in ids for chunk_id in needed)


def main():
    index_path = ROOT / "data" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    print(f"index: {len(index['chunks'])} chunks, embedder {index.get('embedder')}")
    print(f"candidates: {len(CANDIDATES)}")
    print()

    results = []
    for number, candidate in enumerate(CANDIDATES, start=1):
        question = candidate["question"]
        needed = candidate["needed"]

        ranked = rank_chunks(index, question)
        dense_rank = {}
        rank_by_id = {chunk["chunk_id"]: position
                      for position, (_, chunk) in enumerate(ranked, start=1)}
        for chunk_id in needed:
            dense_rank[chunk_id] = rank_by_id.get(chunk_id)

        counts = {"gen": 0}

        def counting_generate(system, user, model):
            counts["gen"] += 1
            return ollama_generate(system, user, model)

        started = time.perf_counter()
        context = retrieval_context(index, question, generate_fn=counting_generate)
        single_seconds = time.perf_counter() - started
        single_ids = [hit["chunk_id"] for hit in context["passages"]]
        single = {
            "ids": single_ids,
            "found": all_present(single_ids, needed),
            "needed_positions": merged_positions(single_ids, needed),
            "gen_calls": counts["gen"],
            "reading": (context["reading"]["reading"]
                        if context.get("reading") else None),
            "seconds_unreliable": round(single_seconds, 2),
        }

        counts2 = {"gen": 0}

        def counting_generate2(system, user, model):
            counts2["gen"] += 1
            return ollama_generate(system, user, model)

        started = time.perf_counter()
        loop = agentic_search(index, question, generate_fn=counting_generate2)
        loop_seconds = time.perf_counter() - started
        loop_ids = [hit["chunk_id"] for hit in loop["passages"]]
        attempts = [
            {
                "step": item["step"],
                "tool": item["tool"],
                "query": item["query"],
                "chosen_by": item["chosen_by"],
                "new": item["new"],
            }
            for item in loop["attempts"]
        ]
        agentic = {
            "steps": len(attempts),
            "tools": [item["tool"] for item in attempts],
            "chosen_by": [item["chosen_by"] for item in attempts],
            "queries": [item["query"] for item in attempts],
            "stopped": loop["stopped"],
            "ids": loop_ids,
            "merged_count": len(loop_ids),
            "found": all_present(loop_ids, needed),
            "needed_positions": merged_positions(loop_ids, needed),
            "found_in_first5": all_present(loop_ids[:5], needed),
            "gen_calls": counts2["gen"],
            "seconds_unreliable": round(loop_seconds, 2),
            "attempts": attempts,
        }

        results.append({
            "label": candidate["label"],
            "question": question,
            "needed": needed,
            "note": candidate["note"],
            "dense_rank_of_needed": dense_rank,
            "single_shot": single,
            "agentic": agentic,
        })

        print(f'Q{number} [{candidate["label"]}] {question}')
        ranks = ", ".join(f"{cid} dense#{dense_rank[cid]}" for cid in needed)
        print(f"   needed: {ranks}")
        print(f'   single: {"found" if single["found"] else "MISS"} '
              f'{single_ids} (gen calls {counts["gen"]})')
        tools = "->".join(agentic["tools"]) or "(none)"
        where = ", ".join(
            f'{cid} pos {agentic["needed_positions"][cid]}' for cid in needed
        )
        print(f'   loop:   {"found" if agentic["found"] else "MISS"} '
              f'steps={agentic["steps"]} tools={tools} '
              f'stopped={agentic["stopped"]} (gen calls {counts2["gen"]})')
        print(f'           merged {agentic["merged_count"]} passages; needed at {where}; '
              f'first-5: {"yes" if agentic["found_in_first5"] else "no"}')
        print()

    out = ROOT / "artifacts" / "evidence" / "multihop" / "multihop-results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    single_hits = sum(1 for r in results if r["single_shot"]["found"])
    loop_hits = sum(1 for r in results if r["agentic"]["found"])
    loop5_hits = sum(1 for r in results if r["agentic"]["found_in_first5"])
    total_steps = sum(r["agentic"]["steps"] for r in results)
    print(f"single-shot found the needed set: {single_hits}/{len(results)}")
    print(f"agentic found the needed set (any position): {loop_hits}/{len(results)}")
    print(f"agentic found the needed set in its first 5: {loop5_hits}/{len(results)}")
    print(f"agentic steps over the set: {total_steps} "
          f"({total_steps / len(results):.1f} per question)")
    print(f"raw JSON: {out}")


if __name__ == "__main__":
    main()
