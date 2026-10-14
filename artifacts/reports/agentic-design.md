# Agentic tool loop — design, prompts, and live trace

Status: **prototype, not wired into the server.** The four routes are frozen.
Files: `agentic.py`, `tests/test_agentic.py` (13 tests, all offline),
`artifacts/probe-agentic.py` (live probe). Verified 2026-10-13 with
`python -m unittest discover -s tests` (141 tests, OK) and
`python artifacts/probe-agentic.py` (trace below).

## The loop

```
                 +----------------------------------------------+
                 | pick_next_tool    (qwen2.5:7b, temperature 0)|
   question ---> |  reads : question + attempt log               |
                 |          (tool, query, hit ids, snippets)     |
                 |  writes: one tool + query   -- or --  stop    |
                 +----------------------------------------------+
                        |                                    ^
            tool+query  |                                    | one attempt
                        v                                    | logged
                 +-------------------+    hits (top 10)   +--+------------------+
                 | the chosen tool   |------------------->| attempt log        |
                 |  semantic search  |                    | + merged passages  |
                 |  keyword search   |                    |   (deduped by      |
                 |  regex search     |                    |    chunk id,       |
                 +-------------------+                    |    first-seen)     |
                                                          +--------------------+
   stop when: model says stop                                  |
              |  a tool returns nothing new                     |
              |  max_steps = 3 reached                          v
              +----------------------------------> {"attempts", "passages"}
```

The tools share one interface: `.name` and
`.search(query, index, state) -> list of retrieve.search-shaped hits`
(`chunk_id, chapter, heading, text, source, score`). `state` is per-search
scratch; the keyword tool memoizes the postings map there.

| tool | machinery | strength | known weakness |
| --- | --- | --- | --- |
| semantic | `retrieve.search`, dense cosine, top-k | paraphrases, concepts | a rare exact word can rank low |
| keyword | idf-weighted overlap over `keywords.postings`; same math as `fusion.lexical_scores`, restated without the dense-band veto (no rank map as input; pinned against fusion in a unit test) | exact terms | ignores order and meaning |
| regex | the query's tokens (stopwords dropped) as one escaped `\bterm\b\|...` pattern, case-insensitive, ranked by match count | acronyms, spellings | a common content word floods it |

Scores are tool-local (cosine, idf sums, match counts) and are **not
comparable across tools**; the merge keeps the first-seen hit exactly as the
first tool returned it.

## The exact prompts

System (`agentic.DECIDE_SYSTEM`), verbatim:

```
You pick the next retrieval step for an open-book question. Tools:
- semantic: embeds the query and ranks passages by meaning. Catches paraphrases; can miss an exact word.
- keyword: ranks passages by rare words shared with the query. Catches exact words; ignores word order and meaning.
- regex: matches the query's words as a case-insensitive pattern and counts hits. Catches acronyms and spellings; a common word floods it.

You see the question and every attempt so far: tool, query, chunk ids found, and a snippet of the top hits.

Reply with exactly two lines and nothing else:
line 1: semantic, keyword, regex, or stop
line 2: the search query for that tool (omit this line when you choose stop)

Pick the tool that finds evidence still missing for the question. Reusing a tool with a different query is allowed; repeating a query is not. Choose stop when the passages found already cover the question, or when another attempt cannot add anything.
```

User message (`agentic.decide_user_message`), template:

```
Question: {question}

Tools: semantic, keyword, regex
Attempts so far:
(no attempts yet)                <- or one block per attempt:
{step}. tool={name} query="{query}"
   chunk ids: {id, id, ...}      <- "none" when the tool returned nothing
   snippet {chunk_id}: "{first 100 chars of the hit text, one line}"
   ... up to 3 snippets per attempt
Next tool and query?
```

Rendered for real by the probe run below (Codd, decision call 2 — the call
that returned `stop`):

