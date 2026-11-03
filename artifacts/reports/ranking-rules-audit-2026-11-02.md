# Ranking rules audit — 2026-11-02

Read-only audit of the rules that decide the passage window before generation
(`docs/ARCHITECTURE.md` §3.2). Every number below was measured on this tree
with the index files under `data/`, or is quoted from a named Baseline/Gate
run. The tree changed during the audit (Gate shipped `keywords.lexical_terms`
and `fusion.fuse(added=…)`); the rule being judged is named in each entry, and
the shipped replacement is noted separately in §5.

The fiction case is `data/index.mushoku-tensei_-jobless-reincarnation--light-novel--vol-80a406d0.sqlite`
(the novel). Rows come from Baseline's authored set: 42 rows, 12 novel and 30
technical (`artifacts/datasets/retrieval/retrieval-recall-2026-11-02.jsonl`),
pre-fix measurements in
`artifacts/runs/retrieval-recall-before-20261102T101846Z.json` and the pinned
row snapshot `artifacts/runs/retrieval-recall-before-dataset-20261102T101322Z.jsonl`.

## 1. The corpus these rules were written for, and the one they meet

The rules were tuned on `ddia` and `fde`: 1306 and 1042 chunks, real section
headings, 90 and 111 figures, and answers that live inside one definition. The
novel's shape is different in every dimension the rules read:

| Property | Novel | ddia (reference manual) | Source |
|---|---|---|---|
| chunks | 274 | 1306 | `SELECT count(*) FROM chunks` |
| chapters | 10 numeric + 3 matter (`section-0014` 45 chunks, `section-0015` 8, `section-0018` 1) | 17 | same |
| figures | **0** | 90 | same |
| median chunk text | 1276 chars (max 1431) | 1400 cap | `len(text)` |
| distinct headings | **274 / 274** | many-to-one | `count(distinct heading)` |
| heading is an exact prefix of its chunk text | **274 / 274** (median 124 chars) | yes, a real heading | measured |

The last two rows matter for every heading-based rule: in the novel each chunk
has its own heading and that heading is the chunk's own opening line. A
heading match therefore identifies exactly one chunk and carries no evidence
the body does not already carry. The lead's "heading is the first sentence"
claim is directionally right but not literally true: only 34 of 274 headings
equal the text's first sentence by sentence-splitting, because the heading is
the first *line* (it can hold two sentences, or end mid-sentence). The
load-bearing fact — 274 distinct headings, each a prefix of its own text —
holds exactly.

The entity vocabulary is the opposite of rare:

| word | chunks containing it (of 274) | `keywords.rare` (df ≤ 8) |
|---|---|---|
| atofe | 51 | False |
| rudeus | 65 | False |
| ruijerd | 69 | False |
| eris | 91 | False |
| sandor | 115 | False |
| zenith | 1 | True |

`RARE_DF = 8` (`keywords.py:32`) is a reference-manual constant: in a manual the
subject of a question is a term used a handful of times. In a novel the subject
is a name used throughout, so the gate is closed for every character name and
open for incidental nouns.

Window sizes: `RANK_BAND = 0.20` (`fusion.py:80`) admits the dense top 55 of 274
on the novel and the top 261 of 1306 on ddia. `RRF_K = 60` (`fusion.py:76`)
means a lexical rank-1 candidate at dense rank 55 still scores
1/115 + 1/61 = 0.0251 against 1/61 = 0.0164 for the dense leader, so one
candidate can reorder the window; it cannot add a second one.

## 2. Rule by rule

| Rule | Where | Assumption encoded | Holds on the novel? | Verdict |
|---|---|---|---|---|
| `retrieve.rank_chunks` + `ranked[:passage_limit]` | `retrieve.py:425`, `answer.py:3587` | one query vector over 1400-char chunks finds the passage; the answer is local | partly: scene asks yes, entity and paraphrase asks no | **keep** the score, **fix** the window composition (§6.1) |
| `_pin_chunk` | `answer.py:6365-6409` | the window is the caller's passage limit | it was not: 8 was cut to 5; fixed during this run | **fixed today** |
| `_figure_referencing_chunk` | `answer.py:839` | the book has figures and names them `figure N-M` | inert: 0 figures | keep |
| `fusion.fuse` admission (`MAX_LEXICAL_ADDITIONS*`, pre-fix single RRF candidate) | `fusion.py:177-233` | one (now 1–2) lexical candidate is enough; a lexical hit must also be dense-central (`RANK_BAND`) | partly: adds breadth, cannot recover the missed chunk | **fix** (cap), keep band |
| `captions.caption_seed` | `captions.py:31-110` | a caption is a dense name for an artifact | inert: `captions.py:40` returns on 0 figures | keep |
| `_prioritize_phrase_matches` | `answer.py:3417` | a heading is a section title and a phrase in it is a topic match | **no** — headings are first lines; fires on 1 of 10 novel rows | keep for technical, **drop for fiction** |
| `prefer_definitions` | `answer.py:406`, gate `answer.py:3870` | the book defines its terms | no; and `DEF_PREF` is off | keep, off |
| `rerank.rerank_passages` | `rerank.py:40` | an MS-MARCO cross-encoder orders book passages | unproven; window-only, cannot add a chapter | keep off |
| follow-up neighbour injection | `answer.py:3782-3823` | the next chunk continues the scene | **yes**, better than for a manual | keep |

