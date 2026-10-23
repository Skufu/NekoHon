"""Agentic tool-loop checks. Fake generator, fake embedder. No Ollama.

The loop mechanics are under test, not retrieval quality: the fake embedder
returns one vector for every text, so the semantic tool's order is index order.
"""

import math
import unittest

from agentic import (
    TOOL_NAMES,
    KeywordTool,
    RegexTool,
    agentic_search,
    build_tools,
    fallback_decision,
    keyword_scores,
    parse_decision,
    pick_next_tool,
)
from fusion import lexical_scores
from keywords import postings
from retrieve import embed_index

DIMS = 3


def fake_embed(texts, model):
    """One fixed vector per text: every chunk scores the same."""
    return [[1.0, 0.0, 0.0] for _ in texts]


def make_index():
    texts = [
        "Codd introduced the relational model.",  # c01
        "Alpha appears here once.",  # c02
        "Alpha and beta together.",  # c03
        "Nothing relevant in this passage.",  # c04
        "Alpha again, with beta and gamma.",  # c05
    ]
    index = {
        "chunks": [
            {
                "chunk_id": f"c{i:02d}",
                "chapter": "1",
                "heading": "",
                "text": text,
                "source": "",
            }
            for i, text in enumerate(texts, start=1)
        ],
        "figures": [],
    }
    embed_index(index, embed_fn=fake_embed, dims=DIMS)
    return index


def gen_from(replies):
    """A fake generate_fn with scripted replies and recorded user prompts."""
    calls = {"users": []}

    def gen(system, user, model):
        calls["users"].append(user)
        return replies.pop(0) if replies else "stop"

    return gen, calls


class ToolTests(unittest.TestCase):
    def test_keyword_tool_is_idf_weighted_and_gated(self):
        index = make_index()
        tool = KeywordTool(k=2)
        state = {}
        hits = tool.search("alpha beta codd", index, state)
        self.assertIn("word_map", state)  # memoized for the next attempt
        self.assertEqual([hit["chunk_id"] for hit in hits], ["c01", "c03"])
        self.assertAlmostEqual(hits[0]["score"], math.log(4.5 / 1.5))
        self.assertAlmostEqual(hits[1]["score"], math.log(3.5 / 2.5))
        # "alpha" lives in 3 of 5 chunks: dropped by the half-corpus gate,
        # so c02 (alpha alone) never scores.
        self.assertNotIn("c02", [hit["chunk_id"] for hit in hits])

    def test_keyword_scores_pin_to_fusion_lexical_scores(self):
        index = make_index()
        chunks = index["chunks"]
        word_map = postings(index)
        ranks = {chunk["chunk_id"]: 1 for chunk in chunks}
        mine = keyword_scores("alpha beta codd", word_map, chunks)
        # Every chunk pinned at rank 1 with band >= 1 opens fusion's dense-band
        # veto, leaving its idf math bare -- the same math this tool restates.
        fused = lexical_scores("alpha beta codd", word_map, chunks, ranks, band=1)
        self.assertEqual(mine, fused)
        self.assertEqual(set(mine), {0, 2, 4})

    def test_regex_tool_ranks_by_match_count(self):
        texts = [
            "Streaming ingestion moves data to an endpoint.",  # 3 matches
            "An endpoint receives data.",  # 1 match
            "Nothing here.",  # 0 matches
        ]
        index = {
            "chunks": [
                {"chunk_id": f"r{i}", "chapter": "1", "heading": "", "text": text}
                for i, text in enumerate(texts)
            ]
        }
        hits = RegexTool(k=5).search(
            "what is an endpoint in streaming ingestion", index, {}
        )
        self.assertEqual([hit["chunk_id"] for hit in hits], ["r0", "r1"])
        self.assertEqual([hit["score"] for hit in hits], [3.0, 1.0])

    def test_regex_tool_survives_metacharacters(self):
        index = make_index()
        tool = RegexTool(k=5)
        # Parentheses and a bare metacharacter: words() keeps only word
        # tokens, and re.escape guards whatever reaches the pattern.
        hits = tool.search("what is (alpha) beta?", index, {})
        self.assertEqual([hit["chunk_id"] for hit in hits], ["c03", "c05", "c02"])
        self.assertEqual(tool.search("(", index, {}), [])

    def test_registry_matches_the_choice_names(self):
        self.assertEqual(tuple(build_tools()), TOOL_NAMES)


