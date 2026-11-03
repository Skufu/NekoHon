"""A book's kind decides how it is answered.

Technical books keep the measured strict profile: temperature 0, five
passages, one quote plus one gloss line. Fiction gets the loose one: a warmer
sampler, eight passages, and the model's own paragraph kept. The citation
gate is the same in both, so these tests also pin that a fiction answer still
cites passages the book contains.
"""

import io
import json
import unittest
from unittest import mock

import answer as A
import bookkind
import prompt
from prompt import (
    FICTION_GENERATION_OPTIONS,
    GENERATION_OPTIONS,
    SPELL_SYSTEM,
    SYSTEM,
    SYSTEM_FICTION,
)


def chunk(chunk_id, chapter, text, heading=""):
    return {
        "chunk_id": chunk_id,
        "chapter": chapter,
        "heading": heading,
        "text": text,
        "source": f"section-{chapter}",
        "score": 0.9,
    }


# Dialogue-dense text: the detector reads a novel off the quotes.
FICTION_CHUNKS = [
    chunk("f-1", "1",
          "“You are late,” Sandor said, and set the cup down. "
          "“The road from the Second City is not kind at night.” "
          "“I know,” Rudeus said. “I stopped at the tavern.”"),
    chunk("f-2", "2",
          "“Did you see the Superd?” Eris asked. "
          "“They slaughtered a whole village,” Rudeus said. "
          "“Then we ride at dawn,” Eris said, and she meant it."),
    chunk("f-3", "3",
          "“My third eye sees what yours cannot,” Ruijerd said. "
          "“Keep behind me,” he told them, “and do not look back.”"),
]

TECH_CHUNKS = [
    chunk("t-1", "1",
          "Change data capture streams row-level changes from a database so "
          "downstream systems stay in sync with the source of truth."),
    chunk("t-2", "2",
          "Batch processing runs on a schedule and handles large volumes of "
          "records at once, trading latency for throughput."),
]

ANSWER_REPLY = (
    '[Ch. 1] "“You are late,” Sandor said, and set the cup down."\n'
    '[Ch. 2] "“Then we ride at dawn,” Eris said, and she meant it."\n'
    "Sandor is waiting on Rudeus when he comes back from the road, and Eris "
    "turns the news about the Superd into a decision to leave at first light. "
    "Neither of them argues with him; they act on what he brings."
)


def scripted(replies):
    """generate_fn that walks the replies on the answer prompt only.

    A question word the fixture does not hold sends the reading repair to the
    same function with SPELL_SYSTEM; that pass gets an empty correction and is
    not counted, so a test's call count is the fiction rounds.
    """
    queue = list(replies)
    calls = []

    def generate(system, user, model):
        if system == SPELL_SYSTEM:
            return ""
        calls.append(system)
        return queue[min(len(calls), len(queue)) - 1]

    return generate, calls


def fiction_index(extra=None):
    index = {
        "book_id": "a-novel",
        "title": "A Novel",
        "author": "Someone",
        "chunks": [dict(c) for c in FICTION_CHUNKS],
        "figures": [],
    }
    index.update(extra or {})
    return index


def tech_index(extra=None):
    index = {
        "book_id": "a-tech-book",
        "title": "A Technical Book",
        "author": "Someone",
        "chunks": [dict(c) for c in TECH_CHUNKS],
        "figures": [],
    }
    index.update(extra or {})
    return index


class DetectTest(unittest.TestCase):
    def test_dialogue_dense_text_is_fiction(self):
        self.assertEqual(bookkind.detect_kind(fiction_index()), bookkind.FICTION)

    def test_technical_prose_is_nonfiction(self):
        self.assertEqual(bookkind.detect_kind(tech_index()), bookkind.NONFICTION)

    def test_empty_index_is_nonfiction(self):
        self.assertEqual(bookkind.detect_kind({"chunks": []}), bookkind.NONFICTION)

    def test_stored_kind_wins_over_the_guess(self):
        pinned = fiction_index({"kind": bookkind.NONFICTION})
        self.assertEqual(bookkind.kind(pinned), bookkind.NONFICTION)
        self.assertEqual(bookkind.for_index(pinned)["passage_limit"], 5)

    def test_unknown_stored_kind_is_ignored(self):
        self.assertEqual(
            bookkind.kind(tech_index({"kind": "poetry"})), bookkind.NONFICTION
        )

    def test_short_story_is_still_story(self):
        """A two-chunk story is fiction; the detector needs no minimum size."""
        index = {"book_id": "tiny", "chunks": [dict(c) for c in FICTION_CHUNKS[:1]],
                 "figures": []}
        self.assertEqual(bookkind.detect_kind(index), bookkind.FICTION)


