"""new-forms generator 2026-10-15: Part A candidates for the next teacher build.

Part A of the next capture (Qwen3.8-27B on Colab) generates NEW question forms
for the measured deficit cards (`artifacts/datasets/training-list-2026-10-14.md`,
`artifacts/reports/retry-safety-net-2026-10-14.md`,
`artifacts/reports/query-coverage-gaps-2026-10-14.md`). Part B re-uses the
existing 328 train rows; this file is Part A only.

Run: python artifacts/probes/gen-new-forms-2026-10-15.py
Writes data/finetune/new-forms-2026-10-15.json, a list of
{"question", "class", "source_card", "expect", "pin", "note"} with
expect in cited|refusal. Refusal rows carry pin: null (nothing to pin); a
cited row carries a chunk id, or "unverified" when no pin could be verified
for the card. Nothing here trains a model: the script calls the local Ollama
embedder through the shipped retrieval seam (retrieval preflight) and stubs
every generation call out (x2d.no_llm). No teacher, no `answer.respond`.

Helpers are IMPORTED from artifacts/probes/gen-x2d-forms-2026-10-14.py (it
imports cleanly through importlib: no top-level side effects, its main() is
behind an `if __name__ == "__main__"` guard, measured 0.10 s to import):
similarity / normalized / norm_tokens / no_llm / load_questions /
is_template_cluster / ITEMS (the sealed 21) / SEAL_TEMPLATE_TWINS /
VISIBLE_TEN / TEMPLATE_TOKENS. Thresholds and classes are x2d's: suite
near-match r>=0.8 or j>=0.6, bench near-match at the same bar, classes
bare|lower|flip|swap|greet|named|explain|restate|heading (swap/greet/heading
produce nothing new here) plus the new tags fragment, contraction,
possessive, punctuation, meaning-of, compound, casing, polite, shorthand,
statement. The sealed 21 are read from artifacts/datasets/sealed-forms.json
and cross-checked against the x2d ITEMS literal (abort on drift).

Guards, in check order (every candidate passes all of them):
1. duplicate-of-train: normalized equality against every question in every
   *train*.jsonl under data/finetune/ (meta.question + user-message
   "Question: " blocks).
2. near-suite: r>=0.8 or j>=0.6 vs the sealed 21 (raw and canonical forms on
   both sides; SEAL_TEMPLATE_TWINS logged, never trained).
3. near-bench: same bar vs bench question+asked; the x2d template-cluster
   (interrogative + "data" shared tokens) is logged and admitted, as in x2d.
4. near-visible-ten and near-probe-user-forms: r>=0.8 vs the ten trial
   queries and vs the 30 parsed items of probe-user-forms-2026-10-14.py.
5. in-book: cited candidates must have every content token present as a
   standalone word in data/index.json's chunk text (word-boundary regex over
   the collapsed lowercase text; digits are content here, so ddr4/ddr5 are
   checked, unlike keywords.words which drops digits); per-card tolerated
   tokens are declared and logged. Refusal candidates must show the opposite:
   at least one content token of the topic with no standalone occurrence in
   the index.
6. candidate dedupe: exact normalized duplicate -> reject; near-match at
   r>=0.8/j>=0.6 -> LOGGED, not rejected. Measured reason: the shipped
   data/finetune/x2d-forms-2026-10-14.json contains 64 near-twin pairs at
   these thresholds (bare/lower/explain/greet rows of the same card, e.g.
   'shared responsibility in the cloud' vs 'explain shared responsibility in
   the cloud' r=0.895) — per-class twins are the design, so rejecting them
   here would contradict x2d's shipped semantics. Deviation from the task's
   "same thresholds" wording, reported.
7. caps: core classes <=16/card, owner classes <=8/card (the task's
   "10-16 per card, cap 16" plus "4-8 new-class forms per card"), fragments
   <=20, refusals <=65.
8. retrieval preflight through answer.retrieval_context (generate_fn stubbed):
   strict pin (Location, the card whose pin x2d trained and measured at rank 1)
   rejects on miss; soft pins keep with a note. Fragments pin the passage the
   preflight actually returns (their note says so; no gold chunk exists).
   Refusals reject when the reading repair rewrites the ask (the capture would
   otherwise train a repaired question's behavior, not this one).

Cards, from training-list-2026-10-14.md + the user brief: Time Series
(ch05-045/046, the bare form is the sealed item itself and is rejected by
guard 2 — recorded, never trained), column-oriented vs row-oriented and
row-oriented vs column-oriented both directions (ch06-066/067, app01-008),
Location (ch07-046, strict; the exact strings 'Location' is a visible-ten
target and a train form, so no bare form is generated), DE Lifecycle
(ch02-002), ddr4 vs ddr5 (ch06-011 — the only DDR chunk; DDR4 never occurs in
the book, the card tolerates that one token and says so), lambda vs kappa
(ch03-086/088), auto scanning / automated scanning (ch06-082, shorthand
spellings). DDR4 absence is measured: 'ddr4' has 0 occurrences in
data/index.json, 'ddr5' occurs in ch06-011 ('Random Access Memory'). No pin
here is unverified; if one had been, the row would say "unverified" and never
a guessed id.

Refusal topics: the second-book contamination seeds (GPTQ, TurboQuant,
post-training quantization, lightning indexer, kv cache eviction) plus
invented everyday topics, none reusing the sealed controls
('the offside rule', 'violin strings', 'capital of France'); every accepted
row lists its decisive absent token in the note.

First run of this file (2026-10-15): 349 candidates generated -> 227 accepted
(162 cited, 65 refusal); 97 rejected by guards (near-suite 29,
near-probe-user-forms 16, duplicate-of-candidate 14, reading-repair-fires 12,
duplicate-of-train 9, near-bench 9, near-visible-ten 6, not-in-book 1,
pin-not-shown 1) + 25 cap skips; 265 distinct asks embedded, 0 retrieval
errors, 45 s.
"""

