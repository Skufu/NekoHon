"""Agentic retrieval prototype: three tools, the model picks the next step.

Not imported by server.py. A measured multi-hop win is the bar for wiring
this loop into a route. Follow-up chat is a different change and does not
go through this file. Evidence: `artifacts/reports/agentic-design.md`,
`artifacts/probes/probe-agentic.py`, `tests/test_agentic.py`.

The loop:

    while not done:
        decision = pick_next_tool(question, attempts, generate_fn, model)
        hits = tools[decision["tool"]].search(decision["query"], index, state)
        attempts.append(attempt)          # tool, query, hits, new chunk ids
        merge fresh hits into the passages (first-seen order)

Stops when the model says stop, when a tool returns nothing new, or at
`max_steps` (3 is a documented budget, not a tuned number: one first channel
plus two complements).

The three tools share one interface: `.name` and
`.search(query, index, state) -> list of retrieve.search-shaped hits`
(chunk_id, chapter, heading, text, source, score). `state` is per-search
scratch; the keyword tool memoizes the postings map there, so the two or
three attempts of one search build it at most once.

- semantic: `retrieve.search`, the dense cosine channel, unchanged.
- keyword: idf-weighted overlap over `keywords.postings` -- the same math as
  `fusion.lexical_scores`, restated without the dense-band veto (the band
  needs a full dense rank map this tool does not take as input; the tests
  pin the two formulas against each other on one fixture).
- regex: the query's tokens as one escaped case-insensitive pattern, ranked
  by match count. Stopwords are dropped: every passage holds "the", so their
  matches are noise, not signal -- the same reason the lexical channel
  refuses words living in more than half the corpus.

`pick_next_tool` is the "magic": it shows the local model the tools and every
attempt (tool, query, hit chunk ids, one-line snippets) and asks for the next
tool and query, or stop. The reply is parsed strictly: the first line must be
a tool name or stop (the query rides on line 2); failing that, the whole reply
must name exactly one tool or say stop and nothing else. Anything else -- an
unknown name, several names, "stop" next to a tool -- is a parse failure and
takes the deterministic fallback: the untried tool farthest from the one that
just ran on the fixed spectrum semantic -> keyword -> regex, with the original
question as the query. No attempts yet takes the head of the spectrum; no
untried tool left stops the loop.

Scores are tool-local (cosine, idf sums, match counts) and are NOT comparable
across tools; the merge keeps the first-seen hit exactly as the first tool
returned it.

Stdlib only. `generate_fn` and the tools' embedder are injected, so tests
never call Ollama.
"""

import math
import re

from answer import ollama_generate
from keywords import postings
from preprocess import STOPWORDS, words
from prompt import ANSWER_MODEL
from retrieve import DEFAULT_EMBEDDER, TOP_K, search

TOOL_K = TOP_K  # One tool call brings one existing retrieval width (top 10).
MAX_STEPS = 3  # Documented budget: the first channel plus two complements.
SNIPPET_CHARS = 100  # One line of a hit, for the decision prompt.
SNIPPETS_PER_ATTEMPT = 3  # Prompt size, not a tuned number.
REPLY_CHARS = 160  # The raw model reply kept in the attempt log, flattened.


def _as_hit(chunk, score):
    """A retrieve.search-shaped hit. See the module docstring on scores."""
    return {
        "score": score,
        "chunk_id": chunk["chunk_id"],
        "chapter": chunk["chapter"],
        "heading": chunk.get("heading", ""),
        "text": chunk.get("text", ""),
        "source": chunk.get("source", ""),
    }


class Tool:
    """One retrieval channel.

    `search(query, index, state)` returns hits shaped like `retrieve.search`'s
    output. `state` is the loop's scratch dict; a tool may memoize expensive
    derived data there for the life of one search.
    """

    name = ""

    def search(self, query, index, state):
        raise NotImplementedError