class ProfileTest(unittest.TestCase):
    def test_fiction_profile_is_the_loose_one(self):
        settings = bookkind.for_index(fiction_index())
        self.assertEqual(settings["kind"], bookkind.FICTION)
        self.assertEqual(settings["system"], SYSTEM_FICTION)
        self.assertEqual(settings["passage_limit"], bookkind.FICTION_PASSAGE_LIMIT)
        self.assertGreater(settings["passage_limit"], bookkind.NONFICTION_PASSAGE_LIMIT)
        self.assertGreater(
            settings["options"]["temperature"],
            GENERATION_OPTIONS["temperature"],
        )
        self.assertEqual(
            settings["options"]["num_predict"], GENERATION_OPTIONS["num_predict"]
        )
        self.assertTrue(settings["keep_body"])

    def test_nonfiction_profile_is_unchanged(self):
        settings = bookkind.for_index(tech_index())
        self.assertEqual(settings["system"], SYSTEM)
        self.assertEqual(settings["passage_limit"], A.PASSAGE_LIMIT)
        self.assertEqual(settings["options"], GENERATION_OPTIONS)
        self.assertFalse(settings["keep_body"])


class PayloadTest(unittest.TestCase):
    """The sampler reaches Ollama, and a test double is left alone."""

    def generate_with(self, **kwargs):
        captured = {}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        body = json.dumps({"message": {"content": "ok"}, "eval_count": 1}).encode()

        def fake_urlopen(request, timeout=None):
            captured.update(json.loads(request.data.decode("utf-8")))
            return Response(body)

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            A.ollama_generate("sys", "user", "m", **kwargs)
        return captured

    def test_default_sampler_is_the_strict_one(self):
        payload = self.generate_with()
        self.assertEqual(payload["options"], GENERATION_OPTIONS)
        self.assertEqual(payload["options"]["temperature"], 0)

    def test_fiction_sampler_reaches_the_request(self):
        payload = self.generate_with(options=FICTION_GENERATION_OPTIONS)
        self.assertEqual(payload["options"], FICTION_GENERATION_OPTIONS)
        self.assertGreater(payload["options"]["temperature"], 0)

    def test_stream_request_takes_the_same_sampler(self):
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def __iter__(self):
                return iter([
                    json.dumps({"message": {"content": "ok"}}).encode(),
                    json.dumps({"done": True, "eval_count": 1}).encode(),
                ])

        def fake_urlopen(request, timeout=None):
            captured.update(json.loads(request.data.decode("utf-8")))
            return Response()

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            A.ollama_generate_stream(
                "sys", "user", "m", options=FICTION_GENERATION_OPTIONS,
            )
        self.assertEqual(captured["options"], FICTION_GENERATION_OPTIONS)

    def test_a_double_without_options_is_untouched(self):
        def double(system, user, model):
            return ""

        self.assertIs(A._with_generation_options(double, {"temperature": 1}), double)

    def test_binding_keeps_the_live_flag(self):
        bound = A._with_generation_options(A.ollama_generate, {"temperature": 1})
        self.assertTrue(bound._is_live)
        self.assertTrue(bound._accepts_options)