class ParseTests(unittest.TestCase):
    def test_parse_decision_shapes(self):
        decision = parse_decision("semantic\nsome alpha query")
        self.assertEqual((decision["kind"], decision["tool"], decision["query"]),
                         ("tool", "semantic", "some alpha query"))
        decision = parse_decision("semantic: alpha beta")
        self.assertEqual((decision["tool"], decision["query"]), ("semantic", "alpha beta"))
        decision = parse_decision("keyword CRUD")
        self.assertEqual((decision["tool"], decision["query"]), ("keyword", "CRUD"))
        self.assertEqual(parse_decision("semantic or stop")["kind"], "unparsed")
        decision = parse_decision("**keyword**\nQuery: watermarks")
        self.assertEqual((decision["tool"], decision["query"]), ("keyword", "watermarks"))
        self.assertEqual(parse_decision("stop")["kind"], "stop")
        self.assertEqual(parse_decision("stop.")["kind"], "stop")
        self.assertEqual(parse_decision("I would stop here.")["kind"], "stop")
        self.assertEqual(parse_decision("banana")["kind"], "unparsed")
        self.assertEqual(parse_decision("use semantic and regex")["kind"], "unparsed")
        self.assertEqual(parse_decision("semantic\nstop")["tool"], "semantic")
        self.assertEqual(parse_decision("")["kind"], "unparsed")
        # A tool named without a query still runs, on the original question.
        self.assertIsNone(parse_decision("regex")["query"])

    def test_fallback_policy_is_deterministic(self):
        cases = [
            ([], "semantic"),  # nothing tried: the head of the spectrum
            (["semantic"], "regex"),  # farthest from the dense end
            (["keyword"], "semantic"),  # tie: earlier in the spectrum wins
            (["regex"], "semantic"),
        ]
        for tried, expected in cases:
            attempts = [{"tool": name} for name in tried]
            choice = fallback_decision("original question", attempts)
            self.assertEqual(choice["tool"], expected)
            self.assertEqual(choice["query"], "original question")
            self.assertEqual(choice["chosen_by"], "fallback")
        choice = fallback_decision("q", [{"tool": name} for name in TOOL_NAMES])
        self.assertIsNone(choice["tool"])