class SemanticTool(Tool):
    """The dense cosine channel, unchanged."""

    name = "semantic"

    def __init__(self, embed_fn=None, embed_model=DEFAULT_EMBEDDER, k=TOOL_K):
        self.embed_fn = embed_fn
        self.embed_model = embed_model
        self.k = k

    def search(self, query, index, state):
        return search(index, query, self.embed_model, self.embed_fn, self.k)


def keyword_scores(query, word_map, chunks):
    """Chunk position -> idf-weighted overlap. Same math as
    `fusion.lexical_scores` without the band veto: a word living in more than
    half the corpus weighs nothing, only positive weights contribute, and the
    sums are over the word's posting positions.
    """
    total = len(chunks)
    scores = {}
    for word in set(words(query)):
        positions = word_map.get(word)
        if not positions or len(positions) > total / 2:
            continue
        weight = math.log((total - len(positions) + 0.5) / (len(positions) + 0.5))
        if weight <= 0:
            continue
        for position in positions:
            scores[position] = scores.get(position, 0.0) + weight
    return scores


class KeywordTool(Tool):
    """Rare-word overlap over `keywords.postings`, idf-weighted."""

    name = "keyword"

    def __init__(self, k=TOOL_K):
        self.k = k

    def search(self, query, index, state):
        chunks = index.get("chunks") or []
        if not chunks:
            return []
        word_map = state.get("word_map")
        if word_map is None:
            word_map = postings(index)
            state["word_map"] = word_map
        scores = keyword_scores(query, word_map, chunks)
        ordered = sorted(scores, key=lambda position: (-scores[position], position))
        return [
            _as_hit(chunks[position], scores[position]) for position in ordered[:self.k]
        ]


class RegexTool(Tool):
    """The query's tokens as one escaped pattern; ranked by match count."""

    name = "regex"

    def __init__(self, k=TOOL_K):
        self.k = k

    def search(self, query, index, state):
        terms = sorted({word for word in words(query) if word not in STOPWORDS})
        if not terms:
            return []
        pattern = re.compile(
            "|".join(rf"\b{re.escape(term)}\b" for term in terms), re.I
        )
        scored = []
        for position, chunk in enumerate(index.get("chunks") or []):
            matches = pattern.findall(chunk.get("text") or "")
            if matches:
                scored.append((len(matches), position, chunk))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [_as_hit(chunk, float(count)) for count, _, chunk in scored[:self.k]]


def build_tools(embed_fn=None, embed_model=DEFAULT_EMBEDDER, k=TOOL_K):
    """The tool registry. Dict order is the fallback spectrum:
    semantic (meaning) -> keyword (words) -> regex (characters).
    """
    return {
        "semantic": SemanticTool(embed_fn, embed_model, k),
        "keyword": KeywordTool(k),
        "regex": RegexTool(k),
    }


TOOL_NAMES = tuple(build_tools())

DECIDE_SYSTEM = """You pick the next retrieval step for an open-book question. Tools:
- semantic: embeds the query and ranks passages by meaning. Catches paraphrases; can miss an exact word.
- keyword: ranks passages by rare words shared with the query. Catches exact words; ignores word order and meaning.
- regex: matches the query's words as a case-insensitive pattern and counts hits. Catches acronyms and spellings; a common word floods it.

You see the question and every attempt so far: tool, query, chunk ids found, and a snippet of the top hits.

Reply with exactly two lines and nothing else:
line 1: semantic, keyword, regex, or stop
line 2: the search query for that tool (omit this line when you choose stop)

Pick the tool that finds evidence still missing for the question. Reusing a tool with a different query is allowed; repeating a query is not. Choose stop when the passages found already cover the question, or when another attempt cannot add anything."""

_LABEL = re.compile(r"^\s*(?:line\s*\d*|answer|tool|query|step\s*\d*)\s*[:.)-]\s*", re.I)


