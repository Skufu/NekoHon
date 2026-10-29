"""Regression tests for the broken comparison follow-up. No Ollama, no server.

The failing trace (2026-10-29 baseline, rows 82-83) answered "How does this
compare to LLM?" with a chapter-heading fragment quoted and the template
"In Chapter 1. From LLMs to Agents: , AI connects to this topic: ..." as the
gloss. These tests pin the three fixes: whole-word entity matching, no
template over a live gloss, and a real comparison branch that quotes a
contrastive sentence.
"""

import unittest
from unittest import mock

import answer as A
from answer import (
    _advance_followup_quote,
    _append_asked_as,
    _comparison_body,
    _comparison_quote,
    _comparison_side_tokens,
    _comparison_sides,
    _ensure_answer_gloss,
    _evidence_quote,
    _extract_query_entities,
    _leading_heading_lines,
    _prose_heading,
    _side_covered,
    _starts_with_heading_line,
    parse_completion,
    respond,
)
from prompt import COMPARE_SYSTEM, REFUSAL


AI_AGENT_HEADING = "Chapter 1. From LLMs to Agents: "

AI_AGENT_CHUNK = {
    "chunk_id": "ch01-001",
    "chapter": "1",
    "heading": AI_AGENT_HEADING,
    "text": (
        "Chapter 1. From LLMs to Agents:\n"
        "The Foundational Blueprint\n"
        "One of the defining traits of human intelligence is the way we combine "
        "inner reasoning with concrete actions, and this maps surprisingly well "
        "to how large language model (LLM) agents operate when paired with tools."
    ),
}

AI_AGENT_QUOTE = (
    "From LLMs to Agents: The Foundational Blueprint One of the defining traits "
    "of human intelligence is the way we combine inner reasoning with concrete "
    "actions, and this maps surprisingly well to how large language model (LLM) "
    "agents operate when paired with tools."
)

CONTRAST_PASSAGE = {
    "chunk_id": "ch01-002",
    "chapter": "1",
    "heading": "From LLMs to Agents",
    "text": (
        "An LLM agent is a large language model embedded in a loop of reasoning, "
        "acting, and feedback, where it can call external tools and adapt its "
        "behavior based on results. Unlike a standalone LLM, which is limited to "
        "static text generation, an agent operates as a decision-making entity "
        "within a workflow."
    ),
}

CONTRAST_SENTENCE = (
    "Unlike a standalone LLM, which is limited to static text generation, an "
    "agent operates as a decision-making entity within a workflow."
)

DEFINITION_SENTENCE = (
    "An LLM agent is a large language model embedded in a loop of reasoning, "
    "acting, and feedback, where it can call external tools and adapt its "
    "behavior based on results."
)


def _followup_body(quote, chunk):
    return {
        "answer": f'[Ch. {chunk["chapter"]}] "{quote}"\nRaw gloss.',
        "citations": [{
            "chunk_id": chunk["chunk_id"],
            "chapter": str(chunk["chapter"]),
            "quote": quote,
        }],
        "figures": [],
        "refused": False,
    }