class WordsTest(unittest.TestCase):
    """The length target: 0 keeps the measured prompt, any other aims it."""

    def test_default_keeps_the_measured_prompts(self):
        self.assertIs(prompt.technical_system(), prompt.SYSTEM)
        self.assertIs(prompt.fiction_system(), prompt.SYSTEM_FICTION)
        self.assertIs(prompt.answer_gloss_system(), prompt.ANSWER_GLOSS_SYSTEM)
        self.assertIs(prompt.followup_gloss_system(), prompt.FOLLOWUP_GLOSS_SYSTEM)

    def test_technical_gloss_is_aimed_at_the_word_count(self):
        text = prompt.technical_system(120)
        self.assertIn("about 120 words of gloss", text)
        self.assertNotIn("one line of gloss", text)
        self.assertIn("Not in this book.", text)

    def test_fiction_paragraph_is_aimed_at_the_word_count(self):
        text = prompt.fiction_system(240)
        self.assertIn("one paragraph of about 240 words", text)
        self.assertNotIn("three to five sentences", text)
        self.assertIn("Not in this book.", text)

    def test_gloss_passes_are_aimed_too(self):
        self.assertIn("about 90 words", prompt.answer_gloss_system(90))
        self.assertIn("about 90 words", prompt.followup_gloss_system(90))
        self.assertNotIn("1 to 2 sentence", prompt.answer_gloss_system(90))

    def test_an_aimed_prompt_still_streams(self):
        self.assertTrue(prompt.is_quote_system(prompt.technical_system(120)))
        self.assertTrue(prompt.is_quote_system(prompt.fiction_system(240)))
        self.assertFalse(prompt.is_quote_system(prompt.answer_gloss_system(120)))

    def test_profile_carries_the_target_and_a_cap_that_fits_it(self):
        for kind, words, limit in (
            ("nonfiction", 200, A.PASSAGE_LIMIT),
            ("fiction", 200, bookkind.FICTION_PASSAGE_LIMIT),
        ):
            with self.subTest(kind=kind):
                original = (
                    bookkind.TECHNICAL_ANSWER_WORDS
                    if kind == "nonfiction"
                    else bookkind.FICTION_ANSWER_WORDS
                )
                try:
                    if kind == "nonfiction":
                        bookkind.TECHNICAL_ANSWER_WORDS = words
                    else:
                        bookkind.FICTION_ANSWER_WORDS = words
                    settings = bookkind.for_index(
                        fiction_index() if kind == "fiction" else tech_index()
                    )
                finally:
                    if kind == "nonfiction":
                        bookkind.TECHNICAL_ANSWER_WORDS = original
                    else:
                        bookkind.FICTION_ANSWER_WORDS = original
                self.assertEqual(settings["answer_words"], words)
                self.assertEqual(settings["passage_limit"], limit)
                self.assertGreaterEqual(
                    settings["options"]["num_predict"],
                    max(GENERATION_OPTIONS["num_predict"], words * 2),
                )
                self.assertIn(f"about {words} words", settings["system"])

    def test_a_paragraph_target_switches_the_gloss_prompt(self):
        line = prompt.answer_gloss_system(20)
        paragraph = prompt.answer_gloss_system(80)
        self.assertIn("about 20 words", line)
        self.assertIn("repeat the sentence verbatim", line)
        self.assertNotIn("paragraph of about", line)
        self.assertIn("paragraph of about 80 words", paragraph)
        self.assertNotIn("1 to 2 sentence", paragraph)
        # the guards that protect the reader survive the switch
        for text in (line, paragraph):
            self.assertIn("Do not use quotation marks", text)
            self.assertIn("Not in this book.", text)

    def test_a_comparison_answer_is_aimed_too(self):
        self.assertIn("about 70 plain words", prompt.compare_system(70))
        self.assertIs(prompt.compare_system(), prompt.COMPARE_SYSTEM)

    def test_an_aimed_answer_forces_the_gloss_pass(self):
        """A coherent first gloss is rewritten when a target is set."""
        generate, calls = scripted([
            '[Ch. 1] "Change data capture streams row-level changes."\nA change feed.',
            ("Change data capture copies row-level changes out of a database so "
             "downstream systems can follow them without reading the whole table."),
        ])
        generate._is_live = True
        original = bookkind.TECHNICAL_ANSWER_WORDS
        bookkind.TECHNICAL_ANSWER_WORDS = 80
        try:
            body = A.respond(
                tech_index(), "What is change data capture?",
                generate_fn=generate,
                search_fn=lambda idx, q, k=5: [dict(c) for c in TECH_CHUNKS],
                model="m",
            )
        finally:
            bookkind.TECHNICAL_ANSWER_WORDS = original
        self.assertEqual(len(calls), 2)
        self.assertIn("paragraph of about 80 words", calls[1])
        self.assertFalse(body["refused"])

    def test_zero_target_imposes_no_aim(self):
        """At the measured default no prompt carries a word count."""
        generate, calls = scripted([
            '[Ch. 1] "Change data capture streams row-level changes from a database '
            'so downstream systems stay in sync with the source of truth."\n'
            "Change data capture copies row-level changes so downstream systems follow them.",
        ])
        A.respond(
            tech_index(), "What is change data capture?",
            generate_fn=generate,
            search_fn=lambda idx, q, k=5: [dict(c) for c in TECH_CHUNKS],
            model="m",
        )
        for system in calls:
            self.assertNotIn("about ", system)

    def test_zero_keeps_the_profile_unchanged(self):
        settings = bookkind.for_index(tech_index())
        self.assertEqual(settings["answer_words"], 0)
        self.assertEqual(settings["options"], GENERATION_OPTIONS)
        self.assertEqual(settings["system"], SYSTEM)