import importlib.util
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
from retrieve import INDEX, load_index

spec = importlib.util.spec_from_file_location(
    "gen_x2d", HERE / "gen-x2d-forms-2026-10-14.py"
)
x2d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(x2d)

OUT = ROOT / "data" / "finetune" / "new-forms-2026-10-15.json"
DATA = ROOT / "data" / "finetune"
SEALED_JSON = ROOT / "artifacts" / "datasets" / "sealed-forms.json"
PROBE_USER = ROOT / "artifacts" / "probes" / "probe-user-forms-2026-10-14.py"

similarity = x2d.similarity
normalized = x2d.normalized
norm_tokens = x2d.norm_tokens

MAX_CORE_PER_CARD = 16
MAX_OWNER_PER_CARD = 8
MAX_FRAGMENTS = 20
MAX_REFUSALS = 65
OWNER_CLASSES = frozenset((
    "contraction", "possessive", "punctuation", "meaning-of", "compound",
    "casing", "polite",
))

# ---------------------------------------------------------------------------
# Content tokens: digits are content (ddr4/ddr5), stopwords are not. The set is
# deliberately broad function words + politeness + question meta-words; every
# topic word (time, series, column, row, location, lifecycle, memory, ...)
# stays in.
# ---------------------------------------------------------------------------
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOP_TOKENS = frozenset("""
what whats how hows why whys when where which who whose
is are was were am do does did done can could should would will shall
has have had be been being not no yes
the a an of to in on at for and or but with about from by as into than then
that this these those there here it its it's i me my mine you your yours we
our us they them their he she his her
hey hi hello please pls thanks thank tell show give explain describe define
compare contrast list types kinds examples example difference different
mean means meaning meant purpose role used use uses using work works working
deal really actually matter matters important importance thing things stuff
vs versus say says like just so also more most much many any some
doin gonna wanna s t d ll re ve m
""".split())


def content_tokens(text):
    return [tok for tok in TOKEN_RE.findall((text or "").lower())
            if tok not in STOP_TOKENS]


# ---------------------------------------------------------------------------
# Sealed suite + cross-check.
# ---------------------------------------------------------------------------
def load_sealed():
    sealed = json.loads(SEALED_JSON.read_text(encoding="utf-8"))
    items = list(sealed["items"])
    x2d_items = [item for _cls, item, _expect, _note in x2d.ITEMS]
    if sorted(items) != sorted(x2d_items):
        raise SystemExit(
            "ABORT: sealed-forms.json and the x2d ITEMS literal disagree: "
            f"{sorted(items)} vs {sorted(x2d_items)}"
        )
    return items


def parse_probe_user_forms():
    """The 30 'q' strings of probe-user-forms-2026-10-14.py."""
    text = PROBE_USER.read_text(encoding="utf-8")
    found = []
    for raw in re.findall(r'"q":\s*"((?:[^"\\]|\\.)*)"', text):
        found.append(json.loads(f'"{raw}"'))
    return found


# ---------------------------------------------------------------------------
# The dedupe pools: every train and bench jsonl under data/finetune/.
# ---------------------------------------------------------------------------
def question_forms(path):
    """Every question-shaped string a finetune row carries."""
    forms = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        meta = row.get("meta") or {}
        for key in ("question", "asked"):
            if isinstance(meta.get(key), str):
                forms.append(meta[key])
        for key in ("question", "asked", "q"):
            if isinstance(row.get(key), str):
                forms.append(row[key])
        for message in row.get("messages") or []:
            if message.get("role") != "user":
                continue
            block = message.get("content") or ""
            if block.startswith("Question: "):
                forms.append(block.split("\n", 1)[0][len("Question: "):])
    return forms


def load_dedupe_pools():
    train = {}
    bench = {}
    used = []
    for path in sorted(DATA.glob("*.jsonl")):
        name = path.name
        if "train" in name:
            bucket, label = train, "train"
        elif "bench" in name:
            bucket, label = bench, "bench"
        else:
            continue  # probe/mining scratch is out of the guard spec
        forms = question_forms(path)
        for form in forms:
            bucket.setdefault(normalized(form), set()).add(name)
        used.append((name, label, len(forms)))
    return train, bench, used


