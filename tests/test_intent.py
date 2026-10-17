"""Unit tests for the Intent Engine and Anti-Gibberish guards. No Ollama."""

import unittest

from answer import (
    _advance_followup_quote,
    _clean_boilerplate_gloss,
    _is_coherent_gloss,
)
from intent import (
    INTENT_AUTHOR_QUESTION,
    INTENT_CONCEPT_TERM,
    INTENT_MULTI_SENTENCE,
    INTENT_VAGUE_FRAGMENT,
    analyze_intent,
    classify_intent,
    compute_dynamic_followups,
    extract_core_concept,
    extract_enclosing_subject,
    select_substantive_anchor_sentence,
    split_sentences,
)


class IntentEngineTests(unittest.TestCase):
    def test_extract_core_concept_strips_structural_meta_prefixes(self):
        cases = [
            ("A Brief Detour on Cloud Economics", "Cloud Economics"),
            ("Brief Detour on Cloud Economics", "Cloud Economics"),
            ("A Detour on Cloud Economics", "Cloud Economics"),
            ("An Introduction to Distributed Systems", "Distributed Systems"),
            ("A Quick Primer on Stream Processing", "Stream Processing"),
            ("A Short Note about IOPS", "IOPS"),
            ("Understanding Data Ingestion", "Data Ingestion"),
            ("Defining Storage Tiers", "Storage Tiers"),
            ("What is Cloud Native?", "Cloud Native"),
            ("What are Credit Default Swaps?", "Credit Default Swaps"),
            ("simple lift and shift", "simple lift and shift"),
            ("Cloud", "Cloud"),
            ("IOPS", "IOPS"),
        ]
        for inp, expected in cases:
            self.assertEqual(extract_core_concept(inp), expected, f"Failed on {inp}")

    def test_classify_intent_concept_term(self):
        chunk = {"heading": "A Brief Detour on Cloud Economics"}
        self.assertEqual(classify_intent("Cloud Economics", heading="A Brief Detour on Cloud Economics", chunk=chunk), INTENT_CONCEPT_TERM)
        self.assertEqual(classify_intent("Cloud", chunk=chunk), INTENT_CONCEPT_TERM)
        self.assertEqual(classify_intent("IOPS"), INTENT_CONCEPT_TERM)
        self.assertEqual(classify_intent("simple lift and shift"), INTENT_CONCEPT_TERM)

    def test_classify_intent_vague_fragment(self):
        self.assertEqual(classify_intent("is a perfectly reasonable strategy"), INTENT_VAGUE_FRAGMENT)
        self.assertEqual(classify_intent("are in for a rude shock"), INTENT_VAGUE_FRAGMENT)
        self.assertEqual(classify_intent("on its head"), INTENT_VAGUE_FRAGMENT)
        self.assertEqual(classify_intent("can be arbitrarily interrupted"), INTENT_VAGUE_FRAGMENT)

    def test_classify_intent_multi_sentence_passage(self):
        passage = (
            "Any of these limits (IOPs, storage capacity, bandwidth) is a potential bottleneck for a cloud provider. "
            "For instance, the cloud provider might have a disk storing 3 TB of data but hitting maximum IOPs. "
            "An alternative to leaving the remaining 7 TB empty is to sell the empty space without selling IOPs. "
            "Or, more specifically, sell cheap storage space and expensive IOPs to discourage reads."
        )
        self.assertEqual(classify_intent(passage), INTENT_MULTI_SENTENCE)

    def test_classify_intent_author_question(self):
        self.assertEqual(classify_intent("Why would you want to run your own servers instead of using serverless?"), INTENT_AUTHOR_QUESTION)
        self.assertEqual(classify_intent("How is this possible?"), INTENT_AUTHOR_QUESTION)

    def test_extract_enclosing_subject_vague_fragment(self):
        sentence = (
            "Moving on-premises servers one by one to VMs in the cloud—known as simple lift and shift—is a perfectly "
            "reasonable strategy for the initial phase of cloud migration, especially when facing a lease cliff."
        )
        selection = "is a perfectly reasonable strategy"
        subject = extract_enclosing_subject(sentence, selection)
        self.assertEqual(
            subject,
            "Moving on-premises servers one by one to VMs in the cloud—known as simple lift and shift",
        )

        sent2 = "In addition, database indexing is critical for high-throughput query performance."
        sel2 = "is critical for high-throughput query performance"
        self.assertEqual(extract_enclosing_subject(sent2, sel2), "database indexing")

    def test_select_substantive_anchor_sentence_rejects_meta_transition(self):
        chunk = {
            "chunk_id": "c1",
            "chapter": "4",
            "heading": "Cloud",
            "text": (
                "Cloud\n"
                "Before we discuss the nuances of cloud architecture, it's helpful to pause for a brief detour on cloud economics. "
                "Enterprises that migrate to the cloud often make deployment errors on the pricing front.\n\n"
                "A Brief Detour on Cloud Economics\n\n"
                "To understand how to use cloud services efficiently through cloud native architecture, you need to know how clouds make money. "
                "This is an extremely complex concept and one on which cloud providers offer little transparency."
            ),
        }
        chosen_chunk, anchor = select_substantive_anchor_sentence(
            chunk, neighbors=[], selection="Cloud Economics", core_concept="Cloud Economics"
        )
        self.assertEqual(chosen_chunk["chunk_id"], "c1")
        self.assertNotIn("Before we discuss", anchor)
        self.assertNotIn("it's helpful to pause", anchor)
        self.assertIn("To understand how to use cloud services efficiently", anchor)

    def test_analyze_intent_comprehensive(self):
        chunk = {
            "chunk_id": "c1",
            "chapter": "4",
            "heading": "Cloud",
            "text": (
                "Cloud\n"
                "Moving on-premises servers one by one to VMs in the cloud—known as simple lift and shift—is a perfectly "
                "reasonable strategy for the initial phase of cloud migration."
            ),
        }
        info = analyze_intent("is a perfectly reasonable strategy", heading="Cloud", chunk=chunk)
        self.assertEqual(info["intent_type"], INTENT_VAGUE_FRAGMENT)
        self.assertEqual(
            info["subject"],
            "Moving on-premises servers one by one to VMs in the cloud—known as simple lift and shift",
        )