class LiveGlossTests(unittest.TestCase):
    def test_live_gloss_is_not_overwritten_by_the_followup_template(self):
        """The exact broken follow-up: the live gloss must survive."""
        stub = (
            "LLMs provide the reasoning and language capabilities that agents "
            "need to interact effectively with tools."
        )
        calls = []

        def generate(system, user, model):
            calls.append(system)
            return stub

        body = _ensure_answer_gloss(
            {"chunks": [AI_AGENT_CHUNK], "figures": []},
            _followup_body(AI_AGENT_QUOTE, AI_AGENT_CHUNK),
            "Regarding AI agent: How does this compare to LLM?",
            [AI_AGENT_CHUNK],
            is_live=True,
            history=[{
                "question": "What is an LLM agent?",
                "answer": (
                    '[Ch. 1] "An LLM agent is a large language model embedded '
                    'in a loop of reasoning."\nAn LLM agent acts on feedback.'
                ),
            }],
            heading=AI_AGENT_HEADING,
            model="stub",
            generate_fn=generate,
        )
        answer = body["answer"]
        self.assertNotIn("connects to this topic", answer)
        self.assertIn(stub, answer)
        self.assertTrue(calls)

    def test_query_entities_keep_llm_when_the_heading_has_llms(self):
        entities = _extract_query_entities(
            "Regarding AI agent: How does this compare to LLM?",
            AI_AGENT_HEADING,
        )
        self.assertIn("LLM", entities)

    def test_offline_template_still_aligns_the_entity(self):
        """is_live=False keeps the deterministic template, heading included."""
        chunk = {
            "chunk_id": "genomics_010",
            "chapter": "5",
            "heading": "High-Throughput Sequencing Formats",
            "text": (
                "High-Throughput Sequencing Formats\n"
                "FASTQ files represent biological sequencing reads with "
                "corresponding per-base quality scores. "
                "Aligners like BWA-MEM map raw reads from FASTQ files against "
                "reference genomes to identify genomic variations."
            ),
        }
        prior_quote = (
            "FASTQ files represent biological sequencing reads with "
            "corresponding per-base quality scores."
        )
        adv_quote = (
            "Aligners like BWA-MEM map raw reads from FASTQ files against "
            "reference genomes to identify genomic variations."
        )
        body = _ensure_answer_gloss(
            {"chunks": [chunk], "figures": []},
            _followup_body(adv_quote, chunk),
            "How does this relate to BWA-MEM?",
            [chunk],
            is_live=False,
            history=[{
                "question": "What is FASTQ format?",
                "answer": f'[Ch. 5] "{prior_quote}"\nFASTQ stores reads and quality scores.',
            }],
            heading=chunk["heading"],
        )
        answer = body["answer"]
        self.assertIn("BWA-MEM", answer)
        self.assertIn("High-Throughput Sequencing Formats", answer)

    def test_prose_heading_drops_the_chapter_prefix_and_colon(self):
        self.assertEqual(
            _prose_heading("Chapter 1. From LLMs to Agents: "),
            "From LLMs to Agents",
        )
        self.assertEqual(
            _prose_heading("High-Throughput Sequencing Formats"),
            "High-Throughput Sequencing Formats",
        )

    def test_an_incoherent_live_gloss_is_replaced_by_a_coherent_template(self):
        chunk = {
            "chunk_id": "ch-agents",
            "chapter": "1",
            "heading": "Agents",
            "text": (
                "Agents\n"
                "An LLM agent is a large language model embedded in a loop of "
                "reasoning."
            ),
        }
        quote = (
            "An LLM agent is a large language model embedded in a loop of "
            "reasoning."
        )

        def generate(system, user, model):
            return "It is different."

        body = _ensure_answer_gloss(
            {"chunks": [chunk], "figures": []},
            _followup_body(quote, chunk),
            "Regarding AI agent: How does this compare to LLM?",
            [chunk],
            is_live=True,
            history=[{
                "question": "What is an LLM agent?",
                "answer": f'[Ch. 1] "{quote}"\nIt acts.',
            }],
            heading="Agents",
            model="stub",
            generate_fn=generate,
        )
        self.assertNotIn("It is different.", body["answer"])
        self.assertIn("connects to this topic", body["answer"])

    def test_an_incoherent_live_gloss_is_dropped_when_the_template_fails(self):
        chunk = {
            "chunk_id": "ch-fail",
            "chapter": "1",
            "heading": "The section discusses agents",
            "text": (
                "The section discusses agents\n"
                "An LLM agent is a large language model embedded in a loop of "
                "reasoning."
            ),
        }
        quote = (
            "An LLM agent is a large language model embedded in a loop of "
            "reasoning."
        )

        def generate(system, user, model):
            return "It is different."

        body = _ensure_answer_gloss(
            {"chunks": [chunk], "figures": []},
            _followup_body(quote, chunk),
            "Regarding AI agent: How does this compare to LLM?",
            [chunk],
            is_live=True,
            history=[{
                "question": "What is an LLM agent?",
                "answer": f'[Ch. 1] "{quote}"\nIt acts.',
            }],
            heading="The section discusses agents",
            model="stub",
            generate_fn=generate,
        )
        self.assertNotIn("It is different.", body["answer"])
        self.assertNotIn("connects to this topic", body["answer"])


