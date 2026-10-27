"""A definitional answer must not be offered the example it just quoted.

The bug this guards: "what is an api" quoted "For example, well-designed
abstractions, APIs, ..." from a chunk that also opens with a different
"For example" (operator errors causing outages). The pill generator saw the
chunk-level marker and offered "What example do the authors give?", and the
click scored both example sentences equal (37), then the earlier one won the
tie-break and replaced the API quote with the outage quote.

Two rules are pinned here:

1. `compute_dynamic_followups` does not offer the example pill when the quote
   the reader is looking at already contains an example marker.
2. `_advance_followup_quote` continues forward: for an example question, a
   sentence before the cited quote is a different example and is skipped.

The scenario table below doubles as the rating: every question is scored on
the pills it generated and the quote a click would show.
"""

import unittest

from answer import _advance_followup_quote, _quote_in_passage
from intent import compute_dynamic_followups

EXAMPLE_PILL = "What example do the authors give?"

API_QUOTE = (
    "For example, well-designed abstractions, APIs, and admin interfaces make it "
    "easy to do \u201cthe right thing\u201d and discourage \u201cthe wrong thing.\u201d"
)
OUTAGE_QUOTE_START = (
    "For example, one study of large internet services found that configuration "
    "errors by operators were the leading cause of outages"
)
RELIABILITY_INTRO = "How do we make our systems reliable, in spite of unreliable humans?"

HUMAN_ERRORS_TEXT = (
    "Human Errors\n"
    "Humans design and build software systems, and the operators who keep the systems "
    "running are also human. Even when they have the best intentions, humans are known "
    "to be unreliable. For example, one study of large internet services found that "
    "configuration errors by operators were the leading cause of outages, whereas "
    "hardware faults (servers or network) played a role in only 10\u201325% of outages [13\n"
    " ].\n\n"
    "How do we make our systems reliable, in spite of unreliable humans? The best "
    "systems combine several approaches:\n\n"
    "Design systems in a way that minimizes opportunities for error. For example, "
    "well-designed abstractions, APIs, and admin interfaces make it easy to do "
    "\u201cthe right thing\u201d and discourage \u201cthe wrong thing.\u201d However, if the "
    "interfaces are too restrictive people will work around them, negating their "
    "benefit, so this is a tricky balance to get right.\n\n"
    "Decouple the places where people make the most mistakes from the places where "
    "they can cause failures.\n"
    " In particular, provide fully featured non-production sandbox\n"
    " environments where people can explore and experiment safely, using real data, "
    "without affecting real users."
)

BACKPRESSURE_DEFINITION = (
    "Backpressure is a mechanism that slows producers when consumers cannot keep up."
)
BACKPRESSURE_EXAMPLE = (
    "For example, a bounded queue rejects writes once its buffer is full."
)
BACKPRESSURE_TEXT = f"Backpressure\n{BACKPRESSURE_DEFINITION} {BACKPRESSURE_EXAMPLE}"

RECOVERY_NEIGHBOR_TEXT = (
    "Human Errors\n"
    "In particular, provide fully featured non-production sandbox\r\n environments "
    "where people can explore and experiment safely, using real data, without "
    "affecting real users.\n\n"
    "Test thoroughly at all levels, from unit tests to whole-system integration tests "
    "and manual tests [3\r\n ]. Automated testing is widely used, well understood, "
    "and especially valuable for covering corner cases that rarely arise in normal "
    "operation.\n\n"
    "Allow quick and easy recovery from human errors, to minimize the impact in the "
    "case of a failure. For example, make it fast to roll back configuration changes, "
    "roll out new code gradually (so that any unexpected bugs affect only a small "
    "subset of users), and provide tools to recompute data (in case it turns out that "
    "the old computation was incorrect)."
)

SERIALIZATION_QUOTE = (
    "Data serialization formats such as JSON, XML, and Protobuf encode structured "
    "data for transport."
)
SERIALIZATION_TEXT = (
    f"Data Serialization\n{SERIALIZATION_QUOTE} "
    "Protobuf uses a schema to keep messages compact."
)


def human_errors_chunk():
    return {
        "chunk_id": "text00006-016",
        "chapter": "1",
        "heading": "Human Errors",
        "text": HUMAN_ERRORS_TEXT,
    }


def backpressure_chunk():
    return {
        "chunk_id": "c-backpressure",
        "chapter": "4",
        "heading": "Backpressure",
        "text": BACKPRESSURE_TEXT,
    }


def serialization_chunk():
    return {
        "chunk_id": "c-serialization",
        "chapter": "2",
        "heading": "Data Serialization",
        "text": SERIALIZATION_TEXT,
    }


def pills_for(question, chunk, prior_quote):
    answer_text = f'[Ch. {chunk["chapter"]}] "{prior_quote}"'
    return compute_dynamic_followups(
        chunk,
        neighbors=[],
        question=question,
        answer_text=answer_text,
        mode="ask",
    )


def advance_for(chunk, prior_quote, neighbors=None):
    return _advance_followup_quote(
        chunk,
        neighbors=neighbors or [],
        prior_quote=prior_quote,
        followup_question=EXAMPLE_PILL,
    )