class LoopTests(unittest.TestCase):
    def test_model_choices_drive_the_tool_order(self):
        index = make_index()
        gen, calls = gen_from([
            "semantic\nalpha beta codd",
            "keyword\nalpha beta codd",
            "regex\nalpha beta codd",
        ])
        result = agentic_search(
            index, "alpha (beta) codd", generate_fn=gen,
            tools=build_tools(fake_embed, k=2), max_steps=3,
        )
        self.assertEqual([item["tool"] for item in result["attempts"]],
                         ["semantic", "keyword", "regex"])
        self.assertEqual([item["chosen_by"] for item in result["attempts"]],
                         ["model", "model", "model"])
        self.assertEqual([item["query"] for item in result["attempts"]],
                         ["alpha beta codd"] * 3)
        self.assertEqual([item["new"] for item in result["attempts"]],
                         [["c01", "c02"], ["c03"], ["c05"]])
        self.assertEqual([hit["chunk_id"] for hit in result["passages"]],
                         ["c01", "c02", "c03", "c05"])
        self.assertEqual(result["stopped"], "max_steps")
        self.assertTrue(any("Question: alpha (beta) codd" in user for user in calls["users"]))
        # The merge output is a drop-in for retrieve.search's hit shape.
        for hit in result["passages"]:
            self.assertEqual(set(hit),
                             {"score", "chunk_id", "chapter", "heading", "text", "source"})

    def test_stop_works(self):
        index = make_index()
        gen, calls = gen_from(["stop"])
        result = agentic_search(index, "alpha", generate_fn=gen,
                                tools=build_tools(fake_embed, k=2))
        self.assertEqual(result["attempts"], [])
        self.assertEqual(result["passages"], [])
        self.assertEqual(result["stopped"], "model")
        self.assertEqual(len(calls["users"]), 1)
        gen, _ = gen_from(["semantic\nalpha", "I would stop here."])
        result = agentic_search(index, "alpha", generate_fn=gen,
                                tools=build_tools(fake_embed, k=2))
        self.assertEqual([item["tool"] for item in result["attempts"]], ["semantic"])
        self.assertEqual(result["stopped"], "model")

    def test_unknown_tool_name_falls_back_deterministically(self):
        index = make_index()
        gen, _ = gen_from(["banana", "banana", "banana"])
        result = agentic_search(index, "alpha beta codd", generate_fn=gen,
                                tools=build_tools(fake_embed, k=2), max_steps=3)
        self.assertEqual([item["tool"] for item in result["attempts"]],
                         ["semantic", "regex", "keyword"])
        self.assertEqual([item["chosen_by"] for item in result["attempts"]],
                         ["fallback"] * 3)
        self.assertEqual([item["query"] for item in result["attempts"]],
                         ["alpha beta codd"] * 3)
        self.assertEqual(result["stopped"], "nothing_new")
        self.assertEqual([hit["chunk_id"] for hit in result["passages"]],
                         ["c01", "c02", "c03", "c05"])

    def test_max_steps_caps_the_loop(self):
        index = make_index()
        gen, calls = gen_from(["semantic\nalpha beta codd", "stop"])
        result = agentic_search(index, "alpha", generate_fn=gen,
                                tools=build_tools(fake_embed, k=2), max_steps=1)
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(result["stopped"], "max_steps")
        # The model wanted another step; the budget ended the loop first.
        self.assertEqual(len(calls["users"]), 1)

    def test_nothing_new_stops_and_duplicates_are_deduped(self):
        index = make_index()
        gen, _ = gen_from(["semantic\nalpha", "semantic\nbeta"])
        result = agentic_search(index, "alpha", generate_fn=gen,
                                tools=build_tools(fake_embed, k=2))
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(result["attempts"][1]["new"], [])
        self.assertEqual(result["stopped"], "nothing_new")
        total_hits = sum(len(item["hits"]) for item in result["attempts"])
        self.assertEqual(total_hits, 4)
        self.assertEqual([hit["chunk_id"] for hit in result["passages"]],
                         ["c01", "c02"])

    def test_decision_prompt_shows_tool_query_ids_and_snippets(self):
        # One logged attempt replayed back into the decision prompt.
        attempt = {
            "step": 1,
            "tool": "semantic",
            "query": "alpha (beta) codd",
            "chosen_by": "model",
            "reply": "semantic\nalpha (beta) codd",
            "hits": [{"chunk_id": "c01", "text": "Codd\nCodd introduced the relational model."}],
            "new": ["c01"],
        }
        gen, calls = gen_from(["stop"])
        pick_next_tool("alpha (beta) codd", [attempt], gen, "fake-model")
        user = calls["users"][0]
        self.assertIn("Question: alpha (beta) codd", user)
        self.assertIn("Tools: semantic, keyword, regex", user)
        self.assertIn('1. tool=semantic query="alpha (beta) codd"', user)
        self.assertIn("chunk ids: c01", user)
        self.assertIn('snippet c01: "Codd Codd introduced the relational model."', user)


if __name__ == "__main__":
    unittest.main()