class HeadingGlueTests(unittest.TestCase):
    def test_advance_skips_a_colon_heading_glued_sentence(self):
        chunk = {
            "chunk_id": "ch01-001",
            "chapter": "1",
            "heading": "Chapter 1. From LLMs to Agents:",
            "text": (
                "Chapter 1. From LLMs to Agents:\n"
                "The Foundational Blueprint\n"
                "One of the defining traits of human intelligence is the way we "
                "combine inner reasoning with concrete actions, and this maps "
                "surprisingly well to how large language model (LLM) agents "
                "operate when paired with tools.\n"
                "An LLM alone only generates text."
            ),
        }
        quote = _advance_followup_quote(
            chunk,
            neighbors=[],
            prior_quote="",
            followup_question="How does this compare to LLM?",
        )
        self.assertFalse(quote and "The Foundational Blueprint" in quote)
        self.assertFalse(quote and quote.startswith("Chapter 1."))

    def test_advance_skips_a_subtitle_glued_sentence(self):
        chunk = {
            "chunk_id": "ch01-001",
            "chapter": "1",
            "heading": "Chapter 1. From LLMs to Agents:",
            "text": (
                "Chapter 1. From LLMs to Agents:\n"
                "The Foundational Blueprint\n"
                "External support, such as code libraries or documentation, maps "
                "to tools like retrieval systems or web searches, which refine "
                "the output beyond the model's own raw ability."
            ),
        }
        quote = _advance_followup_quote(
            chunk,
            neighbors=[],
            prior_quote="",
            followup_question="Why does this matter?",
        )
        self.assertFalse(quote and "The Foundational Blueprint" in quote)

    def test_advance_skips_a_subtitle_when_the_first_line_has_no_colon(self):
        # Without the colon the old guard cannot see the glue; the leading-line
        # guard must skip the subtitle candidate itself.
        chunk = {
            "chunk_id": "ch01-001",
            "chapter": "1",
            "heading": "Chapter 1. From LLMs to Agents",
            "text": (
                "Chapter 1. From LLMs to Agents\n"
                "The Foundational Blueprint\n"
                "External support, such as code libraries or documentation, maps "
                "to tools like retrieval systems or web searches, which refine "
                "the output beyond the model's own raw ability."
            ),
        }
        quote = _advance_followup_quote(
            chunk,
            neighbors=[],
            prior_quote="",
            followup_question="What external support is mentioned?",
        )
        self.assertFalse(quote and "The Foundational Blueprint" in quote)

    def test_evidence_quote_drops_the_subtitle_line(self):
        chunk = {
            "chunk_id": "ch01-002",
            "chapter": "1",
            "heading": "Chapter 1. From LLMs to Agents:",
            "text": (
                "Chapter 1. From LLMs to Agents:\n"
                "The Foundational Blueprint\n"
                "External support, such as code libraries or documentation, maps "
                "to tools like retrieval systems or web searches, which refine "
                "the output beyond the model's own raw ability."
            ),
        }
        claim = (
            "External support, such as code libraries or documentation, maps to "
            "tools like retrieval systems or web searches, which refine the "
            "output beyond the model's own raw ability."
        )
        quote = _evidence_quote(claim, chunk)
        self.assertTrue(quote.startswith("External support"), quote)
        self.assertNotIn("The Foundational Blueprint", quote)

    def test_leading_heading_lines_does_not_take_a_body_sentence_for_a_subtitle(self):
        storage = {
            "chunk_id": "ch02-001",
            "chapter": "2",
            "heading": "Chapter 2. Storage",
            "text": (
                "Chapter 2. Storage\n"
                "Storage is the cornerstone of the data engineering lifecycle."
            ),
        }
        self.assertEqual(_leading_heading_lines(storage), ["Storage"])
        self.assertFalse(
            _starts_with_heading_line(
                "Storage is the cornerstone of the data engineering lifecycle.",
                storage,
            )
        )

        ai = {
            "chunk_id": "ch01-001",
            "chapter": "1",
            "heading": "Chapter 1. From LLMs to Agents:",
            "text": (
                "Chapter 1. From LLMs to Agents:\n"
                "The Foundational Blueprint\n"
                "External support, such as code libraries or documentation, maps "
                "to tools like retrieval systems or web searches."
            ),
        }
        self.assertEqual(
            _leading_heading_lines(ai),
            ["From LLMs to Agents:", "The Foundational Blueprint"],
        )
        self.assertTrue(
            _starts_with_heading_line(
                "The Foundational Blueprint External support, such as code "
                "libraries or documentation, maps to tools like retrieval systems "
                "or web searches.",
                ai,
            )
        )

    def test_advance_keeps_a_body_sentence_that_repeats_the_heading(self):
        chunk = {
            "chunk_id": "ch02-001",
            "chapter": "2",
            "heading": "Chapter 2. Storage",
            "text": (
                "Chapter 2. Storage\n"
                "Storage is the cornerstone of the data engineering lifecycle."
            ),
        }
        quote = _advance_followup_quote(
            chunk,
            neighbors=[],
            prior_quote="",
            followup_question="Why is storage the cornerstone?",
        )
        self.assertIsNotNone(quote)
        self.assertIn("cornerstone", quote)


