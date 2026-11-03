"""Who is X: a profile built from the book, not written by the model.

A name is not a concept, so dense retrieval drops a "who is X" question into one
scene and the model answers from that scene. The engine instead gathers the
book's own sentences that name the person, one per chapter, and adds the titles
those sentences use. Nothing is generated, so nothing can be invented.
"""

import unittest
from unittest import mock

import answer as A
import bookkind
import entity
from prompt import SPELL_SYSTEM


def chunk(chunk_id, chapter, text, heading=""):
    return {
        "chunk_id": chunk_id,
        "chapter": chapter,
        "heading": heading,
        "text": text,
        "source": f"section-{chapter}",
        "score": 0.9,
    }


ATO = [
    chunk("a-1", "1",
          "“Move,” she said, and the guard moved before he had finished the "
          "challenge, because Immortal Demon King Atofe did not wait at gates. "
          "“She is here,” he whispered to nobody, “she is actually here.”"),
    chunk("a-2", "2",
          "“The box came from Atofe,” Rudeus said, and set it down between them so "
          "the seal caught the light. “Do we open it?” Eris asked, and he said "
          "nothing at all."),
    chunk("a-3", "3",
          "“Kneel,” Immortal Demon King Atofe said, and the whole hall went quiet "
          "at once. Nobody argued with her twice, and the guards found somewhere "
          "else to look."),
    chunk("a-4", "4",
          "“Atofe's guard cleared the road,” Rudeus said, “and left us with an "
          "empty road and a very bad feeling.” “Then we ride,” Eris said, "
          "“before they come back.”"),
]
# Front matter: an index-like page that names her but is not the story.
MATTER = chunk("a-matter", "section-0014",
               "Atofe: see Immortal Demon King Atofe. Atofe's guard, 12. Atofe's box, 44.")

TECH = [
    chunk("t-1", "1",
          "Change data capture streams row-level changes from a database so "
          "downstream systems stay in sync with the source of truth."),
    chunk("t-2", "2",
          "Batch processing runs on a schedule and handles large volumes of "
          "records at once, trading latency for throughput."),
]


def index_of(chunks, extra=None):
    index = {
        "book_id": "a-novel",
        "title": "A Novel",
        "author": "Someone",
        "chunks": [dict(item) for item in chunks],
        "figures": [],
    }
    index.update(extra or {})
    return index


class SubjectTest(unittest.TestCase):
    def test_who_is_form(self):
        self.assertEqual(entity.subject("who is atofe"), "atofe")
        self.assertEqual(entity.subject("Who is Sandor?"), "Sandor")
        self.assertEqual(entity.subject("who's eris"), "eris")

    def test_tell_me_about_form(self):
        self.assertEqual(entity.subject("tell me about ruijerd"), "ruijerd")
        self.assertEqual(entity.subject("Describe Eris."), "Eris")
        self.assertEqual(entity.subject("what do you know about Atofe?"), "Atofe")

    def test_scope_phrase_and_article_are_stripped(self):
        self.assertEqual(entity.subject("who is Atofe in this book"), "Atofe")
        self.assertEqual(entity.subject("who is the Atofe"), "Atofe")

    def test_not_a_name(self):
        for question in (
            "who is the main character", "who is he", "who is the author",
            "what is a watermark", "how does the third eye work",
            "who is this person in the story",
        ):
            with self.subTest(question=question):
                self.assertIsNone(entity.subject(question))

    def test_a_long_phrase_is_not_a_name(self):
        self.assertIsNone(
            entity.subject("who is the man with the sword in the first chapter")
        )


class ProfileSentencesTest(unittest.TestCase):
    def test_one_sentence_per_chapter_in_reading_order(self):
        picks = entity.profile_sentences(index_of(ATO), "Atofe")
        self.assertEqual([item["chapter"] for item in picks], ["1", "2", "3", "4"])
        for item in picks:
            self.assertIn("atofe", item["quote"].lower())

    def test_front_matter_is_not_a_profile(self):
        picks = entity.profile_sentences(index_of(ATO + [MATTER]), "Atofe")
        self.assertNotIn("section-0014", [item["chapter"] for item in picks])

    def test_quotes_are_whole_sentences(self):
        for item in entity.profile_sentences(index_of(ATO), "Atofe"):
            with self.subTest(quote=item["quote"]):
                self.assertTrue(item["quote"].endswith((".", "!", "?")))
                self.assertNotIn("\n", item["quote"])

    def test_an_unknown_name_has_no_profile(self):
        self.assertEqual(entity.profile_sentences(index_of(ATO), "Zzznotinbook"), [])

    def test_a_single_chapter_is_not_a_profile(self):
        one = ATO[:1] + [chunk("b-1", "1", "Atofe waited by the gate all morning "
                                        "while the guard said nothing at all to her.")]
        self.assertEqual(len(entity.profile_sentences(index_of(one), "Atofe")), 1)


class TitlesTest(unittest.TestCase):
    def test_the_books_own_title_is_copied(self):
        picks = entity.profile_sentences(index_of(ATO), "Atofe")
        titles = entity.titles(picks, "Atofe")
        self.assertIn("Immortal Demon King Atofe", titles)
        for title in titles:
            self.assertTrue(any(title in item["quote"] for item in picks))

    def test_a_lowercase_question_still_finds_the_capitalised_title(self):
        picks = entity.profile_sentences(index_of(ATO), "atofe")
        self.assertIn("Immortal Demon King Atofe", entity.titles(picks, "atofe"))

    def test_an_honorific_alone_is_not_a_title(self):
        picks = [{"quote": "Master Rudeus will return to us.", "chapter": "1"}]
        self.assertEqual(entity.titles(picks, "Rudeus"), [])