# ---------------------------------------------------------------------------
# The cards. `forms` are (class, question) in acceptance order. `topic` is the
# in-book probe string for the card report; `tolerate` lists content tokens the
# card deliberately allows to be out-of-book (declared, logged).
# ---------------------------------------------------------------------------
CARDS = [
    {
        "key": "time-series",
        "source_card": "Time Series",
        "pins": ("ch05-045", "ch05-046"),
        "pin_mode": "soft",
        "tolerate": frozenset(),
        "topic": "time series",
        "forms": [
            ("bare", "Time Series"),          # sealed item itself -> guard 2
            ("lower", "time series"),         # normalized == sealed item
            ("named", "what is time series"),
            ("named", "what is a time series"),
            ("restate", "what are time series"),
            ("bare", "time series data"),
            ("named", "what does time series mean"),
            ("bare", "time series databases"),
            ("named", "what is the purpose of time series data"),
            ("explain", "explain time series"),
            ("contraction", "what's a time series?"),
            ("contraction", "what's the deal with time series"),
            ("possessive", "time series data's purpose"),
            ("punctuation", "time series???"),
            ("punctuation", "time series..."),
            ("punctuation", "what is time series,"),
            ("meaning-of", "meaning of time series"),
            ("meaning-of", "time series means what"),
            ("compound", "what is a time series and how is it used"),
            ("casing", "TIME SERIES"),
            ("casing", "Time series"),
            ("polite", "hey can you tell me what a time series is"),
            ("polite", "could you explain time series"),
            ("named", "why are time series useful"),
            # seal-clear extensions (the sealed item's two content tokens must
            # be diluted by >=2 further content tokens to stay under j<0.6)
            ("named", "how are time series data stored in a database"),
            ("named", "what is the difference between time series and "
                       "event streams"),
            ("bare", "time series forecasting models"),
            ("bare", "time series data modeling"),
            ("contraction", "what's the deal with time series forecasting "
                            "models"),
            ("meaning-of", "meaning of time series data modeling"),
            ("polite", "could you explain how time series data is stored"),
            ("named", "how is time series analysis used in forecasting"),
            ("named", "what is the definition of time series data"),
            ("explain", "explain time series data"),
            ("restate", "what are time series databases"),
            ("named", "why do time series need regular timestamps"),
            ("bare", "time series analysis and forecasting"),
        ],
    },
    {
        "key": "column-first",
        "source_card": "column-oriented vs row-oriented",
        "pins": ("ch06-066", "ch06-067", "app01-008"),
        "pin_mode": "soft",
        "tolerate": frozenset(),
        "topic": "column-oriented row-oriented columnar",
        "forms": [
            ("bare", "column-oriented vs row-oriented"),   # sealed item
            ("named", "what is column-oriented storage"),
            ("named", "what is a columnar database"),
            ("named", "what is the difference between column-oriented and "
                      "row-oriented storage"),
            ("restate", "what are column-oriented databases"),
            ("explain", "explain column-oriented databases"),
            ("named", "how do column-oriented databases store data"),
            ("bare", "columnar vs row-oriented storage"),
            ("bare", "columnar serialization"),
            ("contraction", "what's the deal with column-oriented databases"),
            ("contraction", "how's column-oriented storage used"),
            ("possessive", "column-oriented storage's purpose"),
            ("punctuation", "column-oriented???"),
            ("punctuation", "column-oriented storage..."),
            ("meaning-of", "meaning of column-oriented storage"),
            ("meaning-of", "column-oriented means what"),
            ("compound", "what is column-oriented storage and how is it used"),
            ("casing", "COLUMNAR DATABASES"),
            ("casing", "column-oriented storage"),
            ("polite", "hey can you tell me about columnar databases"),
            ("named", "why are column-oriented databases faster"),
            ("bare", "row vs column storage"),
            ("named", "how does column-oriented storage differ from "
                       "row-oriented storage"),
            ("bare", "columnar storage format"),
            ("named", "what is a columnar data format"),
        ],
    },
    {
        "key": "row-first",
        "source_card": "row-oriented vs column-oriented",
        "pins": ("ch06-066", "ch06-067", "app01-008"),
        "pin_mode": "soft",
        "tolerate": frozenset(),
        "topic": "row-oriented column-oriented",
        "forms": [
            ("bare", "row-oriented vs column-oriented"),   # sealed item
            ("named", "what is row-oriented storage"),
            ("named", "what is a row-oriented database"),
            ("restate", "what are row-oriented databases"),
            ("explain", "explain row-oriented storage"),
            ("named", "how do row-oriented databases store data"),
            ("bare", "row-oriented serialization"),
            ("named", "what is the difference between row-oriented and "
                      "columnar serialization"),
            ("contraction", "what's the deal with row-oriented databases"),
            ("contraction", "how's row-oriented storage used"),
            ("possessive", "row-oriented storage's purpose"),
            ("punctuation", "row-oriented???"),
            ("punctuation", "row-oriented databases..."),
            ("meaning-of", "meaning of row-oriented storage"),
            ("meaning-of", "row-oriented means what"),
            ("compound", "what is row-oriented storage and how is it used"),
            ("casing", "ROW-ORIENTED DATABASES"),
            ("casing", "row-oriented storage"),
            ("polite", "hey can you tell me about row-oriented databases"),
            ("named", "why are row-oriented databases slower"),
            ("bare", "serializing row by row"),
            ("named", "how does row-oriented storage differ from "
                       "column-oriented storage"),
            ("bare", "row-based storage"),
            ("named", "what is a row-based data format"),
        ],
    },
    {
        "key": "location",
        "source_card": "Location",
        "pins": ("ch07-046",),
        "pin_mode": "strict",
        "tolerate": frozenset(),
        "topic": "location",
        "forms": [
            ("named", "what is location"),
            ("named", "what is a location"),
            ("named", "why is location important"),
            ("named", "how is location used"),
            ("named", "why does location matter"),
            ("bare", "location"),                 # visible-ten target string
            ("contraction", "what's location"),
            ("contraction", "what's the deal with location"),
            ("possessive", "location's role"),
            ("possessive", "location's importance"),
            ("punctuation", "location???"),
            ("punctuation", "location..."),
            ("meaning-of", "meaning of location"),
            ("meaning-of", "location means what"),
            ("compound", "what is location and why does it matter"),
            ("casing", "LOCATION"),
            ("polite", "hey can you tell me about location"),
            ("explain", "explain location"),
            ("bare", "data location"),
            ("bare", "locations"),
            ("named", "why does location matter for streaming data"),
            ("named", "how does location affect data architecture"),
            ("explain", "explain why location matters for streaming"),
        ],
    },
    {
        "key": "de-lifecycle",
        "source_card": "DE Lifecycle",
        "pins": ("ch02-002",),
        "pin_mode": "soft",
        "tolerate": frozenset(),
        "topic": "data engineering lifecycle",
        "forms": [
            ("bare", "DE lifecycle"),             # visible-ten target string
            ("bare", "data engineering lifecycle"),  # already a train row
            ("named", "what is DE lifecycle"),
            ("named", "what is the DE lifecycle"),
            ("named", "what is the data engineering lifecycle"),
            ("named", "what are the stages of the data engineering lifecycle"),
            ("named", "how does the data engineering lifecycle work"),
            ("named", "why does the data engineering lifecycle matter"),
            ("named", "what does the data engineering lifecycle consist of"),
            ("contraction", "what's the deal with the DE lifecycle"),
            ("contraction", "what's the DE lifecycle"),
            ("possessive", "the DE lifecycle's purpose"),
            ("possessive", "the data engineering lifecycle's stages"),
            ("punctuation", "the DE lifecycle..."),
            ("meaning-of", "meaning of DE lifecycle"),
            ("compound", "what is the DE lifecycle and how is it used"),
            ("casing", "Data Engineering Lifecycle"),  # train row normalized
            ("polite", "hey can you tell me about the DE lifecycle"),
            ("explain", "explain the DE lifecycle"),
            ("bare", "undercurrents of the data engineering lifecycle"),
            ("named", "how do the stages of the data engineering lifecycle fit "
                       "together"),
            ("explain", "explain the data engineering lifecycle stages"),
            ("restate", "what are the data engineering lifecycle stages"),
        ],
    },
    {
        "key": "ddr4-vs-ddr5",
        "source_card": "ddr4 vs ddr5",
        "pins": ("ch06-011",),
        "pin_mode": "soft",
        "tolerate": frozenset(("ddr4",)),
        "topic": "ddr5 ram memory",
        "forms": [
            ("bare", "ddr4 vs ddr5"),             # visible-ten target string
            ("flip", "ddr5 vs ddr4"),             # visible-ten target string
            ("named", "what is the difference between ddr4 and ddr5"),
            ("named", "why is ddr5 faster than ddr4"),
            ("named", "is ddr5 better than ddr4"),
            ("bare", "ddr5"),
            ("bare", "ddr5 memory"),
            ("named", "what is ddr5 memory"),
            ("named", "what is ddr5 latency"),
            ("named", "speed of ddr5"),           # visible-ten target string
            ("bare", "ddr4"),
            ("bare", "ddr4 memory"),
            ("contraction", "what's ddr5"),
            ("contraction", "what's the deal with ddr5 memory"),
            ("possessive", "ddr5's role in ram"),
            ("punctuation", "ddr5???"),
            ("punctuation", "ddr5 memory..."),
            ("meaning-of", "meaning of ddr5"),
            ("compound", "what is ddr5 and why does it matter"),
            ("casing", "DDR5"),
            ("polite", "hey can you tell me what ddr5 is"),
            ("explain", "explain ddr5 memory"),
            ("named", "how much faster is ddr5 than ddr4"),
            ("named", "what is ddr5 bandwidth"),
            ("bare", "ddr5 speed"),
        ],
    },
    {
        "key": "lambda-vs-kappa",
        "source_card": "lambda vs kappa",
        "pins": ("ch03-086", "ch03-088"),
        "pin_mode": "soft",
        "tolerate": frozenset(),
        "topic": "lambda kappa architecture",
        "forms": [
            ("bare", "lambda vs kappa"),          # probe-user-forms item
            ("flip", "kappa vs lambda"),          # permutation of the item
            ("named", "what is lambda architecture"),
            ("named", "what is kappa architecture"),
            ("named", "what is the difference between lambda and kappa "
                      "architectures"),
            ("named", "how does lambda architecture differ from kappa "
                      "architecture"),
            ("named", "why was kappa architecture proposed"),
            ("named", "when should you use lambda vs kappa architecture"),
            ("bare", "lambda and kappa architectures"),
            ("bare", "lambda architecture"),
            ("bare", "kappa architecture"),
            ("contraction", "what's lambda architecture"),
            ("contraction", "what's the difference between lambda and kappa"),
            ("possessive", "lambda architecture's purpose"),
            ("possessive", "kappa architecture's role"),
            ("punctuation", "lambda architecture???"),
            ("meaning-of", "meaning of lambda architecture"),
            ("compound", "what is lambda architecture and how is it used"),
            ("casing", "KAPPA ARCHITECTURE"),
            ("polite", "hey can you tell me about lambda architecture"),
            ("explain", "explain the kappa architecture"),
            ("named", "why does kappa architecture replace batch and "
                       "streaming pipelines"),
            ("named", "what is the difference between lambda and kappa in "
                       "streaming"),
            ("bare", "unified batch and streaming"),
        ],
    },
    {
        "key": "auto-scanning",
        "source_card": "auto scanning",
        "pins": ("ch06-082",),
        "pin_mode": "soft",
        "tolerate": frozenset(("autoscanning",)),
        "topic": "automated scanning",
        "forms": [
            ("bare", "auto scanning"),
            ("contraction", "what's auto scanning?"),
            ("shorthand", "autoscanning"),
            ("shorthand", "auto-scanning"),
            ("named", "what is auto scanning"),
            ("bare", "automated scanning"),
            ("named", "what is automated scanning"),
            ("named", "what does automated scanning do"),
            ("named", "how does automated scanning work"),
            ("named", "why is automated scanning needed"),
            ("named", "what is automated scanning in a data catalog"),
            ("bare", "auto scanning layer"),
            ("contraction", "what's the deal with automated scanning"),
            ("possessive", "automated scanning's purpose"),
            ("punctuation", "automated scanning???"),
            ("meaning-of", "meaning of automated scanning"),
            ("compound", "what is automated scanning and how does it work"),
            ("casing", "AUTOMATED SCANNING"),
            ("polite", "hey can you tell me about automated scanning"),
            ("explain", "explain automated scanning"),
            ("named", "how does auto scanning work"),
            ("bare", "auto scan"),
            ("named", "what is the automated scanning layer"),
        ],
    },
]
# (the two scanning source_card labels share one card cap: the brief lists
# 'auto scanning / automated scanning' as one card)