class ComparisonSidesTests(unittest.TestCase):
    def test_regarding_prefix_resolves_to_ai_agent_and_llm(self):
        self.assertEqual(
            _comparison_sides("Regarding AI agent: How does this compare to LLM?"),
            ("AI agent", "LLM"),
        )

    def test_what_separates_form(self):
        self.assertEqual(
            _comparison_sides("What separates an AI agent from an LLM?"),
            ("AI agent", "LLM"),
        )

    def test_how_is_different_from_form(self):
        self.assertEqual(
            _comparison_sides("How is an AI agent different from an LLM?"),
            ("AI agent", "LLM"),
        )

    def test_how_does_relate_to_form(self):
        self.assertEqual(
            _comparison_sides("How does an LLM agent relate to an LLM?"),
            ("LLM agent", "LLM"),
        )

    def test_generic_relational_target_is_not_a_comparison(self):
        self.assertIsNone(
            _comparison_sides("How does ingestion relate to the workflow?")
        )
        self.assertIsNone(
            _comparison_sides("How does ingestion relate to this topic?")
        )

    def test_a_generic_target_is_valid_for_a_compare_to_question(self):
        self.assertEqual(
            _comparison_sides(
                "Regarding AI agent: How does this compare to a workflow?"
            ),
            ("AI agent", "workflow"),
        )

    def test_a_non_comparison_question_has_no_sides(self):
        self.assertIsNone(_comparison_sides("What are the key trade-offs?"))

    def test_plain_llm_modifier_names_the_llm_side(self):
        for side in ("plain LLM", "standalone LLM", "regular LLM", "normal LLM"):
            with self.subTest(side=side):
                tokens = _comparison_side_tokens(side)
                self.assertEqual(tokens, ["llm"])
                self.assertIsNotNone(
                    _side_covered(tokens, [{"heading": "", "text": "An LLM generates text."}])
                )


class ComparisonQuoteTests(unittest.TestCase):
    def test_contrast_sentence_beats_the_definition(self):
        quotes = _comparison_quote(("AI agent", "LLM"), [CONTRAST_PASSAGE])
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0][1], CONTRAST_SENTENCE)
        self.assertNotEqual(quotes[0][1], DEFINITION_SENTENCE)

    def test_two_sides_fall_back_to_one_sentence_each(self):
        passage = {
            "chunk_id": "p-two",
            "chapter": "2",
            "heading": "Two Systems",
            "text": (
                "Batch processing runs a job over stored data. "
                "Stream processing handles each record as it arrives."
            ),
        }
        quotes = _comparison_quote(("batch processing", "stream processing"), [passage])
        self.assertEqual(len(quotes), 2)
        self.assertTrue(any("Batch" in sentence for _, sentence in quotes))
        self.assertTrue(any("Stream" in sentence for _, sentence in quotes))