class AnswerTest(unittest.TestCase):
    def test_the_fixture_is_a_fiction_book(self):
        self.assertEqual(bookkind.kind(index_of(ATO)), bookkind.FICTION)

    def test_a_profile_is_built_without_calling_the_model(self):
        calls = []

        def generate(system, user, model):
            calls.append(system)
            return "should not be called"

        body = A.respond(
            index_of(ATO), "who is atofe", generate_fn=generate,
            search_fn=lambda idx, q, k=5: [dict(c) for c in ATO], model="m",
        )
        self.assertEqual(calls, [])
        self.assertFalse(body["refused"])
        self.assertEqual(len(body["citations"]), 4)
        self.assertIn("Known as: Immortal Demon King Atofe", body["answer"])
        self.assertEqual(
            set(body), {"answer", "citations", "figures", "refused", "followups"}
        )

    def test_ask_mode_builds_the_same_profile(self):
        body = A.ask(
            index_of(ATO), "who is atofe",
            generate_fn=lambda s, u, m: "unused",
            search_fn=lambda idx, q, k=5: [dict(c) for c in ATO], model="m",
        )
        self.assertFalse(body["refused"])
        self.assertEqual(len(body["citations"]), 4)

    def test_the_app_pin_does_not_block_a_profile(self):
        """The reader UI sends the on-screen chunk with every question."""
        body = A.respond(
            index_of(ATO), "who is atofe",
            generate_fn=lambda s, u, m: "unused",
            search_fn=lambda idx, q, k=5: [dict(c) for c in ATO], model="m",
            pin_chunk="a-2",
        )
        self.assertEqual(len(body["citations"]), 4)
        self.assertIn("Known as:", body["answer"])

    def test_a_new_person_in_a_thread_still_profiles(self):
        calls = []

        def generate(system, user, model):
            calls.append(system)
            return "unused"

        body = A.respond(
            index_of(ATO), "who is eris", generate_fn=generate,
            search_fn=lambda idx, q, k=5: [dict(c) for c in ATO], model="m",
            pin_chunk="a-2",
            history=[{"question": "who is atofe", "answer": "A demon king."}],
        )
        self.assertEqual(calls, [])
        # The fixture names Eris in two chapters, so a profile of her is two
        # moments; what matters is that the thread did not block it.
        self.assertEqual(len(body["citations"]), 2)

    def test_the_same_person_asked_again_is_a_follow_up(self):
        calls = []

        def generate(system, user, model):
            calls.append(system)
            return "Not in this book."

        A.respond(
            index_of(ATO), "who is atofe", generate_fn=generate,
            search_fn=lambda idx, q, k=5: [dict(c) for c in ATO], model="m",
            history=[{"question": "who is atofe", "answer": "A demon king."}],
        )
        self.assertTrue(calls)

    def test_a_technical_book_never_takes_the_profile_path(self):
        calls = []

        def generate(system, user, model):
            calls.append(system)
            return "Not in this book."

        A.respond(
            index_of(TECH), "who is atofe", generate_fn=generate,
            search_fn=lambda idx, q, k=5: [dict(c) for c in TECH], model="m",
        )
        self.assertTrue(calls)

    def test_a_name_the_book_does_not_know_answers_normally(self):
        calls = []

        def generate(system, user, model):
            calls.append(system)
            return "Not in this book."

        body = A.respond(
            index_of(ATO), "who is zzznotinbook", generate_fn=generate,
            search_fn=lambda idx, q, k=5: [dict(c) for c in ATO], model="m",
        )
        self.assertTrue(calls)
        self.assertTrue(body["refused"])

    def test_the_trace_names_the_profile(self):
        import observe

        with observe.trace(source="probe", mode="answer") as trace:
            A.respond(
                index_of(ATO), "who is atofe",
                generate_fn=lambda s, u, m: "unused",
                search_fn=lambda idx, q, k=5: [dict(c) for c in ATO], model="m",
            )
        self.assertEqual(trace.shortcut, "entity_profile")
        self.assertIn("entity_profile", trace.retrieval_stages)


if __name__ == "__main__":
    unittest.main()


class PinWindowTest(unittest.TestCase):
    """A pinned follow-up keeps the window it asked for.

    Measured 2026-11-02: `_pin_chunk` capped at the module constant, so a
    fiction request for eight passages returned five whenever a pin was
    present, and the reader UI sends the on-screen chunk with every follow-up.
    """

    def test_a_pinned_followup_keeps_the_requested_window(self):
        long_fixture = ATO + [
            chunk("a-5", "5", "“Wait,” someone said, and the hall settled again. "
                              "Atofe said nothing at all, and the guard waited."),
            chunk("a-6", "6", "“We go now,” Rudeus said, and the party moved. "
                              "Atofe watched them from the wall and did not follow."),
        ]
        index = index_of(long_fixture)
        # The fixture has no vectors, so the lexical leg is closed for the test;
        # what is under test is the window size a pin leaves behind.
        with mock.patch.object(A, "lexical_terms", return_value=[]):
            ctx = A.retrieval_context(
                index,
                "what did atofe do next",
                search_fn=lambda idx, q, k=5: [dict(c) for c in long_fixture][:k],
                generate_fn=lambda system, user, model: "",
                pin_chunk="a-1",
                history=[{"question": "who is atofe", "answer": "A demon king."}],
                passage_limit=bookkind.FICTION_PASSAGE_LIMIT,
            )
        self.assertEqual(len(ctx["passages"]), len(long_fixture))
        self.assertEqual(ctx["passages"][0]["chunk_id"], "a-1")