class AntiGibberishCoherenceTests(unittest.TestCase):
    def test_is_coherent_gloss_rejects_screenshot4_gibberish(self):
        gibberish = (
            "The sentence 0 negative again selects reads the cloud readers. "
            "a cloud provider might have a disk of maximum again reads the space again. The readers also."
        )
        self.assertFalse(_is_coherent_gloss(gibberish))

    def test_is_coherent_gloss_rejects_short_and_fragments(self):
        self.assertFalse(_is_coherent_gloss("Too short."))
        self.assertFalse(_is_coherent_gloss("A complete thought but ends with the."))
        self.assertFalse(_is_coherent_gloss("A complete thought but ends with also."))

    def test_is_coherent_gloss_rejects_word_repetition_loops(self):
        loop_sent = "The disk reads data and reads cache and reads memory continuously."
        self.assertFalse(_is_coherent_gloss(loop_sent))

        adjacent_repeat = "The disk reads reads the blocks."
        self.assertFalse(_is_coherent_gloss(adjacent_repeat))

    def test_is_coherent_gloss_rejects_meta_commentary(self):
        meta1 = "The section introduces cloud economics to prepare readers for architecture."
        meta2 = "This chapter discusses data storage and retrieval systems."
        meta3 = "The authors mention cloud economics to provide background."
        meta4 = "The passage explains the concept in detail."
        self.assertFalse(_is_coherent_gloss(meta1))
        self.assertFalse(_is_coherent_gloss(meta2))
        self.assertFalse(_is_coherent_gloss(meta3))

    def test_is_coherent_gloss_accepts_good_explanations(self):
        good1 = "To understand how to use cloud services efficiently through cloud native architecture, you need to know how clouds make money."
        good2 = "The highlighted phrase refers to moving on-premises servers one by one to VMs in the cloud, explaining why lift and shift is acceptable initially."
        good3 = "Limits on IOPs, storage capacity, and bandwidth create bottlenecks that encourage providers to price resources to discourage overconsumption."
        self.assertTrue(_is_coherent_gloss(good1))
        self.assertTrue(_is_coherent_gloss(good2))
        self.assertTrue(_is_coherent_gloss(good3))

    def test_clean_boilerplate_gloss_rewrites_the_passage(self):
        raw_word = "The passage explains that cloud storage pricing depends on access patterns."
        cleaned_word = _clean_boilerplate_gloss(raw_word, selection="Cloud")
        self.assertTrue(cleaned_word.startswith("The highlighted word"))
        self.assertNotIn("The passage", cleaned_word)

        raw_phrase = "This passage describes the trade-offs in cloud economics."
        cleaned_phrase = _clean_boilerplate_gloss(raw_phrase, selection="Cloud Economics")
        self.assertTrue(cleaned_phrase.startswith("The highlighted phrase"))
        self.assertNotIn("This passage", cleaned_phrase)

        raw_in_passage = "In this passage, cloud providers charge for bandwidth and IOPs."
        cleaned_in = _clean_boilerplate_gloss(raw_in_passage, selection="IOPS")
        self.assertFalse(cleaned_in.lower().startswith("in this passage"))


