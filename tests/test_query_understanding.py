"""Synthetic unseen-domain tests for query understanding, intent engine, and figure scoping.

Domains tested:
1. Distributed Consensus (Paxos, Raft, Quorum, State Machine Replication)
2. Compiler Optimization (LLVM, SSA / Static Single Assignment, phi-nodes)
3. Genomics / Bioinformatics (FASTQ, BWA-MEM, RNA-seq, CRISPR-Cas9)

No Ollama. No book-specific chunk IDs or hardcoded book constants.
"""

import unittest

from engine.answering.answer import (
    _advance_followup_quote,
    _ensure_answer_gloss,
    _extract_query_entities,
    _resolve_contextual_query,
    _should_include_chunk_figures,
    explain,
    fix_acronym_casing,
    respond,
)
from engine.answering.intent import (
    INTENT_CONCEPT_TERM,
    analyze_intent,
    compute_dynamic_followups,
)


class QueryUnderstandingSyntheticTests(unittest.TestCase):
    def test_contrast_gating_compiler_optimization(self):
        """Dynamic followups must not generate contrast comparisons for tools/examples without contrast cues."""
        chunk = {
            "chunk_id": "compiler_002",
            "chapter": "1",
            "heading": "Intermediate Representation",
            "text": (
                "Intermediate Representation\n"
                "Modern compilers transform source syntax trees into intermediate representations such as LLVM IR. "
                "Optimization passes manipulate this intermediate form to eliminate redundant computations."
            ),
        }
        followups = compute_dynamic_followups(chunk, neighbors=[], mode="explain")
        for q in followups:
            self.assertNotIn("compare to LLVM IR", q)
            self.assertNotIn("How does this compare to LLVM IR?", q)

        # But when explicit contrast is present, contrast comparison is valid
        chunk_contrast = {
            "chunk_id": "compiler_003",
            "chapter": "1",
            "heading": "Execution Engines",
            "text": (
                "Execution Engines\n"
                "Unlike Interpreter Execution, Ahead-Of-Time Compilation emits native assembly instructions directly. "
                "This significantly improves runtime performance for compute-bound algorithms."
            ),
        }
        followups_contrast = compute_dynamic_followups(chunk_contrast, neighbors=[], mode="explain")
        self.assertTrue(
            any("interpreter" in q.lower() or "ahead-of-time" in q.lower() or "compare" in q.lower() for q in followups_contrast)
        )

    def test_forward_only_slot3_distributed_consensus(self):
        """Slot 3 must strictly inspect forward neighbors and ignore backward neighbors."""
        chunk = {
            "chunk_id": "consensus_002",
            "chapter": "3",
            "heading": "Log Replication Protocol",
            "text": (
                "Log Replication Protocol\n"
                "The leader appends log entries from clients and broadcasts them to peer nodes. "
                "Entries are committed once a quorum acknowledges receipt."
            ),
        }
        backward_neighbor = {
            "chunk_id": "consensus_001",
            "chapter": "3",
            "heading": "Leader Election Terminology",
            "text": "Leader Election Terminology\nNodes elect a leader during randomized timeouts.",
        }
        forward_neighbor = {
            "chunk_id": "consensus_003",
            "chapter": "3",
            "heading": "Safety Invariants",
            "text": "Safety Invariants\nLeader completeness guarantees committed logs persist.",
        }
        followups = compute_dynamic_followups(
            chunk,
            neighbors=[backward_neighbor, forward_neighbor],
            mode="explain",
        )
        for q in followups:
            self.assertNotIn("Leader Election", q)
        self.assertTrue(any("Safety Invariants" in q for q in followups))

    def test_followup_entity_alignment_genomics(self):
        """Follow-up questions citing specific query entities must align quote and gloss."""
        chunk = {
            "chunk_id": "genomics_010",
            "chapter": "5",
            "heading": "High-Throughput Sequencing Formats",
            "text": (
                "High-Throughput Sequencing Formats\n"
                "FASTQ files represent biological sequencing reads with corresponding per-base quality scores. "
                "Aligners like BWA-MEM map raw reads from FASTQ files against reference genomes to identify genomic variations. "
                "Downstream variant callers subsequently assess candidate single nucleotide polymorphisms."
            ),
        }
        prior_quote = "FASTQ files represent biological sequencing reads with corresponding per-base quality scores."
        followup_q = "How does this relate to BWA-MEM?"

        # 1. Quote advancing selects the BWA-MEM sentence
        adv_quote = _advance_followup_quote(
            chunk,
            neighbors=[],
            prior_quote=prior_quote,
            followup_question=followup_q,
        )
        self.assertIsNotNone(adv_quote)
        self.assertIn("BWA-MEM", adv_quote)
        self.assertNotIn("FASTQ files represent biological sequencing", adv_quote)

        # 2. Gloss synthesis mentions the target entity and connects to section heading
        body = {
            "answer": f'[Ch. 5] "{adv_quote}"\nRaw gloss.',
            "citations": [{
                "chunk_id": "genomics_010",
                "chapter": "5",
                "quote": adv_quote,
            }],
            "figures": [],
            "refused": False,
        }
        history = [
            {"question": "What is FASTQ format?", "answer": f'[Ch. 5] "{prior_quote}"\nFASTQ stores reads and quality scores.'}
        ]
        aligned_body = _ensure_answer_gloss(
            {"chunks": [chunk]},
            body,
            followup_q,
            [chunk],
            is_live=False,
            history=history,
            heading="High-Throughput Sequencing Formats",
        )
        ans_text = aligned_body["answer"]
        self.assertIn("BWA-MEM", ans_text)
        self.assertIn("High-Throughput Sequencing Formats", ans_text)

    def test_passing_mention_detection_and_figure_suppression(self):
        """Passing mentions must detect is_passing_mention=True and suppress unrelated figures."""
        chunk = {
            "chunk_id": "consensus_020",
            "chapter": "4",
            "heading": "Raft Leader Election",
            "text": (
                "Raft Leader Election\n"
                "Raft elects a single distinguished leader responsible for log management (Figure 4-1). "
                "Database administrators can monitor cluster heartbeat metrics to detect network partitions."
            ),
        }
        figures = [
            {
                "figure_id": "figure-4-1",
                "chapter": "4",
                "caption": "Timeline of Raft leader election and heartbeat message broadcasts across quorum peers.",
            }
        ]
        index = {"chunks": [chunk], "figures": figures}

        # 1. Intent analysis identifies passing mention
        info = analyze_intent("Database administrators", heading="Raft Leader Election", chunk=chunk)
        self.assertEqual(info["intent_type"], INTENT_CONCEPT_TERM)
        self.assertTrue(info.get("is_passing_mention"))

        # 2. Scoped figure attachment suppresses figure-4-1 for passing mention
        passing_quote = "Database administrators can monitor cluster heartbeat metrics to detect network partitions."
        self.assertFalse(
            _should_include_chunk_figures(chunk, "Database administrators", passing_quote, figures)
        )

        # 3. Explain endpoint suppresses figure-4-1 and grounds gloss with section heading
        norm_val = 1.0 / (768.0 ** 0.5)
        def fake_embed(texts, model=None):
            return [[norm_val] * 768 for _ in texts]

        def fake_generate(system, user, model):
            return "Administrators monitor the heartbeat metrics generated during elections."
        fake_generate._is_live = True

        index = {"chunks": [chunk], "figures": figures, "embedder": "nomic-embed-text"}
        res = explain(
            index,
            "Database administrators",
            chunk_id="consensus_020",
            heading="Raft Leader Election",
            generate_fn=fake_generate,
            search_fn=lambda idx, q, k: [chunk],
            model="m",
            embed_fn=fake_embed,
        )
        self.assertFalse(res["refused"])
        self.assertEqual(res["figures"], [], "Unrelated primary figure must not attach to passing mention")
        self.assertIn("Database administrators", res["answer"])

    def test_deictic_pronoun_comparison_alignment(self):
        """Comparison queries with pronouns (e.g. 'How does this compare to Paxos?') align correctly."""
        paxos_chunk = {
            "chunk_id": "consensus_050",
            "chapter": "6",
            "heading": "Consensus Protocols",
            "text": (
                "Consensus Protocols\n"
                "In contrast to Paxos, Raft defines a clear single-leader architecture that simplifies state transitions."
            ),
            "score": 0.95,
        }
        index = {"chunks": [paxos_chunk], "figures": []}
        history = [
            {"question": "What is Raft?", "answer": '[Ch. 6] "Raft defines a clear single-leader architecture."\nRaft is a consensus protocol.'}
        ]

        def fake_generate(system, user, model):
            return '[Ch. 6] "In contrast to Paxos, Raft defines a clear single-leader architecture that simplifies state transitions."\nRaft simplifies consensus compared to Paxos.'

        body = respond(
            index,
            "How does this compare to Paxos?",
            history=history,
            generate_fn=fake_generate,
            search_fn=lambda idx, q, k: [paxos_chunk],
            model="m",
        )
        self.assertFalse(body["refused"])
        self.assertIn("Paxos", body["citations"][0]["quote"])

    def test_acronym_casing_technical_domains(self):
        """Acronym casing handles compiler, consensus, and genomics acronyms accurately."""
        self.assertEqual(fix_acronym_casing("llvm and ssa forms"), "LLVM and SSA forms")
        self.assertEqual(fix_acronym_casing("bwa and fastq pipelines"), "BWA and FASTQ pipelines")
        self.assertEqual(fix_acronym_casing("crispr and rna targeting"), "CRISPR and RNA targeting")
        self.assertEqual(fix_acronym_casing("mlops and devops workflows"), "MLOps and DevOps workflows")
    def test_resolve_contextual_query_multiturn_generic_facet(self):
        """Contextual query resolution on multi-turn history with generic facets (benefits, drawbacks, etc.)."""
        index = {"chunks": []}
        history = [
            {"question": "What is Raft?", "answer": '[Ch. 6] "Raft defines a clear single-leader architecture."'}
        ]
        resolved = _resolve_contextual_query(
            index,
            "What are the main drawbacks?",
            history=history,
            selection="single-leader architecture",
        )
        self.assertIn("Raft", resolved)
        self.assertIn("drawbacks", resolved.lower())

        resolved_simple = _resolve_contextual_query(
            index,
            "Can you explain this in simpler words?",
            history=history,
        )
        self.assertIn("Raft", resolved_simple)


if __name__ == "__main__":
    unittest.main()