# One scenario per shape the generator has to tell apart. "quote_contains" is
# required when the pill is offered; "quote_forbids" is the quote that must
# never replace the one on screen.
RATING_SCENARIOS = (
    {
        "name": "what is an api: the answer is the example",
        "question": "what is an api",
        "chunk": human_errors_chunk(),
        "prior_quote": API_QUOTE,
        "expect_example_pill": False,
        "quote_contains": None,
        "quote_forbids": OUTAGE_QUOTE_START,
    },
    {
        "name": "what is an api: the intro sits between two examples",
        "question": "what is an api",
        "chunk": human_errors_chunk(),
        "prior_quote": RELIABILITY_INTRO,
        "expect_example_pill": True,
        "quote_contains": "well-designed abstractions",
        "quote_forbids": OUTAGE_QUOTE_START,
    },
    {
        "name": "what is backpressure: a definition, then an example",
        "question": "what is backpressure",
        "chunk": backpressure_chunk(),
        "prior_quote": BACKPRESSURE_DEFINITION,
        "expect_example_pill": True,
        "quote_contains": "bounded queue",
        "quote_forbids": None,
    },
    {
        "name": "what is serialization: the answer uses such as",
        "question": "what is serialization",
        "chunk": serialization_chunk(),
        "prior_quote": SERIALIZATION_QUOTE,
        "expect_example_pill": False,
        "quote_contains": None,
        "quote_forbids": None,
    },
)


def rate_scenario(scenario):
    """Run one scenario and return its rating plus the artifacts it produced."""
    chunk = scenario["chunk"]
    pills = pills_for(scenario["question"], chunk, scenario["prior_quote"])
    quote = advance_for(chunk, scenario["prior_quote"])

    checks = []
    has_pill = EXAMPLE_PILL in pills
    checks.append((
        "example pill offered" if scenario["expect_example_pill"] else "example pill suppressed",
        has_pill == scenario["expect_example_pill"],
        f"pills={pills}",
    ))
    shape_ok = (
        len(pills) == len(set(pills))
        and all(len(p) <= 45 for p in pills)
        and all(p.lower() != scenario["question"].strip().lower() for p in pills)
    )
    checks.append(("pill shape and no repeats", shape_ok, f"pills={pills}"))

    contains = scenario.get("quote_contains")
    if contains:
        checks.append((
            f"quote contains {contains!r}",
            bool(quote and contains in quote),
            f"quote={quote!r}",
        ))
    forbids = scenario.get("quote_forbids")
    if forbids:
        checks.append((
            "quote does not jump back to the earlier example",
            not (quote and forbids in quote),
            f"quote={quote!r}",
        ))
    checks.append((
        "quote is verbatim from the chunk",
        quote is None or _quote_in_passage(quote, chunk["text"]),
        f"quote={quote!r}",
    ))
    return {
        "name": scenario["name"],
        "pills": pills,
        "quote": quote,
        "checks": checks,
        "passed": sum(1 for _, ok, _ in checks if ok),
        "total": len(checks),
    }


class FollowupPillRegressionTests(unittest.TestCase):
    def test_api_answer_does_not_offer_the_example_it_just_quoted(self):
        pills = pills_for("what is an api", human_errors_chunk(), API_QUOTE)
        self.assertNotIn(EXAMPLE_PILL, pills)

    def test_example_click_does_not_replace_the_api_quote_with_the_outage_quote(self):
        quote = advance_for(human_errors_chunk(), API_QUOTE)
        self.assertIsNone(quote)

    def test_example_click_moves_forward_when_an_example_follows(self):
        quote = advance_for(human_errors_chunk(), RELIABILITY_INTRO)
        self.assertIsNotNone(quote)
        self.assertIn("well-designed abstractions", quote)
        self.assertNotIn("configuration errors", quote)

    def test_example_pill_survives_when_the_answer_is_a_definition(self):
        pills = pills_for("what is backpressure", backpressure_chunk(), BACKPRESSURE_DEFINITION)
        self.assertIn(EXAMPLE_PILL, pills)

    def test_no_history_example_question_still_advances(self):
        chunk = human_errors_chunk()
        quote = _advance_followup_quote(
            chunk, neighbors=[], prior_quote="", followup_question=EXAMPLE_PILL
        )
        self.assertIsNotNone(quote)
        self.assertIn("configuration errors", quote)

    def test_example_click_can_continue_into_a_forward_neighbor(self):
        neighbor = {
            "chunk_id": "text00006-017",
            "chapter": "1",
            "heading": "Human Errors",
            "text": RECOVERY_NEIGHBOR_TEXT,
        }
        quote = advance_for(human_errors_chunk(), API_QUOTE, neighbors=[neighbor])
        self.assertIsNotNone(quote)
        self.assertIn("roll back configuration changes", quote)
        self.assertNotIn("configuration errors", quote)


class FollowupRatingTests(unittest.TestCase):
    def test_every_scenario_gets_full_marks(self):
        for scenario in RATING_SCENARIOS:
            with self.subTest(scenario=scenario["name"]):
                result = rate_scenario(scenario)
                failures = [
                    f"{name}: {detail}"
                    for name, ok, detail in result["checks"]
                    if not ok
                ]
                self.assertEqual(
                    failures,
                    [],
                    f"{result['passed']}/{result['total']} checks passed",
                )

    def test_the_rating_helper_can_fail(self):
        """The score is not vacuous: a wrong expectation loses points."""
        wrong = dict(RATING_SCENARIOS[0])
        wrong["name"] = "deliberately wrong expectation"
        wrong["expect_example_pill"] = True
        wrong["quote_forbids"] = None
        result = rate_scenario(wrong)
        self.assertLess(result["passed"], result["total"])


if __name__ == "__main__":
    unittest.main()