### 2.1 `retrieve.rank_chunks` (retrieve.py:425)

Dense cosine over unit vectors, truncated to `passage_limit` at
`answer.py:3587`. Its assumption is that cosine proximity over a ~1300-char
chunk means relevance. Measured failure modes on the novel:

- **One scene fills the window.** For `who is atofe` the dense top 5 is
  chapter 6, 6, 6, 2, matter; the three chapter-6 passages are the adjacent
  chunks `section-0010-018/019/020`. Three of five slots carry one scene.
- **Names retrieve occurrences, not descriptions.** `who is sandor` puts its
  authored gold chunks at dense ranks 113, 32 and 55 and returns chapters
  `[1,5,5,1,3]`. `who is rudeus`: gold ranks 21, 93, 2, window
  `[8,matter,matter,1,1]`.
  This is the defect `entity.py` exists to work around (`docs/ARCHITECTURE.md`
  §3.5), and the entity path pre-empts retrieval entirely for 6 of the 12
  novel rows (§3 below).
- **The chunk is the wrong unit for a scene.** Median 1276 chars means a
  dialogue exchange and its narration are one vector; a question about one
  line in that scene cannot be separated from the rest.

The score itself is not the problem — it is the only channel that finds the
right chapter at all (`who is atofe`: gold at ranks 3, 4, 5, 10). The rule to
change is the truncation, not the math.

### 2.2 `_pin_chunk` (answer.py:6365-6409) — fixed during this run

The rule as Baseline measured the before state: `return pinned + rest[: max(0,
PASSAGE_LIMIT - len(pinned))]` sliced to the module constant `PASSAGE_LIMIT = 5`
(`answer.py:251`), ignoring the `passage_limit` that `retrieval_context`
received (8 for fiction, `bookkind.FICTION_PASSAGE_LIMIT`). Measured directly
on that version:

```
8 passages + pin -> 5 ['section-0009-015', 'fake-0', 'fake-1']
end_chunk_id only -> 5
```

Cost on a real row: for `who is sandor` with a chapter-1 pin, the 8-slot window
`pin + dense[0:7]` covers gold chapters 3, 6 and 8 (3/3); the 5-slot window
that version returned covered none of them (0/3).

Gate fixed it while this audit ran: the signature is now
`_pin_chunk(..., limit=PASSAGE_LIMIT)` and all three call sites
(`answer.py:3593`, `3673`, `3868`) pass `limit=passage_limit`, including the
final call after `retrieval_context` raises the window by the lexical
additions. Gate's re-measurement on the novel with a chapter-1 pin and the
served fiction window: 10 passages, chapters `[1,5,5,1,3,8,6,1,8,1]`, gold
chapters 3/6/8 all present. Verified in the tree: `grep -n "_pin_chunk("`
shows the three `limit=passage_limit` calls. Nothing left to change here; the
entry stays because it is the one rule whose harm was a plain code defect
rather than a tuning choice.

### 2.3 `_figure_referencing_chunk` (answer.py:839)

It requires a figure record; the novel has none (`SELECT count(*) FROM figures`
= 0), so `_figure_record` returns `None` and the rule is inert. On fde it does
its job: `figure 2-1` returns `ch02-002`. Keep; it costs one regex for books
without figures.

### 2.4 `fusion.fuse`, `RANK_BAND`, `RRF_K` (fusion.py:76-80, 177-233)