def _clean(line):
    """One reply line: markdown decorations and a leading label removed."""
    line = line.strip().strip("`*_#\"' ").strip()
    line = _LABEL.sub("", line)
    return line.strip().strip("`*_#\"'").strip()


def _snippet(text, chars=SNIPPET_CHARS):
    """One line out of a passage, for the decision prompt and the trace."""
    return " ".join((text or "").split())[:chars]


def decide_user_message(question, attempts):
    """The user text for pick_next_tool: the question, the tools, the attempts.

    Each attempt shows its tool and query, every hit chunk id, and up to
    SNIPPETS_PER_ATTEMPT one-line snippets from the top hits.
    """
    lines = [f"Question: {question}", "", "Tools: " + ", ".join(TOOL_NAMES)]
    lines.append("Attempts so far:")
    if not attempts:
        lines.append("(none)")
    for item in attempts:
        lines.append(f'{item["step"]}. tool={item["tool"]} query="{item["query"]}"')
        ids = [hit["chunk_id"] for hit in item.get("hits") or []]
        lines.append("   chunk ids: " + (", ".join(ids) if ids else "none"))
        for hit in (item.get("hits") or [])[:SNIPPETS_PER_ATTEMPT]:
            lines.append(f'   snippet {hit["chunk_id"]}: "{_snippet(hit.get("text"))}"')
    lines.append("Next tool and query?")
    return "\n".join(lines)


def parse_decision(reply, tool_names=TOOL_NAMES):
    """Read a pick_next_tool reply: {"kind", "tool", "query"}.

    kind is "tool" when the reply names exactly one tool, "stop" when it says
    stop and names no tool, "unparsed" otherwise (unknown name, several names,
    stop next to a tool, empty reply). The first non-empty line is tried first
    because the prompt documents that shape: the tool name or stop on line 1,
    the query on line 2 (or after the name on line 1, colon or space). A
    one-line "name rest" reply is taken literally unless rest itself names a
    tool or stop -- that would be an ambiguous reply, so it falls through to
    the scan. Failing that, the whole reply is scanned; a tool name or the
    word stop counts only as a whole word. An unparsed reply is
    pick_next_tool's cue to take the fallback.
    """
    text = reply or ""
    lines = [line for line in text.splitlines() if line.strip()]
    head = _clean(lines[0]) if lines else ""
    lowered = head.lower().rstrip(".").strip()

    def next_line_query():
        for line in lines[1:]:
            cleaned = _clean(line)
            if cleaned:
                return cleaned
        return None

    if lowered == "stop":
        return {"kind": "stop", "tool": None, "query": None}
    for name in tool_names:
        if lowered == name:
            return {"kind": "tool", "tool": name, "query": next_line_query()}
        if lowered.startswith(name + ":"):
            query = _clean(head[len(name) + 1:]) or None
            return {"kind": "tool", "tool": name,
                    "query": query or next_line_query()}
        if lowered.startswith(name + " "):
            rest = _clean(head[len(name) + 1:])
            if rest and not re.search(
                rf"\b(?:{'|'.join(tool_names)}|stop)\b", rest, re.I
            ):
                return {"kind": "tool", "tool": name, "query": rest}
            break
    names = [name for name in tool_names if re.search(rf"\b{name}\b", text, re.I)]
    says_stop = re.search(r"\bstop\b", text, re.I) is not None
    if len(names) == 1 and not says_stop:
        query = None
        match = re.search(r"(?im)^\s*(?:query|search)\s*[:=]\s*(.+)$", text)
        if match:
            query = _clean(match.group(1)) or None
        return {"kind": "tool", "tool": names[0], "query": query}
    if not names and says_stop:
        return {"kind": "stop", "tool": None, "query": None}
    return {"kind": "unparsed", "tool": None, "query": None}