```
Question: Codd introduced the idea of what

Tools: semantic, keyword, regex
Attempts so far:
1. tool=semantic query="Codd introduced the idea of"
   chunk ids: ch04-067, ch04-052, ch03-071, ch05-030, ch08-051, ch01-008, ch08-052, ch05-048, ch02-074, ch03-032
   snippet ch04-067: "Modularity Modularity (Figure 4-5) is an old concept in software engineering, but modular distribute"
   snippet ch04-052: "Open Source Software Open source software (OSS) is a software distribution model in which software, "
   snippet ch03-071: "Data Warehouse A data warehouse is a central data hub used for reporting and analysis. Data in a dat"
Next tool and query?
```

Parsing: the first line must be a tool name or `stop` (the query may ride on
line 2, or after the name on line 1). Otherwise the whole reply must name
exactly one tool or say `stop` and nothing else. Anything else is a parse
failure and takes the deterministic fallback: the untried tool farthest from
the one that just ran on the fixed spectrum semantic -> keyword -> regex
(largest index distance; ties resolve to the earlier tool), with the original
question as the query; no attempts yet takes the head of the spectrum; no
untried tool left stops the loop.

## Live trace

`python artifacts/probe-agentic.py`, 2026-10-13, `data/index.json`
(read-only, 1042 chunks, nomic-embed-text, qwen2.5:7b). Full output:

```
index index.json: 1042 chunks, embedder nomic-embed-text, answer model qwen2.5:7b
tools: semantic, keyword, regex

one dense search (retrieve.search, k=5): 0.1s, 5 hits
single-shot reference (answer.ask on the first question): 0.5s, refused=False, first 90 chars: '[Ch. 8] "Codd introduced the idea of normal forms"'

========================================================================
Q: Codd introduced the idea of what
  step 1  tool: semantic  chosen by: model
    query: Codd introduced the idea of
    model said: semantic Codd introduced the idea of
      hit ch04-067  ch4  score 0.645
      hit ch04-052  ch4  score 0.620
      hit ch03-071  ch3  score 0.618
      hit ch05-030  ch5  score 0.615
      hit ch08-051  ch8  score 0.610
      hit ch01-008  ch1  score 0.607
      hit ch08-052  ch8  score 0.607
      hit ch05-048  ch5  score 0.602
      hit ch02-074  ch2  score 0.601
      hit ch03-032  ch3  score 0.600
    new: ['ch04-067', 'ch04-052', 'ch03-071', 'ch05-030', 'ch08-051', 'ch01-008', 'ch08-052', 'ch05-048', 'ch02-074', 'ch03-032']
  merged passages: 10 ['ch04-067', 'ch04-052', 'ch03-071', 'ch05-030', 'ch08-051', 'ch01-008', 'ch08-052', 'ch05-048', 'ch02-074', 'ch03-032']
  stopped: model  |  model calls: 2  |  wall: 0.5s
========================================================================
Q: what is an endpoint in streaming ingestion
  step 1  tool: semantic  chosen by: model
    query: an endpoint in streaming ingestion definition
    model said: semantic an endpoint in streaming ingestion definition
      hit ch07-098  ch7  score 0.710
      hit ch02-024  ch2  score 0.706
      hit ch07-060  ch7  score 0.703
      hit ch02-018  ch2  score 0.693
      hit ch07-037  ch7  score 0.671
      hit ch07-059  ch7  score 0.666
      hit ch07-002  ch7  score 0.659
      hit ch07-004  ch7  score 0.657
      hit ch07-016  ch7  score 0.654
      hit ch11-020  ch11  score 0.654
    new: ['ch07-098', 'ch02-024', 'ch07-060', 'ch02-018', 'ch07-037', 'ch07-059', 'ch07-002', 'ch07-004', 'ch07-016', 'ch11-020']
  step 2  tool: semantic  chosen by: model
    query: an endpoint in streaming ingestion explanation
    model said: semantic an endpoint in streaming ingestion explanation
      hit ch02-024  ch2  score 0.745
      hit ch07-060  ch7  score 0.738
      hit ch07-098  ch7  score 0.738
      hit ch02-018  ch2  score 0.725
      hit ch07-037  ch7  score 0.708
      hit ch07-059  ch7  score 0.700
      hit ch02-017  ch2  score 0.695
      hit ch07-001  ch7  score 0.695
      hit ch07-016  ch7  score 0.689
      hit ch02-016  ch2  score 0.685
    new: ['ch02-017', 'ch07-001', 'ch02-016']
  step 3  tool: semantic  chosen by: model
    query: an endpoint in streaming ingestion context
    model said: semantic an endpoint in streaming ingestion context
      hit ch02-024  ch2  score 0.726
      hit ch07-060  ch7  score 0.722
      hit ch07-098  ch7  score 0.717
      hit ch07-037  ch7  score 0.702
      hit ch02-018  ch2  score 0.698
      hit ch07-059  ch7  score 0.691
      hit ch07-013  ch7  score 0.670
      hit ch11-020  ch11  score 0.669
      hit ch02-021  ch2  score 0.666
      hit ch03-095  ch3  score 0.666
    new: ['ch07-013', 'ch02-021', 'ch03-095']
  merged passages: 16 ['ch07-098', 'ch02-024', 'ch07-060', 'ch02-018', 'ch07-037', 'ch07-059', 'ch07-002', 'ch07-004', 'ch07-016', 'ch11-020', 'ch02-017', 'ch07-001', 'ch02-016', 'ch07-013', 'ch02-021', 'ch03-095']
  stopped: max_steps  |  model calls: 3  |  wall: 0.8s
========================================================================
Q: MAD data landscape
  step 1  tool: semantic  chosen by: model
    query: MAD data landscape
    model said: semantic MAD data landscape
      hit ch03-099  ch3  score 0.671
      hit ch02-037  ch2  score 0.630
      hit ch11-018  ch11  score 0.628
      hit ch03-084  ch3  score 0.628
      hit ch06-080  ch6  score 0.626
      hit ch01-057  ch1  score 0.625
      hit ch02-059  ch2  score 0.621
      hit ch04-092  ch4  score 0.620
      hit ch03-081  ch3  score 0.618
      hit ch03-079  ch3  score 0.617
    new: ['ch03-099', 'ch02-037', 'ch11-018', 'ch03-084', 'ch06-080', 'ch01-057', 'ch02-059', 'ch04-092', 'ch03-081', 'ch03-079']
  step 2  tool: semantic  chosen by: model
    query: MAD data landscape evolution
    model said: semantic MAD data landscape evolution
      hit ch07-038  ch7  score 0.649
      hit ch03-084  ch3  score 0.639
      hit ch03-099  ch3  score 0.637
      hit ch01-007  ch1  score 0.634
      hit ch01-018  ch1  score 0.634
      hit ch11-023  ch11  score 0.633
      hit ch02-037  ch2  score 0.629
      hit ch04-020  ch4  score 0.626
      hit ch11-018  ch11  score 0.626
      hit ch03-079  ch3  score 0.625
    new: ['ch07-038', 'ch01-007', 'ch01-018', 'ch11-023', 'ch04-020']
  step 3  tool: semantic  chosen by: model
    query: MAD data landscape components
    model said: semantic MAD data landscape components
      hit ch03-099  ch3  score 0.647
      hit ch03-084  ch3  score 0.628
      hit ch02-037  ch2  score 0.618
      hit ch11-018  ch11  score 0.609
      hit ch03-078  ch3  score 0.608
      hit ch03-085  ch3  score 0.607
      hit ch09-042  ch9  score 0.606
      hit ch06-070  ch6  score 0.601
      hit ch06-080  ch6  score 0.601
      hit ch03-015  ch3  score 0.600
    new: ['ch03-078', 'ch03-085', 'ch09-042', 'ch06-070', 'ch03-015']
  merged passages: 20 ['ch03-099', 'ch02-037', 'ch11-018', 'ch03-084', 'ch06-080', 'ch01-057', 'ch02-059', 'ch04-092', 'ch03-081', 'ch03-079', 'ch07-038', 'ch01-007', 'ch01-018', 'ch11-023', 'ch04-020', 'ch03-078', 'ch03-085', 'ch09-042', 'ch06-070', 'ch03-015']
  stopped: max_steps  |  model calls: 3  |  wall: 0.7s
========================================================================
Q: What does CRUD stand for?
  step 1  tool: keyword  chosen by: model
    query: CRUD
    model said: keyword CRUD
      hit ch05-019  ch5  score 5.072
      hit ch05-020  ch5  score 5.072
      hit ch05-021  ch5  score 5.072
      hit ch05-028  ch5  score 5.072
      hit ch05-029  ch5  score 5.072
      hit ch08-005  ch8  score 5.072
    new: ['ch05-019', 'ch05-020', 'ch05-021', 'ch05-028', 'ch05-029', 'ch08-005']
  step 2  tool: semantic  chosen by: model
    query: CRUD, which stands for create, read, update, and delete
    model said: semantic CRUD, which stands for create, read, update, and delete
      hit ch05-019  ch5  score 0.866
      hit ch05-029  ch5  score 0.675
      hit ch05-021  ch5  score 0.667
      hit ch05-020  ch5  score 0.652
      hit ch08-106  ch8  score 0.647
      hit app01-016  chapp01  score 0.643
      hit ch06-032  ch6  score 0.633
      hit ch06-096  ch6  score 0.631
      hit ch08-111  ch8  score 0.627
      hit ch05-030  ch5  score 0.625
    new: ['ch08-106', 'app01-016', 'ch06-032', 'ch06-096', 'ch08-111', 'ch05-030']
  merged passages: 12 ['ch05-019', 'ch05-020', 'ch05-021', 'ch05-028', 'ch05-029', 'ch08-005', 'ch08-106', 'app01-016', 'ch06-032', 'ch06-096', 'ch08-111', 'ch05-030']
  stopped: model  |  model calls: 3  |  wall: 0.7s
========================================================================
Q: dark matter data
  step 1  tool: semantic  chosen by: model
    query: dark matter data definition properties evidence
    model said: semantic dark matter data definition properties evidence
      hit ch11-025  ch11  score 0.658
      hit ch05-045  ch5  score 0.629
      hit ch03-099  ch3  score 0.623
      hit ch02-059  ch2  score 0.622
      hit ch08-065  ch8  score 0.617
      hit ch08-050  ch8  score 0.614
      hit ch05-054  ch5  score 0.613
      hit ch06-085  ch6  score 0.610
      hit ch09-004  ch9  score 0.610
      hit ch02-028  ch2  score 0.609
    new: ['ch11-025', 'ch05-045', 'ch03-099', 'ch02-059', 'ch08-065', 'ch08-050', 'ch05-054', 'ch06-085', 'ch09-004', 'ch02-028']
  merged passages: 10 ['ch11-025', 'ch05-045', 'ch03-099', 'ch02-059', 'ch08-065', 'ch08-050', 'ch05-054', 'ch06-085', 'ch09-004', 'ch02-028']
  stopped: model  |  model calls: 2  |  wall: 0.4s
========================================================================
summary
    0.5s  2 decision call(s)  Codd introduced the idea of what
    0.8s  3 decision call(s)  what is an endpoint in streaming ingestion
    0.7s  3 decision call(s)  MAD data landscape
    0.7s  3 decision call(s)  What does CRUD stand for?
    0.4s  2 decision call(s)  dark matter data
  total 3.1s, 13 decision calls over 5 questions
```