# ---------------------------------------------------------------------------
# Fragment shapes: short/incomplete questions that are not near-matches of the
# sealed four ('how do', 'what about', 'explain', 'why does'). Guard 2 decides;
# 'how does' and 'what is' are generated so the rejection is on the record.
# ---------------------------------------------------------------------------
FRAGMENTS = [
    "how does",
    "what is",
    "why is",
    "how to",
    "why not",
    "how so",
    "and why",
    "how",
    "why",
    "what for",
    "how about",
    "so what",
    "what else",
    "how come",
    "why though",
    "what now",
    "how long",
    "how much",
    "why is that",
    "how is it used",
    "is it",
    "does it",
    "how does it work",
    "why does it matter",
    "how does that work",
    "tell me more",
    "and how",
    "so how",
    "explain that",
    "what is that",
    "how far",
    "how big",
]

# ---------------------------------------------------------------------------
# Refusal topics: second-book contamination seeds + invented off-book topics.
# Every row's note names the decisive token with no standalone occurrence in
# the index. None of the sealed controls is reused.
# ---------------------------------------------------------------------------
REFUSALS = [
    # contamination seeds (the second book's quantization/attention world)
    ("named", "what is GPTQ"),
    ("bare", "GPTQ"),
    ("contraction", "what's GPTQ?"),
    ("punctuation", "GPTQ???"),
    ("meaning-of", "meaning of GPTQ"),
    ("compound", "what is GPTQ and how is it used"),
    ("polite", "hey can you tell me what GPTQ is"),
    ("statement", "GPTQ quantizes model weights after training."),
    ("casing", "gptq"),
    ("named", "what is TurboQuant"),
    ("bare", "TurboQuant"),
    ("contraction", "what's TurboQuant?"),
    ("punctuation", "TurboQuant..."),
    ("statement", "TurboQuant speeds up long-context inference."),
    ("named", "what is post-training quantization"),
    ("bare", "post-training quantization"),
    ("meaning-of", "meaning of post-training quantization"),
    ("statement", "post-training quantization shrinks model weights."),
    ("named", "what is a lightning indexer"),
    ("bare", "lightning indexer"),
    ("contraction", "what's a lightning indexer"),
    ("statement", "the lightning indexer selects the top tokens."),
    ("named", "what is kv cache eviction"),
    ("bare", "kv cache eviction"),
    # class-variety extensions, ahead of the long named tail (the cap keeps the
    # head of this list, so the mix has to live here)
    ("statement", "Photosynthesis converts sunlight into chemical energy."),
    ("statement", "A Roth IRA grows tax-free."),
    ("statement", "Sourdough bread rises without commercial yeast."),
    ("statement", "A haiku has seventeen syllables."),
    ("statement", "The guillotine was used during the French Revolution."),
    ("statement", "Castling moves the king and the rook at once."),
    ("bare", "photosynthesis"),
    ("bare", "habeas corpus"),
    ("bare", "sourdough starter"),
    ("punctuation", "photosynthesis???"),
    ("punctuation", "sourdough starter."),
    ("punctuation", "habeas corpus..."),
    ("casing", "SOURDOUGH"),
    ("casing", "HAIKU"),
    ("contraction", "what's photosynthesis?"),
    ("contraction", "what's the deal with sourdough"),
    ("contraction", "what's castling?"),
    ("meaning-of", "photosynthesis means what"),
    ("meaning-of", "meaning of habeas corpus"),
    ("possessive", "GPTQ's purpose"),
    ("possessive", "a sourdough starter's role"),
    ("polite", "hey can you tell me what castling is"),
    ("polite", "hey can you tell me about photosynthesis"),
    ("compound", "what is a haiku and how is it structured"),
    # invented everyday off-book topics
    ("named", "how do you bake sourdough bread"),
    ("named", "what is a sourdough starter"),
    ("bare", "sourdough"),
    ("polite", "hey can you tell me what sourdough is"),
    ("named", "what is photosynthesis"),
    ("named", "how does photosynthesis work"),
    ("casing", "PHOTOSYNTHESIS"),
    ("named", "what is habeas corpus"),
    ("named", "how does habeas corpus work"),
    ("named", "what is a Roth IRA"),
    ("named", "how does a Roth IRA work"),
    ("named", "what is a pentatonic scale"),
    ("named", "how do you play a pentatonic scale"),
    ("named", "how do you caramelize onions"),
    ("named", "what is a bain-marie"),
    ("meaning-of", "bain marie means what"),
    ("named", "how does a hurricane form"),
    ("statement", "hurricanes form over warm ocean water."),
    ("named", "what are tannins in red wine"),
    ("named", "why do tannins make your mouth dry"),
    ("punctuation", "tannins???"),
    ("named", "how tall is Mount Everest"),
    ("punctuation", "everest..."),
    ("named", "how does castling work in chess"),
    ("named", "what is castling in chess"),
    ("named", "how do you crochet a granny square"),
    ("named", "how many keys does a piano have"),
    ("named", "what is a googly in cricket"),
    ("named", "what is a haiku"),
    ("named", "how many syllables does a haiku have"),
    ("contraction", "what's a haiku"),
    ("named", "how do you play a saxophone"),
    ("named", "how do you build an igloo"),
    ("named", "how do you make latte art"),
    ("named", "what is the boiling point of krypton"),
    ("named", "how do you train a parrot to talk"),
    ("named", "what is a hieroglyph"),
    ("named", "what is the capital of Brazil"),
    ("punctuation", "what is the capital of Brazil,"),
    ("named", "how do you fold a fitted sheet"),
    ("named", "what is a guillotine"),
    ("named", "how do you prune a rose bush"),
    ("named", "what is a sommelier"),
    ("named", "how do you solve a Rubik's cube"),
    ("named", "what is a tarantula"),
    ("compound", "what is a tarantula and is it dangerous"),
    ("named", "how do you tune a ukulele"),
    ("named", "what is the pH scale"),
    ("named", "how do you change a car tyre"),
    ("named", "what is a macaron"),
    ("named", "how do you compost kitchen scraps"),
    ("named", "what is a truffle"),
    ("named", "how do you make a margherita pizza"),
    ("named", "how do you say thank you in Italian"),
    ("named", "what is a fjord"),
    ("named", "how do you play the bagpipes"),
    ("named", "what is a didgeridoo"),
    ("named", "what is a nebula"),
    ("named", "how do you solve a sudoku"),
    ("named", "what is a velodrome"),
    ("named", "how do you brew kombucha"),
    ("named", "what is a limerick"),
    ("named", "how do you play mahjong"),
    ("contraction", "what's a sourdough starter?"),
    ("casing", "TURBOQUANT"),
]


