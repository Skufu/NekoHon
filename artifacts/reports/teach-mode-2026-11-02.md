# Mode `teach`: plain explanation with a labelled example — 2026-11-02

Owner use case: reading a technical book, stuck on a section, asking "explain in
simple words" or "explain with an example". The engine was built for the other
question — "what does the book say" — and it cannot answer this one, by design.

## Why the old path cannot

`PARAPHRASE_SYSTEM`, the plain register's rewrite prompt, says: *"do not add any
fact, comparison, or example that is not in the sentence"*. The quote-first
prompts make the answer a quote plus one line.

Same question, `mode: "answer"`, measured over HTTP:

```
Most replicated databases provide at least eventual consistency, which means that
if you stop writing to the database and wait for some unspecified length of time,
then eventually all read requests will return the same value [1]. [Ch. 9]
```

39 words, a quoted sentence, no example. That is the prompt working as written.

## The mode

`mode: "teach"`, routed in both the JSON and the streaming handler. Two model
calls, because the 2B model will not do both jobs in one:

1. **Explanation**, prefilled `In plain words, `. Without the prefill it answers
   with the passage itself (measured: a 145-word quote for "explain write-ahead
   logging"). The prefill is stripped from the output; the model repeats it.
2. **Example**, prefilled `Example: `, with the idea and the passage as context.
   Measured: it writes one when the example is the only thing asked for and the
   reply is prefilled, and never inside a mixed answer (0 of 2 questions).

Citations are attached by the engine, not quoted by the model: the passage whose
content words overlap the explanation most, and a real sentence from it. The
`Example:` label is the contract — the reader can see which sentence is the
book's and which is ours.

Guards, all measured into place:

- the refusal sentence is still exactly `Not in this book.`;
- a non-Latin answer is rejected (the model drifted to Chinese on
  "what does linearizability mean": `线性可确定性 (linearizability) means ...`), and
  retried once with a different prefill, which landed in English;
- figure-number prefixes are stripped (`1.0 data warehouses ...`, `8-8-8 is a
  rule ...`), and an answer that no longer opens a sentence is rejected;
- an example that repeats the explanation is dropped (the fde lake/warehouse
  question returned the same sentence twice);
- a rejected explanation degrades to `mode: "answer"` rather than refusing a
  question the book covers.

## Measured, six questions

| question | result |
|---|---|
| eventual consistency (ddia) | explanation + correct example, 49 words |
| partitioning (ddia) | explanation + correct example, 36 words |
| write-ahead log (ddia) | explanation + a two-step example, 48 words |
| data lake vs warehouse (fde) | explanation rejected (figure prefix), degraded to `answer` |
| idempotence (fde) | explanation rejected, degraded to `answer` (90 words, correct) |
| watermark (fde) | degraded to `answer` (15 words, thin) |

Latency 3.2–4.8 s for the two-call path; the 16.8 s outlier was a degraded run.

**Example correctness is not guaranteed.** Four examples were read: three were
right, one was wrong — for linearizability the model wrote "200ms after a write,
a read returns the old value because the write never finished", which describes
the failure linearizability forbids. The label says the example is ours; it does
not say it is correct, and the engine cannot check it. That is the honest
ceiling of this model on this task, and the reason the mode is opt-in.

## The eval: dimensions in, lookups out

`artifacts/harnesses/teach-eval.py`. "Explain it with an example" is not one
task, so the set is sampled rather than written by hand:

| dimension | values |
|---|---|
| book | the five technical indexes |
| kind | mechanism (`what is X`), process (`how does X work`), comparison (`difference between X and Y`), why (`why does X matter`) |
| phrasing | `with an example`, `can you give me an example of it`, `and an example?`, `bare` |
| coverage | in-book, absent (a concept from another book's headings) |

The rule that makes it a sample: every cell (book × kind) is filled once, so
each book sees every kind; phrasings rotate through the cells; one `absent` row
per book. Concepts are never typed — they come from the book's own section
headings, deduplicated and ordered deterministically. `bare` is the control: a
question with no request must not be routed. 25 rows, seed 20261102,
`--rows-only` prints the grid.

Scored automatically: routing, refusal correctness, example presence, and
grounding of the explanation against its cited passages (the example is excluded
from that measure — it is the writer's illustration by contract). `--judge` runs
the new `judge.judge_teach_example` rubric (correct / contradicts / missing).

### Three runs, and what each one changed

| run | routed | refused-absent | answered-in-book | example present | failures |
|---|---|---|---|---|---|
| 1 | 1.00 | 0.60 | 1.00 | 0.41 | 12 |
| 2 | 1.00 | 1.00 | 1.00 | 0.40 | 9 |
| 3 | 1.00 | 1.00 | 1.00 | **1.00** | **0** |

Run 1's failures were two different bugs: two out-of-book questions
("Episodic Memory", "Capability extension") were answered instead of refused —
the word-level vocabulary guard cannot see a phrase no passage discusses — and
nine explanations were rejected as fragments, so the reader got the ordinary
quote answer instead of a teach answer. The fixes were `phrase_covered`
(all content words inside one 10-token window, or the phrase itself; separates
all 20 in-book subjects from all 5 absent ones), and trying the next prefill when
the explanation is unusable rather than only when it is in another script. The
shape check also stopped requiring a capital first letter, because "3-tier
architecture separates ..." is a real answer.

### The examples, read by hand

`judge.judge_teach_example` could not run here: the `cli` backend returned
`JudgeTransportError` on all 15 calls and no offline judge model is pulled. So
the 15 examples the eval produced were read:

- **10 correct** — "Active security means constantly looking for new threats ...
  Instead of running annual security scans, you hire a security researcher to
  analyse real-world phishing campaigns"; "32-bit floats need 4 bytes while 8-bit
  integers need only 1, so you pack two small integers into one byte".
- **5 weak** — three restate the explanation instead of illustrating it, and two
  comparison questions give one example per side without showing the difference.
- **0 contradicted** the passages.

So on this model the mode delivers an example 100% of the time and a *useful*
example about two times in three. That is the number to improve, and it is a
model problem, not a prompt one.

## What is left

- No UI control, by owner decision: the reader types the request. The engine
  routes `ask`/`answer` to teach when the question asks for an example
  (`answer.asks_for_example`), so the UI needs no change. The cue requires a
  request verb or a second-person ask, because the hard bench carries "What
  uptime percentage represents a concrete example of a service-level objective
  in contracts?" and that must stay a normal answer.
- Example quality: the only real fix is a model trained on explanations and
  examples; prompt work bought the shape, not the correctness.