Counts from the trace: 10 attempts (semantic 9, keyword 1, regex 0), 3 stops
by the model, 2 runs to the 3-step budget, 0 parse failures (so 0 fallback
picks), 0 `nothing_new` stops in this run. A `nothing_new` stop was observed
in an earlier run of the same probe, before the on-line query parse: the
model repeated its keyword query verbatim, and the rule ended the loop.

## Honest notes

**Latency vs single-shot.** Measured on this box, warm, on the same index:

| run | wall |
| --- | --- |
| one dense search (`retrieve.search`, k=5) | 0.1 s |
| single-shot `answer.ask`, warm (this run) | 0.5 s |
| single-shot `answer.ask`, first run of this probe (model not warm) | 16.8 s |
| agentic loop, per question | 0.4-0.8 s (2-3 decision calls each) |
| agentic loop, 5 questions total | 3.1 s, 13 decision calls |

The warm single-shot ask measured 0.5 s here; AGENTS.md records warm asks
0.4-1.2 s. The 16.8 s was the first probe run of the day: the calls after it
were fast, which matches the known ~25 s cold-load profile, so treat it as
model load, not loop cost. The agentic loop is **cheap per question (+1 to +2
extra model calls, each ~15 tokens)** because a decision reply is one line.
But that comparison is not end-to-end: the prototype stops at passages and
never generates a final answer. Wired in, every question would add one answer
generation on top, so the fair price is single-shot ask + 2-3 small decision
calls, measured here as +0.3-0.7 s per question over the retrieval baseline
(0.1 s).