def main():
    started = time.monotonic()
    index = load_index(INDEX)
    chunk_ids = {chunk["chunk_id"] for chunk in index["chunks"]}
    heading_by_id = {chunk["chunk_id"]: (chunk.get("heading") or "").strip()
                     for chunk in index["chunks"]}
    big = " ".join((chunk.get("text") or "") for chunk in index["chunks"]).lower()
    big = re.sub(r"\s+", " ", big)

    sealed = load_sealed()
    probe_user = parse_probe_user_forms()
    train_pool, bench_pool, files_used = load_dedupe_pools()
    print(f"index: {INDEX.name} chunks={len(index['chunks'])}")
    print(f"guard sources: sealed {len(sealed)} | visible-ten "
          f"{len(x2d.VISIBLE_TEN)} | probe-user-forms {len(probe_user)}")
    for name, label, count in files_used:
        print(f"  dedupe file [{label}] {name} forms={count}")
    print(f"train normalized keys: {len(train_pool)}  "
          f"bench normalized keys: {len(bench_pool)}")

    presence_cache = {}

    def present(token):
        if token not in presence_cache:
            presence_cache[token] = re.search(
                r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", big
            ) is not None
        return presence_cache[token]

    ctx_cache = {}
    retrieval_errors = 0

    def get_ctx(asked):
        nonlocal retrieval_errors
        if asked not in ctx_cache:
            try:
                ctx_cache[asked] = A.retrieval_context(
                    index, asked, generate_fn=x2d.no_llm)
            except Exception as exc:
                retrieval_errors += 1
                print(f"  retrieval error for {asked!r}: "
                      f"{type(exc).__name__}: {exc}")
                ctx_cache[asked] = None
        return ctx_cache[asked]

    bench_forms = sorted(bench_pool)
    accepted = []
    accepted_norm = {}
    cap_counts = Counter()
    cap_skips = []
    rejects = []
    near_candidate_notes = []
    twin_notes = []
    cluster_notes = []
    repair_notes = []
    soft_pin_notes = []
    worst_suite, worst_bench, worst_visible, worst_probe = [], [], [], []

    def note_reject(cand, reason, detail=""):
        rejects.append({"question": cand["question"], "class": cand["class"],
                        "reason": reason, "detail": str(detail)[:220]})

    def run_checks(cand):
        """(reason, detail) or (None, None); fills cand['note_parts']."""
        question = cand["question"]
        class_name = cand["class"]
        expect = cand["expect"]
        card = cand["card"]
        norm = normalized(question)
        canon = A.canonical_query(question)
        forms = {question, canon}
        parts = []

        best = (0.0, 0.0, None, None)
        for item in sealed:
            for form in forms:
                for item_form in {item, A.canonical_query(item)}:
                    r, j = similarity(form, item_form)
                    if r > best[0]:
                        best = (r, j, item_form, form)
        worst_suite.append((best[0], best[1], question, best[2], best[3]))

        best_bench = (0.0, 0.0, None, None)
        for bench_form in bench_forms:
            for form in forms:
                r, j = similarity(form, bench_form)
                if r > best_bench[0]:
                    best_bench = (r, j, bench_form, form)
        worst_bench.append((best_bench[0], best_bench[1], question,
                            best_bench[2], best_bench[3]))

        for visible in x2d.VISIBLE_TEN:
            r, j = similarity(question, visible)
            if r > 0.5 or j > 0.5:
                worst_visible.append((round(r, 3), round(j, 3), question,
                                      visible))
        for probe_q in probe_user:
            r, j = similarity(question, probe_q)
            if r > 0.5 or j > 0.5:
                worst_probe.append((round(r, 3), round(j, 3), question,
                                    probe_q))

        # 1. exact duplicate of any train row
        if norm in train_pool:
            return ("duplicate-of-train", ",".join(sorted(train_pool[norm])))

        # 2. sealed suite near-match
        for item in sealed:
            for form in forms:
                for item_form in {item, A.canonical_query(item)}:
                    r, j = similarity(form, item_form)
                    if r >= 0.8 or j >= 0.6:
                        if (item, form) in x2d.SEAL_TEMPLATE_TWINS:
                            twin_notes.append((question, item, form,
                                               round(r, 3), round(j, 3)))
                            continue
                        return ("near-suite",
                                f"{item!r} vs {form!r} r={r:.3f} j={j:.3f}")

        # 3. bench near-match (template cluster admitted, as in x2d)
        for bench_form in bench_forms:
            for form in forms:
                r, j = similarity(form, bench_form)
                if r >= 0.8 or j >= 0.6:
                    if x2d.is_template_cluster(form, bench_form):
                        cluster_notes.append((question, bench_form,
                                              round(r, 3), round(j, 3)))
                        continue
                    return ("near-bench",
                            f"{bench_form!r} vs {form!r} r={r:.3f} j={j:.3f}")

        # 4. visible-ten / probe-user-forms near-match
        for visible in x2d.VISIBLE_TEN:
            for form in forms:
                r, _j = similarity(form, visible)
                if r >= 0.8:
                    return ("near-visible-ten",
                            f"{visible!r} vs {form!r} r={r:.3f}")
        for probe_q in probe_user:
            for form in forms:
                r, _j = similarity(form, probe_q)
                if r >= 0.8:
                    return ("near-probe-user-forms",
                            f"{probe_q!r} vs {form!r} r={r:.3f}")

        # 5. in-book / absent-topic check
        tokens = content_tokens(question)
        if expect == "cited":
            missing = [tok for tok in tokens if not present(tok)]
            hard = [tok for tok in missing
                    if tok not in (card["tolerate"] if card else ())]
            if hard:
                return "not-in-book", missing
            if missing:
                parts.append("tolerated out-of-book token(s): "
                             + ",".join(missing))
            if card is not None and card["tolerate"]:
                parts.append("card tolerates: "
                             + ",".join(sorted(card["tolerate"])))
        else:
            decisive = [tok for tok in tokens if not present(tok)]
            if not decisive:
                return "topic-present-in-index", ",".join(tokens)
            parts.append(f"absent token(s): {','.join(decisive[:3])}")

        # 6. candidate dedupe: exact reject, near-match logged
        if norm in accepted_norm:
            return "duplicate-of-candidate", accepted_norm[norm]
        for other in accepted:
            r, j = similarity(question, other["question"])
            if r >= 0.8 or j >= 0.6:
                near_candidate_notes.append(
                    (round(r, 3), round(j, 3), question, other["question"]))

        # 7. retrieval preflight
        asked = canon
        ctx = get_ctx(asked)
        passages = ctx["passages"] if ctx else []
        if not passages:
            return "no-passages", ""
        if ctx["asked"] != asked:
            if expect == "refusal":
                return "reading-repair-fires", ctx["asked"]
            repair_notes.append((question, ctx["asked"]))
            parts.append(f"reading repair: asked as {ctx['asked']!r}")
        shown = [hit["chunk_id"] for hit in passages]
        if expect == "refusal":
            cand["pin_out"] = None
        elif card is None:                      # fragment: pin the top passage
            cand["pin_out"] = shown[0]
            parts.append(f"fragment: pin = preflight top passage "
                         f"({heading_by_id.get(shown[0], '?')})")
        else:
            pins = card["pins"]
            hit = next((pin for pin in pins if pin in shown), None)
            if hit is None:
                if card["pin_mode"] == "strict":
                    return "pin-not-shown", f"{pins[0]} not in {shown[:5]}"
                soft_pin_notes.append((question, pins[0], shown[:5]))
                parts.append(f"soft pin miss: {pins[0]} not in {shown[:5]}")
            cand["pin_out"] = hit or pins[0]
            card.setdefault("_pins_shown", set()).update(set(pins) & set(shown))
            if hit is not None:
                parts.append(f"pin {hit} in top-5")
            if canon != question:
                parts.append(f"asked as: {canon!r}")

        cand["note_parts"] = parts
        return None, None

    def cap_bucket(cand):
        """(cap key, limit) for a candidate."""
        if cand["expect"] == "refusal":
            return "refusal", MAX_REFUSALS
        if cand["card"] is None:
            return "fragment", MAX_FRAGMENTS
        limit = (MAX_OWNER_PER_CARD if cand["class"] in OWNER_CLASSES
                 else MAX_CORE_PER_CARD)
        return f"{cand['card']['key']}:{'owner' if cand['class'] in OWNER_CLASSES else 'core'}", limit

    def check_and_accept(cand):
        reason, detail = run_checks(cand)
        if reason is not None:
            note_reject(cand, reason, detail)
            return False
        key, limit = cap_bucket(cand)
        if cap_counts[key] >= limit:
            cap_skips.append({"question": cand["question"],
                              "class": cand["class"],
                              "reason": f"over-cap {key} "
                                        f"{cap_counts[key]}>={limit}"})
            return False
        accepted.append({
            "question": cand["question"],
            "class": cand["class"],
            "source_card": cand["source_card"],
            "expect": cand["expect"],
            "pin": cand.get("pin_out"),
            "note": "; ".join(cand.get("note_parts") or []),
        })
        cap_counts[key] += 1
        accepted_norm[normalized(cand["question"])] = cand["question"]
        return True

    # order: cards, fragments, refusals
    candidates = []
    for card in CARDS:
        for class_name, question in card["forms"]:
            label = card["source_card"]
            if card["key"] == "auto-scanning" and "automated" in question.lower():
                label = "automated scanning"
            candidates.append({
                "question": question, "class": class_name, "card": card,
                "source_card": label, "expect": "cited",
            })
    for question in FRAGMENTS:
        candidates.append({
            "question": question, "class": "fragment", "card": None,
            "source_card": "fragment-shape", "expect": "cited",
        })
    for class_name, question in REFUSALS:
        candidates.append({
            "question": question, "class": class_name, "card": None,
            "source_card": f"refusal:{' '.join(content_tokens(question)[:2])}",
            "expect": "refusal",
        })

    for cand in candidates:
        check_and_accept(cand)

    rows = [{k: v for k, v in row.items() if k != "_key"} for row in accepted]
    OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")

    by_expect = Counter(row["expect"] for row in rows)
    by_class = Counter(f"{row['expect']}/{row['class']}" for row in rows)
    by_card = Counter(row["source_card"] for row in rows)
    rej_by_reason = Counter(rej["reason"].split(":")[0] for rej in rejects)

    print()
    print("================ summary ================")
    print(f"generated candidates: {len(candidates)}  "
          f"(cards {sum(len(c['forms']) for c in CARDS)}, fragments "
          f"{len(FRAGMENTS)}, refusals {len(REFUSALS)})")
    print(f"accepted: {len(rows)}  by expect: {dict(sorted(by_expect.items()))}")
    print(f"rejected: {len(rejects)}  cap skips: {len(cap_skips)}")
    print(f"by expect/class: {dict(sorted(by_class.items()))}")
    print(f"accepted by source_card: {dict(sorted(by_card.items()))}")
    print(f"rejections by guard: {dict(sorted(rej_by_reason.items()))}")
    print(f"cap counts (accepted per cap bucket): "
          f"{dict(sorted(cap_counts.items()))}")
    print(f"retrieval errors: {retrieval_errors}  ctx cache: {len(ctx_cache)}")
    print(f"reading repairs (cited, kept with note): {len(repair_notes)}")
    for q, reading in repair_notes[:10]:
        print(f"  repair {q!r} -> {reading!r}")
    print(f"soft pin misses (kept with note): {len(soft_pin_notes)}")
    for q, pin, shown in soft_pin_notes[:12]:
        print(f"  soft-miss {q!r} pin={pin} top={shown}")
    print(f"seal template twins logged: {len(twin_notes)}  {twin_notes}")
    print(f"bench template-cluster admits (logged): {len(cluster_notes)}")
    for q, bf, r, j in cluster_notes[:10]:
        print(f"  cluster-admit {q!r} vs {bf!r} r={r} j={j}")
    print(f"near-candidate pairs at 0.8/0.6 (report only, x2d semantics): "
          f"{len(near_candidate_notes)}")
    for r, j, a, b in sorted(near_candidate_notes, reverse=True)[:12]:
        print(f"  near-candidate r={r} j={j} {a!r} vs {b!r}")

    def worst_of(rows_, n=8):
        return sorted(rows_, key=lambda row: (-row[0], -row[1]))[:n]

    print("worst suite similarities seen (r, j, candidate, item, form):")
    for r, j, q, item, form in worst_of(worst_suite):
        print(f"  r={r:.3f} j={j:.3f} {q!r} vs {item!r} (as {form!r})")
    print("worst bench similarities seen:")
    for r, j, q, bench_form, form in worst_of(worst_bench):
        print(f"  r={r:.3f} j={j:.3f} {q!r} vs {bench_form!r} (as {form!r})")
    print(f"visible-ten hits >0.5 (report only): {len(worst_visible)}")
    for r, j, q, visible in sorted(worst_visible, reverse=True)[:10]:
        print(f"  r={r} j={j} {q!r} vs {visible!r}")
    print(f"probe-user-forms hits >0.5 (report only): {len(worst_probe)}")
    for r, j, q, probe_q in sorted(worst_probe, reverse=True)[:10]:
        print(f"  r={r} j={j} {q!r} vs {probe_q!r}")

    print("in-book probe per card:")
    for card in CARDS:
        tokens = content_tokens(card["topic"])
        missing = [tok for tok in tokens if not present(tok)]
        print(f"  {card['source_card']}: topic {card['topic']!r} "
              f"tokens={tokens} absent={missing or 'none'} "
              f"tolerate={sorted(card['tolerate']) or 'none'} "
              f"pins={list(card['pins'])} pin_mode={card['pin_mode']}")
        unresolved = set(card["pins"]) - (card.get("_pins_shown") or set())
        if unresolved:
            print(f"    pins never shown in any accepted preflight: "
                  f"{sorted(unresolved)}")

    print("cap skips (detail):")
    for item in cap_skips:
        print(f"  [{item['class']}] {item['question']!r} {item['reason']}")
    print("rejects (detail):")
    for item in rejects:
        print(f"  [{item['class']}] {item['question']!r} "
              f"{item['reason']} {item['detail']}")
    print("accepted forms:")
    for row in rows:
        print(f"  [{row['expect']}/{row['class']:11s}] {row['question']!r} "
              f"pin={row['pin']} card={row['source_card']!r} note={row['note']}")
    print(f"\nwrote {OUT}  ({len(rows)} entries)  "
          f"runtime {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