class DynamicFollowupPillTests(unittest.TestCase):
    def test_compute_dynamic_followups_basic_constraints(self):
        chunk = {
            "chunk_id": "c1",
            "chapter": "4",
            "heading": "Cloud Economics",
            "text": (
                "Cloud Economics\n"
                "Understanding cloud native systems is essential for two reasons. "
                "First, modern systems require rapid iteration. "
                "Second, resource pricing varies dynamically. "
                "Limits on IOPS and storage bandwidth represent severe bottlenecks for high-throughput applications."
            ),
        }
        followups = compute_dynamic_followups(chunk, neighbors=[], mode="explain")
        self.assertIsInstance(followups, list)
        self.assertLessEqual(len(followups), 3)
        self.assertEqual(len(set(followups)), len(followups), "Followups must be unique")
        for pill in followups:
            self.assertLessEqual(len(pill), 45, f"Pill too long: {pill!r}")
            self.assertTrue(pill.endswith("?") or pill.lower().startswith("explain"), f"Pill should be a question or explanation request: {pill!r}")
        # Slot 1 should recognize "essential for two reasons"
        self.assertIn("What are the specific reasons?", followups)
        # Slot 2 should recognize pricing/bottlenecks/trade-offs
        self.assertTrue(any(kw in followups[1].lower() for kw in ("trade-offs", "bottlenecks", "risks")))

    def test_compute_dynamic_followups_term_extraction_and_neighbors(self):
        chunk = {
            "chunk_id": "c1",
            "chapter": "5",
            "heading": "Storage Systems",
            "text": (
                "Storage Systems\n"
                "Distributed storage models often encounter significant trade-offs between consistency and latency. "
                "An event streaming engine such as (Apache Beam) provides unified stream processing."
            ),
        }
        neighbor = {
            "chunk_id": "c2",
            "chapter": "5",
            "heading": "Dataflow Engine",
            "text": "Dataflow Engine\nDataflow execution coordinates parallel workers.",
        }
        followups = compute_dynamic_followups(chunk, neighbors=[neighbor], mode="explain")
        self.assertLessEqual(len(followups), 3)
        self.assertEqual(len(set(followups)), len(followups))
        for pill in followups:
            self.assertLessEqual(len(pill), 45)
        joined = " ".join(followups)
        self.assertTrue("trade-offs" in joined.lower() or "apache beam" in joined.lower() or "dataflow" in joined.lower())

    def test_compute_dynamic_followups_author_question_capture(self):
        chunk = {
            "chunk_id": "c3",
            "chapter": "6",
            "heading": "Query Engines",
            "text": (
                "Query Engines\n"
                "How is this possible? "
                "A vectorized query engine processes arrays of column values simultaneously to maximize CPU cache locality. "
                "However, hardware costs can become prohibitive."
            ),
        }
        followups = compute_dynamic_followups(chunk, neighbors=[], mode="explain")
        self.assertIn("How is this possible?", followups)
        for pill in followups:
            self.assertLessEqual(len(pill), 45)

    def test_compute_dynamic_followups_deduplication_and_cap(self):
        chunk = {
            "chunk_id": "c4",
            "chapter": "7",
            "heading": "Pipeline Resiliency",
            "text": (
                "Pipeline Resiliency\n"
                "Data engineers must evaluate the key trade-offs in distributed computing. "
                "There are several stages in the pipeline. "
                "What are the key trade-offs? "
                "What are the main stages?"
            ),
        }
        followups = compute_dynamic_followups(chunk, neighbors=[], mode="explain")
        self.assertLessEqual(len(followups), 3)
        self.assertEqual(len(set(followups)), len(followups))