class AnswerTest(unittest.TestCase):
    """What the reader gets: more passages, several citations, the paragraph."""

    def search_recorder(self, passages):
        calls = {}

        def search(index, question, k=5):
            calls["k"] = k
            calls["question"] = question
            return [dict(p) for p in passages]

        return search, calls

    def test_fiction_asks_for_more_passages_and_its_own_prompt(self):
        search, calls = self.search_recorder(FICTION_CHUNKS)
        seen = {}

        def generate(system, user, model):
            seen["system"] = system
            seen["user"] = user
            return ANSWER_REPLY

        body = A.respond(
            fiction_index(), "What happened when Rudeus came back?",
            generate_fn=generate, search_fn=search, model="m",
        )
        self.assertEqual(calls["k"], bookkind.FICTION_PASSAGE_LIMIT)
        self.assertEqual(seen["system"], SYSTEM_FICTION)
        self.assertFalse(body["refused"])

    def test_a_three_moment_answer_cites_each_moment(self):
        search, _ = self.search_recorder(FICTION_CHUNKS)

        def generate(system, user, model):
            return ANSWER_REPLY

        body = A.respond(
            fiction_index(), "What happened when Rudeus came back?",
            generate_fn=generate, search_fn=search, model="m",
        )
        self.assertEqual(
            [citation["chunk_id"] for citation in body["citations"]],
            ["f-1", "f-2"],
        )
        for citation in body["citations"]:
            self.assertIn(citation["quote"], ANSWER_REPLY)

    def test_the_paragraph_survives_instead_of_one_gloss_line(self):
        search, _ = self.search_recorder(FICTION_CHUNKS)

        def generate(system, user, model):
            return ANSWER_REPLY

        body = A.respond(
            fiction_index(), "What happened when Rudeus came back?",
            generate_fn=generate, search_fn=search, model="m",
        )
        answer_text = body["answer"]
        self.assertIn("Eris", answer_text)
        self.assertIn("Neither of them argues", answer_text)
        self.assertEqual(len([line for line in answer_text.splitlines() if line.strip()]), 3)

    def test_a_thin_first_answer_is_asked_again_and_merged(self):
        """The count comes from asking again, not from asking harder."""
        search, _ = self.search_recorder(FICTION_CHUNKS)
        generate, calls = scripted([
            '[Ch. 1] "“You are late,” Sandor said, and set the cup down."\n'
            "Sandor is waiting on Rudeus when he comes back.",
            '[Ch. 2] "“Then we ride at dawn,” Eris said, and she meant it."\n'
            "Eris turns the news about the Superd into a decision to leave.",
        ])
        body = A.respond(
            fiction_index(), "What happened when Rudeus came back?",
            generate_fn=generate, search_fn=search, model="m",
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [citation["chunk_id"] for citation in body["citations"]], ["f-1", "f-2"]
        )

    def test_a_scene_quote_is_cut_at_a_sentence_end(self):
        scene = ("“Look. There. It’s getting closer.” My eyes still couldn’t make "
                 "out anything. I strained my vision for a while, but still "
                 "nothing. Maybe Sandor was drunk and seeing things. “Should I "
                 "get a light?” I suggested. “…Can you not see it?” “I can’t see "
                 "anything. Maybe your eyes are just too good, Sandor.” Sandor "
                 "frowned, dubious. Fair, I couldn’t really talk when I had the "
                 "Eye of Distant Sight.")
        capped = A._cap_fiction_quote(scene, cap=160)
        self.assertLessEqual(len(capped), 160)
        self.assertTrue(scene.startswith(capped))
        self.assertTrue(capped.endswith((".", "?", "!")))
        self.assertEqual(A._cap_fiction_quote("short enough"), "short enough")

    def test_one_quote_per_passage_and_the_longer_cut_wins(self):
        """Two rounds quote one passage; it is cited once, at its longest."""
        citations = [{
            "chunk_id": "f-1", "chapter": "1",
            "quote": "He was covered in wounds, his armor was half in ruins.",
        }]
        shorter = {"chunk_id": "f-1", "chapter": "1", "quote": "He was covered in wounds."}
        longer = {"chunk_id": "f-1", "chapter": "1",
                  "quote": "He was covered in wounds, his armor was half in ruins. Blood trickled down."}
        far = {"chunk_id": "f-2", "chapter": "2", "quote": "Eris said they ride at dawn."}
        self.assertFalse(A._add_fiction_quote(citations, shorter))
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["quote"], "He was covered in wounds, his armor was half in ruins.")
        self.assertTrue(A._add_fiction_quote(citations, longer))
        self.assertEqual(len(citations), 1)
        self.assertIn("Blood trickled down", citations[0]["quote"])
        self.assertTrue(A._add_fiction_quote(citations, far))
        self.assertEqual(len(citations), 2)

    def test_a_repeated_answer_stops_the_rounds(self):
        search, _ = self.search_recorder(FICTION_CHUNKS)
        generate, calls = scripted([
            '[Ch. 1] "“You are late,” Sandor said, and set the cup down."\n'
            "Sandor is waiting on Rudeus.",
        ])
        body = A.respond(
            fiction_index(), "What happened when Rudeus came back?",
            generate_fn=generate, search_fn=search, model="m",
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(body["citations"]), 1)
        self.assertFalse(body["refused"])

    def test_rounds_are_bounded_and_end_in_a_refusal(self):
        search, _ = self.search_recorder(FICTION_CHUNKS)
        generate, calls = scripted(["Nobody in this book does anything."])
        body = A.respond(
            fiction_index(), "What happened when Rudeus came back?",
            generate_fn=generate, search_fn=search, model="m",
        )
        self.assertTrue(body["refused"])
        self.assertEqual(len(calls), bookkind.FICTION_SAMPLE_ROUNDS)

    def test_technical_book_keeps_five_passages_and_the_strict_prompt(self):
        search, calls = self.search_recorder(TECH_CHUNKS)
        seen = {}

        def generate(system, user, model):
            seen["system"] = system
            return f'[Ch. 1] "{TECH_CHUNKS[0]["text"]}"'

        A.respond(
            tech_index(), "What is change data capture?",
            generate_fn=generate, search_fn=search, model="m",
        )
        self.assertEqual(calls["k"], A.PASSAGE_LIMIT)
        self.assertEqual(seen["system"], SYSTEM)

    def test_fiction_answer_with_no_citable_passage_is_a_refusal(self):
        """The loose sampler does not buy an uncited answer."""
        search, _ = self.search_recorder(FICTION_CHUNKS)

        def generate(system, user, model):
            return "Rudeus is a hero who always wins and never doubts himself."

        body = A.respond(
            fiction_index(), "What happened when Rudeus came back?",
            generate_fn=generate, search_fn=search, model="m",
        )
        self.assertTrue(body["refused"])
        self.assertEqual(body["answer"], "Not in this book.")


if __name__ == "__main__":
    unittest.main()