def fallback_decision(question, attempts, tool_names=TOOL_NAMES):
    """The deterministic policy when the model's reply cannot be parsed.

    Pick the untried tool farthest from the tool that just ran on the fixed
    spectrum semantic -> keyword -> regex (meaning -> words -> characters):
    largest index distance, ties resolve to the earlier tool in that order.
    The query is the original question -- a fallback cannot invent a better
    one. No attempts yet -> the head of the spectrum. No untried tool left ->
    stop. Returns the same shape as pick_next_tool minus "reply".
    """
    tried = {item["tool"] for item in attempts}
    candidates = [name for name in tool_names if name not in tried]
    if not candidates:
        return {"tool": None, "query": None, "chosen_by": "fallback"}
    if not attempts:
        choice = candidates[0]
    else:
        previous = tool_names.index(attempts[-1]["tool"])
        choice = min(
            candidates,
            key=lambda name: (
                -abs(tool_names.index(name) - previous),
                tool_names.index(name),
            ),
        )
    return {"tool": choice, "query": question, "chosen_by": "fallback"}


def pick_next_tool(question, attempts, generate_fn=None, model=ANSWER_MODEL):
    """Ask the model which tool to run next, with what query, or to stop.

    Returns {"tool", "query", "chosen_by", "reply"}. `tool` is None when the
    loop should stop; `chosen_by` is "model" (a parsed reply) or "fallback"
    (the deterministic policy in fallback_decision); `reply` is the raw model
    reply, flattened and capped, for the trace. A model decision without a
    parseable query uses the original question.
    """
    generate_fn = generate_fn or ollama_generate
    user = decide_user_message(question, attempts)
    reply = generate_fn(DECIDE_SYSTEM, user, model)
    decision = parse_decision(reply)
    if decision["kind"] == "unparsed":
        choice = fallback_decision(question, attempts)
    elif decision["kind"] == "stop":
        choice = {"tool": None, "query": None, "chosen_by": "model"}
    else:
        choice = {
            "tool": decision["tool"],
            "query": decision["query"],
            "chosen_by": "model",
        }
    choice["reply"] = _snippet(reply, REPLY_CHARS)
    return choice


def agentic_search(index, question, generate_fn=None, max_steps=MAX_STEPS,
                   model=ANSWER_MODEL, embed_model=DEFAULT_EMBEDDER,
                   embed_fn=None, tools=None):
    """The loop. Decide, search, log, merge; stop on model/nothing-new/budget.

    Returns {"question", "attempts", "passages", "stopped"}. Every attempt
    carries step, tool, query, chosen_by, reply, hits (full hit dicts), and
    new (the chunk ids this attempt added). `passages` merges by chunk id,
    first-seen order, uncapped; a consumer applies its own passage limit.
    `stopped` is one of "model", "nothing_new", "max_steps", or "exhausted"
    (fallback with no untried tool left).
    """
    generate_fn = generate_fn or ollama_generate
    if tools is None:
        tools = build_tools(embed_fn, embed_model)
    state = {"word_map": None}
    attempts = []
    passages = []
    seen = set()
    stopped = "max_steps"
    for step in range(1, max_steps + 1):
        decision = pick_next_tool(question, attempts, generate_fn, model)
        if decision["tool"] is None:
            stopped = "model" if decision["chosen_by"] == "model" else "exhausted"
            break
        tool = tools[decision["tool"]]
        query = decision["query"] or question
        hits = tool.search(query, index, state)
        fresh = [hit for hit in hits if hit["chunk_id"] not in seen]
        for hit in fresh:
            seen.add(hit["chunk_id"])
            passages.append(hit)
        attempts.append({
            "step": step,
            "tool": tool.name,
            "query": query,
            "chosen_by": decision["chosen_by"],
            "reply": decision["reply"],
            "hits": hits,
            "new": [hit["chunk_id"] for hit in fresh],
        })
        if not fresh:
            stopped = "nothing_new"
            break
    return {
        "question": question,
        "attempts": attempts,
        "passages": passages,
        "stopped": stopped,
    }