class AdvanceFollowupQuoteTests(unittest.TestCase):
    def test_advance_reasons_skips_lead_in(self):
        chunk = {
            "chunk_id": "c1",
            "chapter": "1",
            "heading": "Why Cloud Architecture",
            "text": (
                "Why Cloud Architecture\n"
                "Understanding cloud economics is essential for two reasons. "
                "First, resource pricing directly dictates architecture choices. "
                "Second, unmonitored deployments can lead to unexpected cost overruns."
            ),
        }
        prior_quote = "Understanding cloud economics is essential for two reasons."
        adv = _advance_followup_quote(
            chunk,
            neighbors=[],
            prior_quote=prior_quote,
            followup_question="What are the specific reasons?",
        )
        self.assertIsNotNone(adv)
        self.assertNotEqual(adv, prior_quote)
        self.assertTrue(adv.startswith("First,"), f"Expected 'First, ...', got {adv!r}")

    def test_advance_example_skips_definition(self):
        chunk = {
            "chunk_id": "c2",
            "chapter": "2",
            "heading": "Bottlenecks",
            "text": (
                "Bottlenecks\n"
                "Any of these limits is a potential bottleneck for a cloud provider. "
                "For instance, the cloud provider might have a disk storing 3 TB of data but hitting maximum IOPS. "
                "This creates an imbalance across resources."
            ),
        }
        prior_quote = "Any of these limits is a potential bottleneck for a cloud provider."
        adv = _advance_followup_quote(
            chunk,
            neighbors=[],
            prior_quote=prior_quote,
            followup_question="Can you give an example of this?",
        )
        self.assertIsNotNone(adv)
        self.assertNotEqual(adv, prior_quote)
        self.assertTrue(adv.startswith("For instance,"), f"Expected 'For instance, ...', got {adv!r}")

    def test_advance_risk_skips_intro(self):
        chunk = {
            "chunk_id": "c3",
            "chapter": "3",
            "heading": "Migration",
            "text": (
                "Migration\n"
                "Moving on-premises servers to cloud VMs is a common first step. "
                "The main risk of this approach is that organizational patterns ossify without modern tooling. "
                "Careful planning is required to avoid this trap."
            ),
        }
        prior_quote = "Moving on-premises servers to cloud VMs is a common first step."
        adv = _advance_followup_quote(
            chunk,
            neighbors=[],
            prior_quote=prior_quote,
            followup_question="What are the risks or pitfalls?",
        )
        self.assertIsNotNone(adv)
        self.assertNotEqual(adv, prior_quote)
        self.assertIn("main risk", adv)

    def test_advance_bypasses_on_simplification(self):
        chunk = {
            "chunk_id": "c4",
            "chapter": "4",
            "heading": "Technical Concept",
            "text": (
                "Technical Concept\n"
                "Vectorized execution processes data arrays in register space. "
                "This optimizes cache lines and reduces branch mispredictions."
            ),
        }
        prior_quote = "Vectorized execution processes data arrays in register space."
        adv = _advance_followup_quote(
            chunk,
            neighbors=[],
            prior_quote=prior_quote,
            followup_question="Can you explain this in simpler words?",
        )
        self.assertIsNone(adv, "Simplification request must bypass citation advancing")


if __name__ == "__main__":
    unittest.main()