class ParseCompletionContrastTests(unittest.TestCase):
    def test_a_correct_dual_citation_is_preserved(self):
        other = {
            "chunk_id": "ch-other",
            "chapter": "1",
            "heading": "Contrast",
            "text": (
                "In contrast to older systems, this section explains agents. "
                "An LLM agent is a large language model embedded in a loop of "
                "reasoning."
            ),
        }
        cited = {
            "chunk_id": "ch-cited",
            "chapter": "1",
            "heading": "Agents",
            "text": (
                "An agent acts on tools, whereas a standalone LLM only "
                "generates text."
            ),
        }
        completion = (
            '[Ch. 1] "An agent acts on tools, whereas a standalone LLM only '
            'generates text."'
        )
        body = parse_completion(
            completion,
            [other, cited],
            question="What is the difference between an AI agent and an LLM?",
        )
        self.assertEqual(
            [item["chunk_id"] for item in body["citations"]], ["ch-cited"]
        )
        self.assertIn(
            "whereas a standalone LLM only generates text",
            body["citations"][0]["quote"],
        )

    def test_two_citations_are_not_collapsed_by_the_contrast_switch(self):
        first = {
            "chunk_id": "ch-a",
            "chapter": "1",
            "heading": "Agents",
            "text": (
                "An LLM agent is a large language model embedded in a loop of "
                "reasoning."
            ),
        }
        second = {
            "chunk_id": "ch-b",
            "chapter": "1",
            "heading": "Schedules",
            "text": "Batch processing runs on a schedule.",
        }
        contrast = {
            "chunk_id": "ch-c",
            "chapter": "1",
            "heading": "Contrast",
            "text": (
                "Unlike a standalone LLM, an agent operates as a decision-making "
                "entity within a workflow."
            ),
        }
        completion = (
            '[Ch. 1] "An LLM agent is a large language model embedded in a loop '
            'of reasoning."\n'
            '[Ch. 1] "Batch processing runs on a schedule."'
        )
        body = parse_completion(
            completion,
            [first, second, contrast],
            question="What is the difference between an AI agent and an LLM?",
        )
        self.assertEqual(len(body["citations"]), 2)


class ComparisonBodyTests(unittest.TestCase):
    def _context(self):
        return {
            "passages": [CONTRAST_PASSAGE],
            "asked": "What is the difference between an AI agent and an LLM?",
        }

    def _index(self):
        return {
            "chunks": [CONTRAST_PASSAGE],
            "figures": [],
            "embedder": "nomic-embed-text",
        }

    def test_gloss_naming_both_sides_keeps_the_contrast_quote(self):
        gloss = (
            "An AI agent uses an LLM to reason, act, and call tools, whereas a "
            "standalone LLM only generates text."
        )

        def generate(system, user, model):
            return gloss

        body = _comparison_body(
            self._index(), self._context(), ("AI agent", "LLM"),
            generate, "stub", None, [],
        )
        self.assertIsNotNone(body)
        assert body is not None
        self.assertFalse(body["refused"])
        self.assertEqual(body["citations"][0]["quote"], CONTRAST_SENTENCE)
        self.assertIn(gloss, body["answer"])
        self.assertNotIn("connects to this topic", body["answer"])

    def test_a_one_sided_gloss_is_not_emitted(self):
        calls = []

        def generate(system, user, model):
            calls.append(user)
            return "An LLM generates text from a prompt."

        body = _comparison_body(
            self._index(), self._context(), ("AI agent", "LLM"),
            generate, "stub", None, [],
        )
        self.assertIsNone(body)
        self.assertEqual(len(calls), 2)  # one retry with a stricter instruction

    def test_refusal_text_never_becomes_the_comparison_gloss(self):
        def generate(system, user, model):
            return REFUSAL

        body = _comparison_body(
            self._index(), self._context(), ("AI agent", "LLM"),
            generate, "stub", None, [],
        )
        self.assertIsNone(body)