**Model calls per question:** 2-3 (13 over 5 questions). Budget is
`max_steps=3` (one first channel plus two complements), a documented cap, not
a tuned number. Two questions used it fully.

**When it beat single-shot here:** nowhere, measured. All five questions
already answer under the single-shot path (the golden set and probes cover
Codd, CRUD, MAD). The loop's best moment is the CRUD trace: keyword surfaced
the chunks that contain "CRUD", the model read the definition sentence in a
snippet, and its next semantic query was that sentence -- ch05-019 jumped to
0.866 and led. That is the intended multi-hop shape (result A seeds query B),
but it did not change the outcome: the single-shot path already answers CRUD
from ch05-019. On endpoint, MAD, and dark matter the loop mostly re-ran
semantic with paraphrases; the extra chunks were dense neighbors (3-5 new per
extra call) and 1 of 5 (ch04-020) was material that the single-shot path also
reaches via caption seeding. Nothing here justifies a claim of better
answers.

**When it should beat single-shot:** questions where one channel badly misses
what another would find -- a rare exact term dense ranks low (the keyword
tool's case), an acronym (regex), or a genuine two-hop question whose second
query cannot be written before the first result is read. None of the five
probe questions is a clean two-hop test; a battery with measured single-shot
failures is the honest prerequisite before wiring anything in.

**When it does not:** when the first dense pass already holds the answer (4
of 5 here) the loop spends real latency for tail passages; and the uncapped
merge (10-20 passages here) exceeds the answer layer's 5-passage budget, so a
consumer must cut it down or risk diluting the answer. Extra passages are not
free evidence.

**Wiring into a future `mode`:** the contract lists `mode` as
`ask | answer | explain | quiz` and the routes are frozen, so an `agentic`
mode is a contract change that needs an explicit yes first. The mechanical
part is small: `agentic_search(index, question)["passages"]` is a drop-in for
`answer.retrieval_context(...)["passages"]` (same hit shape; pinned by a unit
test), so the server could hand the merged set to the existing answer layer.
The open pieces: where to cut the merged list and in what order (tool-local
scores are not comparable), how the existing stages compose with the loop
(`readings` and `fusion` run per search today; `caption_seed`'s lead would
have to be re-established after a merge), a decision-call timeout and a
budget for what happens when Ollama is slow, and the window's mode list
(window/index.html) -- all out of scope for this prototype.