The pre-fix rule admitted exactly one lexical candidate. Measured on the novel,
that candidate is usually already in the dense window, so RRF only re-places
it: the BM25 top hit for `who is atofe` is `section-0010-020` at dense rank 2
(already shown), for `who is rudeus` `section-0012-019` at dense rank 1, for
`who is dohga` `section-0006-009` at dense rank 1. Gate's independent sweep on
12 fiction rows found the same flatness at one candidate: novel coverage 0.646
at cap 1, 0.757 at cap 2, 0.757 at caps 3 and 5.

The rule does earn its keep where the lexical channel has a strong hit outside
the dense head. Control row, ddia `fair-dev-44` ("What mechanism do LSM-tree
storage engines use…"): gold `text00008-019` sits at dense rank 7, outside the
5-slot window, and is BM25 rank 1 inside the band; fusion moves it to position 0
(measured). That is the rule working as designed on a manual.

What the rule cannot do, measured on the authored rows:

| row | gold dense rank | gold BM25 rank (admissible) | reachable by `added=k`? |
|---|---|---|---|
| novel `who is sandor` | 113 / 32 / 55 | 13 / 27 in band | needs k ≥ 13 |
| novel `where did rudeus wake up…` | 34 | 8 in band | needs k ≥ 8 |
| novel `what happened to alexander…` | 69 | not admissible (band 55) | no |
| ddia `What is linearizability?` | 9 | 33 | needs k ≥ 33 |

So widening the head is not a free coverage lever and is not the fix for the
remaining recall (§6.1). The band itself caused none of these misses: the
alexander chunk's BM25 score is 0.75 at rank 159, and the sandor chunk at dense
rank 55 is BM25 rank 73 — they are outside the lexical signal too. Verdict:
the band stays; the admission count is a real knob but bounded by these ranks.

### 2.5 `captions.caption_seed` (captions.py:31)

Returns at `captions.py:40` when the book has no figures, so the novel never
pays the second query embedding: measured 0 firings on its 12 rows, 0 figures
in the index. On the authored technical rows it fired once in 30
(ai-engineering, `How does RLHF work?`): it prepended `ch02-058` and dropped
`ch02-066` — one of that row's two gold chunks — from a 6-slot window, because
the seed replaces the tail (`return [seed] + passages[:-1]`, `captions.py:110`).
The row kept its other gold chunk, so its recall stayed green; the eviction is
the same displacement failure Gate removed from fusion, still present here.
Verdict: keep (it is the only rule that is structurally book-typed — a novel
cannot have captions to seed) and make the seed append rather than drop the
tail, measured on this row.

### 2.6 `_prioritize_phrase_matches` (answer.py:3417)

Measured on the authored set at the served window (8 passages for fiction,
5 for technical; dense → fusion where the gate opens):

| book | non-refusal rows | rule fired | gold evicted |
|---|---|---|---|
| novel | 10 | 1 | 0 |
| fde | 5 | 4 | 0 |
| quantization | 5 | 4 | 0 |
| ddia | 5 | 3 | 0 |
| ai-engineering | 5 | 4 | 0 |
| ai-agents | 5 | 4 | 0 |

On the novel it fires almost never, because its bigram phrases are built from
adjacent question tokens with both tokens non-stopword and ≥3 chars: `who is
atofe` yields no phrase at all, and `where does rudeus fight the dragon` yields
only `rudeus fight`, which no passage contains. The one novel row that fires is
`how did eris finish off gall falion?`: `section-0007-009` (chapter 3) scores 10
on the `gall falion` bigram and is promoted from position 8 to position 0 of an
8-passage window, ahead of the chapter-8 scene; the gold chunk keeps its slot
(no eviction), so the move is cosmetic rank churn, not a miss. Across the 25
authored technical rows it never evicted gold; its largest measured move is
ddia `Who originally described the LSM-tree indexing structure…`, where the
window stayed the same set in a different order. Verdict: keep for technical;
skip for fiction (it fires once in ten and the heading signal has no
independent meaning there; see below).

The heading half of the rule is the part that assumes a manual: on the novel
`in_heading` is true for 274/274 chunks whenever the phrase is in the chunk at
all, so "phrase in heading" is not a stronger signal than "phrase in body". The
one novel firing shows what that buys: a chapter-3 passage whose opening line
names Gall Falion leads a window of chapter-8 chunks for a question about a
chapter-4 fight. Gold survived, so it is churn rather than a miss; the heading
signal itself has no independent meaning on this book.

### 2.7 `prefer_definitions` (answer.py:406, enabled at 3870 by `DEF_PREF`)

Called directly on all 42 authored rows (not just with the env on), it
reordered **0** windows. `_definition_tokens` only matches `what is/are`,
`define`, `definition of`, and `definition_passage` then requires every token
plus a defining verb within 60 chars (`answer.py:345-353`); the novel's
sentences ("X was a…", "X is not…") do not match its pattern often enough to
fire. Since `DEF_PREF` defaults off, this rule costs nothing today. Verdict:
keep, off. It is a reference-manual rule (a novel does not define), but it is
also inert.

### 2.8 `rerank.rerank_passages` (rerank.py:40)

Off unless `RERANK_ENABLED=1` (`answer.py:3752`). It reorders only the passages
it is given (`top_k=len(passages)`), so it cannot recover a chapter the window
never held — it is a precision tool, not a recall one. The default model
(`cross-encoder/ms-marco-MiniLM-L-6-v2`) is trained on web question/passage
pairs, i.e. the same reference-manual assumption as the rest; whether it helps
a novel is unmeasured, and the deps are installed so a trial is possible.
Verdict: keep off; do not turn on for fiction without a measured run.

### 2.9 Follow-up neighbour injection (answer.py:3784-3825)

`cand_offsets = (0, 1)`: the previous quote's chunk plus its next chunk, same
chapter only, then `passages[:passage_limit]` (line 3806/3825) — correctly
using the caller's limit. Narrative adjacency is a *better* assumption for a
novel than for a manual (consecutive chunks are the same scene, not two
unrelated subsections), and the comment records the measurement that made the
rule narrow: five prepended neighbours consumed all five slots and 11 of 15
follow-ups lost their gold chunk (2026-11-01). Keep.

## 3. What the window metric does not measure

Three facts that bound how the numbers should be read:

1. **Six of the twelve novel rows never reach these rules in production.**
   `answer.ask` calls `_entity_profile_body` at `answer.py:4815` (and
   `respond` at 5412) *before* `retrieval_context`; it fires for a fiction
   book when the name appears in at least two chapters (`ENTITY_MIN_QUOTES = 2`,
   `answer.py:4682`, gate at 4719). Measured: `entity.profile_sentences` finds
   sentences in chapters 3, 5, 6, 8 for sandor; 2, 6, 8, 9 for atofe; 3, 4, 6, 7
   for eris; 2, 3, 6, 7 for dohga. So every `who is X` row is served from one
   sentence per chapter with no model call, and the retrieval coverage number
   for those rows measures a window the model never sees. It is still the right
   proxy for "could this window answer the question", but it is not the
   serving-path defect.
2. **The harness window is 5; the served fiction window is 8.** Baseline's
   contract runs use `k=5` for all books; `bookkind.FICTION_PASSAGE_LIMIT = 8`.
   The `--engine-window` runs are the serving comparison, and they start from
   8. Any rule verdict about "the window" must say which one it means; §6.1 is
   measured at the served window (8 for fiction).
3. **Coverage credits a chapter reached by any chunk, not the answering
   chunk.** Baseline added a gold-chunks-per-window column on the last run
   (`artifacts/runs/retrieval-recall-after-20261102T103635Z.txt`): four rows
   reach coverage 1.00 with zero gold chunks — novel `fic-ent-sandor` (0/3),
   `fic-scene-white-place` (0/1), `fic-scene-alec-dead` (0/1), and technical
   `tech-ddia-02` (0/1). The novel's mean is 1.10 gold chunks per window. So a
   coverage number is a diffusion signal; the chunk count is what says the
   answering passage is present, and the two must be read together.

## 4. Worked examples from the failing rows

### 4.1 Novel: `who is sandor` — retrieval never had the right chunk

Authored gold: `section-0007-017` (ch3), `section-0010-003` (ch6),
`section-0012-007` (ch8). Dense ranks 113, 32, 55. At the contract k=5 window
the chapters are `[1,5,5,1,3]` — coverage 1/3, chunk recall 0 — and at the
served 8-passage window the coverage is already 1.00, still with **0 of 3 gold
chunks** (`before-20261102T103622Z`, `after-20261102T103635Z`). `keywords.rare`
is False because `sandor` has df 115. Even with the gate open:

- gold BM25 ranks (unbounded, of 274) are 198, 34 and 73; scores 0.31, 1.49,
  1.16. The BM25 top candidate is `section-0012-019` at dense rank 9, not gold.
- to reach the best gold by appending lexical candidates needs k ≥ 13
  (admissible BM25 rank), by which point 12 non-gold passages enter first.

Attribution: **no ranking rule caused this miss**; the chunk is not near the top
of either channel. Fixing it needs a channel that can return "the book's
sentences about Sandor", which is what `entity.py` already does for names.

### 4.2 Novel: `where did rudeus wake up after falling from the bridge?` — the gate and the cap

Gold `section-0006-001`, dense rank 34, BM25 rank 8 among admissible chunks
(score 5.83). The gate is open on this row (a rare word is present); the
pre-fix fused window is `[section-0005-009, -008, -012, -011, section-0009-021]`,
and chapter 2 is not in it. The single-candidate rule took BM25 rank 1 (dense
rank 3, already shown); reaching the gold needs k ≥ 8. Attribution:
the admission cap is *a* cause, but the gold is 8th in its own channel, so the
cap is not the whole story — with the shipped `added=2` this row still misses
(Baseline: coverage 1.0, recall 0).

### 4.3 Novel: `what happened to alexander after his duel with rudeus?` — behind the band

Gold `section-0011-016`, dense rank 69. `RANK_BAND` = 55 of 274, so the lexical
leg may not even consider it; and its BM25 rank unbounded is 159 (score 0.75),
so the band is not what excluded it. Attribution: **retrieval never had the
right chunk**; no ordering rule can fix it.

### 4.4 Technical: `What is linearizability?` (ddia, tech-ddia-02) — the same shape in a manual

Gold `text00015-008` at dense rank 9; `linearizability` has df 54, so
`keywords.rare` is False; BM25 rank 33 (score 5.04), admissible under the band
(261 of 1306) but far behind. The window is all chapter 15, but the wrong
chapter-15 chunks. This is the technical twin of the entity case: the gate is
closed on a word the book uses constantly, and the admission count would need
to be 33. Verdict: the same fix direction (trigger and admission) applies to
both kinds, so this is not a fiction-only finding. Baseline records this row as
coverage 1.0 / recall 0 at both windows; `ai-agents` recall is 1.000 before and
after on the authored set, so it is the only authored technical row that
exercises the failing direction.

### 4.5 Control: ddia `fair-dev-44` (legacy comparability row) — fusion recovering a lexical hit

Gold `text00008-019` at dense rank 7 (outside the 5-window), BM25 rank 1 in
band. Fusion puts it at position 0. This is the case the rule was built for and
the reason the band should stay: the France refusal and this row are the two
sides of the same veto, and the veto is decided at dense rank 55 of 274 on the
novel and 261 of 1306 on ddia, not by the BM25 score.

## 5. What changed today (context for the numbers)

Gate shipped `keywords.lexical_terms` (rare **or** capitalised in ≥50% of
mentions) and a non-displacing admission shape, `fusion.fuse(added=k)`: dense
head first, then up to k admissible BM25 chunks, `MAX_LEXICAL_ADDITIONS = 1`
(technical) / `MAX_LEXICAL_ADDITIONS_FICTION = 2` (`fusion.py:102-103`),
`retrieval_context` raises `passage_limit` by what was added
(`answer.py:3716-3737`). Gate also fixed `_pin_chunk`'s window truncation in
the same change (§2.2). Baseline's authored-set numbers:

- contract window k=5: novel coverage 0.575 → 0.775, recall 0.700 → 0.700,
  entity coverage 0.458 → 0.625; every technical book unchanged exactly.
- served window (fiction 8): novel coverage 0.767 → 0.900, recall 0.700 →
  0.700, window 8.0 → 9.7 passages; technical books +0.000.
- The cap-based design (displacement) was rejected on measurement: cap 2 cost
  quantization recall 1.000 → 0.875, cap 3 cost novel recall 0.700 → 0.600.

The audit view: the shipped change is a coverage fix, not a recall fix. It
takes the diffusion out of the entity windows (coverage) and leaves the missed
chunks missed (recall), because those chunks are far down both channels. That
is consistent with every attribution in §4.

The gold-chunk column sharpens that. Of the novel's +0.133 served coverage,
`fic-scene-white-place` supplies the largest single gain (0.00 → 1.00) with the
same 0/1 gold chunks before and after: the added chapter is reached by a
non-gold chunk. `fic-ent-sandor` was 1.00 coverage with 0/3 gold chunks before
the change as well. The rows where the window actually gained a gold chunk are
`fic-ent-ruijerd` (gold 1/3 → 2/3, coverage **0.67 → 0.67**: chapter 4 is the
missing one both times) and `fic-ent-dohga` (gold 1/3 → 2/3, coverage 0.33 →
0.67), both entity rows whose real serving path is `entity.py`, not retrieval
(§3). So the coverage gain is real as diffusion and is not evidence that the
answering passage entered the window; the report's §4 attributions already say
why.

## 6. The two rules to change next

Two notes before the list. The rule this audit opened with — `_pin_chunk`
cutting a fiction window from 8 to 5 — was fixed during the run (§2.2), so it
does not occupy a slot. And the fusion admission count was judged and is not
the lever: the measured misses need k = 8, 13 and 33, and the alexander chunk
is outside the band entirely (§2.4), while the shipped additions already took
the coverage win that the count can give. Both entries below are ordered by
what they would change in the measured numbers.

### 6.1 Compose the fiction window by chapter, not by chunk (retrieve.py:425 / answer.py:3587)

`rank_chunks(...)[:passage_limit]` can spend three of five slots on one scene
(`who is atofe`: `section-0010-018/019/020`) while the authored gold spans
chapters 2, 6, 8 and matter. Prototype measured on the 10 answerable novel
rows: one best-cosine chunk per chapter, 8 chapters, ordered by that chunk's
score.

| window | novel chunk recall | novel chapter coverage | matter slots (all books) |
|---|---|---|---|
| dense → fusion (today) | 7/10 | 0.900 | 12 |
| best chunk per chapter | 6/10 | **0.967** | 18 |

Per book, the technical damage is uneven: quantization 5/5 → 5/5, ddia 4/5 →
4/5, ai-agents 5/5 → 5/5, but fde 5/5 → 4/5 and ai-engineering 5/5 → 4/5, and
matter slots rise (fde 0 → 2, ai-engineering 1 → 3). The trade on the novel is
+0.067 coverage for −1 chunk. It must stay fiction-only: a manual chapter holds
100+ chunks and the best-cosine chunk in the right chapter is rarely the gold
chunk. Do not ship it as a global window change.

Status: the prototype as measured **fails the ship gate this entry sets** —
novel recall 6/10 is below 0.700, and fde and ai-engineering each lose a row, so
"every technical book's recall unchanged" is false. It is therefore evidence
that the composition rule is wrong, not a shippable replacement. Baseline is
right not to encode an unshipped algorithm in the harness as a default; the
probe should be a flag reported next to the current modes.

Measurement that decides the rule: an append-shape variant — keep the dense
head and append one best chunk from each chapter the window does not yet
reach — run as a flagged probe over the authored 42 rows at the served window.
Success: novel coverage rises, novel recall does not fall below 0.700, no
technical book loses a gold chunk, and the gold-chunks-per-window column does
not fall. If chapter diversity cannot be bought without either recall cost, the
conclusion is that the per-chapter pick needs the BM25/entity signal that §4.1
shows the cosine does not have.

### 6.2 `caption_seed` must not drop the window tail (captions.py:110)

Measured loss: on the authored ai-engineering row `tech-aieng-02`
("How does RLHF work?", gold `ch02-066` and `ch02-067`) the rule prepends
`ch02-058` and drops `ch02-066` — one of the two gold chunks — because
`return [seed] + passages[:-1]` discards the tail of a filled window. The
baseline cannot catch this by construction: `retrieval-recall.py` stops before
`retrieval_context`'s answer-stage steps, so its row prints `goldchunks=2/2`
(the caption rule never ran), while the direct call to `caption_seed` returns a
window with one gold chunk left. With a window that now also holds appended
lexical candidates, the tail is exactly where a recovered chunk sits, so the
shape gets more expensive, not less.

Change: `return [seed] + passages[:-1]` → `return [seed] + passages`, letting
the caller's window handle the length the way fusion's `added=k` does.

Measurement: replay the 30 authored technical rows with and without the change
and require that no window loses a gold chunk (today 1 row loses 1), and that
the per-row `win=` length Baseline now prints grows by one on the firing row
instead of staying fixed. The reference probe is
`captions.caption_seed(index, "How does RLHF work?", dense+fused window)` on
`data/index.ai-engineering.sqlite`, which today returns
`['ch02-058', 'ch02-067', 'ch02-068', 'ch06-031', 'ch02-113', 'ch02-114']`
from a window that held `ch02-066` as well.

Not recommended next: widening `MAX_LEXICAL_ADDITIONS` (needs k = 8, 13 and 33
on the three measured misses and adds 7–32 non-gold passages first), and
dropping `RANK_BAND` (caused none of the measured misses; it is what keeps the
France refusal and the ddia recovery behaving as measured).