class AskedAsTests(unittest.TestCase):
    def test_bare_comparison_label_keeps_the_asked_as_line(self):
        index = {
            "chunks": [CONTRAST_PASSAGE],
            "figures": [],
            "embedder": "nomic-embed-text",
        }

        def generate(system, user, model):
            if system == COMPARE_SYSTEM:
                return (
                    "An AI agent uses an LLM together with tools, whereas a "
                    "standalone LLM only generates text."
                )
            return REFUSAL

        with mock.patch.object(
            A, "retrieval_context",
            return_value={
                "question": "AI agent vs LLM",
                "asked": "What is the difference between AI agent and LLM?",
                "passages": [CONTRAST_PASSAGE],
                "reading": None,
                "word_map": {},
            },
        ):
            body = respond(
                index,
                "AI agent vs LLM",
                generate_fn=generate,
                model="stub",
            )
        self.assertFalse(body["refused"])
        asked = "What is the difference between AI agent and LLM?"
        self.assertTrue(
            body["answer"].endswith(f'\nAsked as: "{asked}"'),
            body["answer"],
        )

        base = body["answer"]
        self.assertEqual(
            _append_asked_as(base, asked, "AI agent vs LLM", "AI agent", []),
            base,
        )
        self.assertEqual(
            _append_asked_as(
                base, asked, "AI agent vs LLM", "",
                [{"question": "What is an AI agent?", "answer": "x"}],
            ),
            base,
        )


class ComparisonEarlyReturnTests(unittest.TestCase):
    def _generate(self, system, user, model):
        if system == COMPARE_SYSTEM:
            return (
                "An AI agent uses an LLM together with tools, whereas a "
                "standalone LLM only generates text."
            )
        return REFUSAL

    def test_reading_repair_is_disclosed(self):
        asked = "What is the difference between an AI agent and an LLM?"
        index = {
            "chunks": [CONTRAST_PASSAGE],
            "figures": [],
            "embedder": "nomic-embed-text",
        }
        context = {
            "question": asked,
            "asked": asked,
            "passages": [CONTRAST_PASSAGE],
            "reading": {"reading": asked},
            "word_map": {},
        }
        with mock.patch.object(A, "retrieval_context", return_value=context):
            body = respond(
                index, asked, generate_fn=self._generate, model="stub",
            )
        self.assertFalse(body["refused"])
        self.assertIn(f'Read as: "{asked}"', body["answer"])

    def test_followups_use_a_chunk_loaded_from_the_index(self):
        one_sided = {
            "chunk_id": "p-ai",
            "chapter": "1",
            "heading": "Agents",
            "text": (
                "An AI agent is a system that uses a language model to think "
                "and act."
            ),
            "score": 0.9,
        }
        extra = {
            "chunk_id": "p-llm",
            "chapter": "1",
            "heading": "Agents",
            "text": (
                "Unlike a standalone LLM, an agent operates as a "
                "decision-making entity within a workflow."
            ),
            "score": 0.8,
        }
        index = {
            "chunks": [one_sided, extra],
            "figures": [],
            "embedder": "nomic-embed-text",
        }
        seen = {}

        def capture(lead_chunk, lead_neighbors, **kwargs):
            seen["lead"] = lead_chunk.get("chunk_id")
            return []

        with mock.patch.object(
            A, "retrieval_context",
            return_value={
                "question": "What is the difference between an AI agent and an LLM?",
                "asked": "What is the difference between an AI agent and an LLM?",
                "passages": [one_sided],
                "reading": None,
                "word_map": {},
            },
        ), mock.patch.object(A, "search", return_value=[extra]), \
                mock.patch.object(A, "compute_dynamic_followups", side_effect=capture):
            body = respond(
                index,
                "What is the difference between an AI agent and an LLM?",
                generate_fn=self._generate,
                model="stub",
            )
        self.assertFalse(body["refused"])
        self.assertEqual(body["citations"][0]["chunk_id"], "p-llm")
        self.assertEqual(seen.get("lead"), "p-llm")


if __name__ == "__main__":
    unittest.main()
