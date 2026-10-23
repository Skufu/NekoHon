"""new-forms generator v2 2026-10-15: rebalanced Part A candidates.

v1 (`gen-new-forms-2026-10-15.py`) produced 227 guarded forms; an external
review measured that 120+ of them concentrate on 7 book passages (the deficit
cards' long named tails) and that the measured teacher-ceiling classes
(contractions, causal shapes) are absent. This v2 keeps v1's guards and row
schema, cuts the deficit cards hard, and spends the freed budget on the two
classes that teach query shapes instead of chunk->quote mappings:

1. Deficit cards: the 8 cards now accept **max 3 forms each** and only forms
   whose retrieval preflight actually shows a gold chunk (strict pin for every
   card; the column/row pair's gold set is ch06-066 or app01-008 only, as
   specified). The v1 form lists stay as the candidate pool; the first three
   passing forms per card are the v2 pick (ordered for shape diversity across
   named / explain / contraction / possessive / meaning-of / bare / shorthand).
2. Bare topics: one bare noun-phrase (class `bare`) per distinct book topic,
   drawn from the book's own section headings in data/index.json (Data Catalog,
   Data Lineage, Data Governance, Data Quality, Schema Evolution, Serialization,
   ...). Each accepted bare must retrieve a top-5 passage whose text carries
   every topic token; that passage becomes the pin. Sealed bare topics
   (Time Series / File Formats / Micro-Batch / Streaming / Event Streams) and
   their near-twins die in guard 2.
3. Order-flipped pairs: both directions of in-book comparisons that are not
   sealed (batch/streaming, column/row) and not already trained. Pairs come
   from the book's own "X Versus Y" headings (Eventual Versus Strong
   Consistency, Monolith Versus Modular, Serverless Versus Servers, ...). Each
   direction must retrieve a top-5 passage carrying both sides' tokens.
4. Causal class: topicful causal shapes (`why does X matter`,
   `why do data engineers care about X`, `why is X important`, `how come X`,
   `what makes X important`) across diverse chapters + the three safe bare
   causals (`how come`, `why though`, `and why`). These measure whether the
   new teacher class is teachable; the local build decides later. All pass
   every guard: none is within 0.8 difflib of the sealed `why does` (measured
   worst r=0.556) and none touches the probed `why's kafka so popular?` /
   `why is kafka so popular?`.
5. Fragments (~20) and refusals (~65) are the v1 selections minus the three
   bare causals (moved to bucket 4); the fragment cap back-fills from the cut
   candidates. Refusals are unchanged and the cap keeps them only if the total
   stays under budget.

Guards are IDENTICAL to v1 (same code, same order): 1. duplicate-of-train vs
every *train*.jsonl question; 2. near-suite (r>=0.8 or j>=0.6 vs the sealed
21, raw + canonical both sides); 3. near-bench at the same bar (template
cluster admitted, logged); 4. near-visible-ten and near-probe-user-forms at
r>=0.8; 5. in-book for cited / absent-token for refusal; 6. candidate dedupe
(exact reject, near-twin logged per x2d semantics); 7. retrieval preflight
(generate_fn stubbed) with pins. The only new mechanics are the per-bucket
caps and the pin policies: card = gold-shown (strict), topical = a top-5
chunk must carry every topic token, top = the preflight's top passage
(fragments and bare causals, where no gold chunk exists).

Run: python artifacts/probes/gen-new-forms-v2-2026-10-15.py
Writes data/finetune/new-forms-v2-2026-10-15.json, a list of
{"question", "class", "source_card", "expect", "pin", "note"} with
expect in cited|refusal; refusal rows carry pin: null.

Run of this file (2026-10-15): 441 candidates -> 187 accepted (122 cited,
65 refusal); identical counts on two runs (119.3 s then 105.0 s), 0 retrieval
errors, 350 distinct asks embedded (first run).
Buckets: cards 24 (3 each of 8), bare 30, flip 16, causal 32, fragment 20,
refusal 65. Guard rejections 112: near-suite 30, near-probe-user-forms 18,
duplicate-of-train 17, reading-repair-fires 12, near-bench 11,
duplicate-of-candidate 8, gold-pin-not-shown 7, near-visible-ten 6,
no-topical-chunk 2, not-in-book 1; cap skips 142 (mostly the cards' v1 tails
and the refusal tail beyond 65). Measured seal margins: causal vs the sealed
`why does` max r=0.556 (`why though`); causal vs the probed
`why is kafka so popular?` max r=0.545; bare topics vs the sealed bare topics
max r=0.609 (`time to live` vs `Time Series`).

Deviations, reported rather than hidden:
- Budget: the brief's tilde counts (24 + ~20 + 12-16 + ~20 + ~20 + ~55) sum to
  ~153-165, below the 180 floor, so bare and causal carry the difference
  (caps 30/32) and refusals keep v1's 65; every stated maximum holds. Total
  187, inside 180-230.
- The brief's example flip `eventual vs strong consistency` is itself one of
  the 30 items in probe-user-forms-2026-10-14.py; the identical guard 4
  (r>=0.8 vs the probe strings) rejects its canonical form, so only the
  flipped direction `strong consistency vs eventual` is trainable. The
  declared backup pair `security theater vs security habit` survives one
  direction; its second direction loses the 16-row cap race.
- Brief-named bare topics that are already trained die in guard 1
  (duplicate-of-train): data catalog, data governance, data quality,
  data wrangling, data maturity, data lakehouse, data warehouse, reverse etl.
  `serialization` dies in guard 4 (the probe's typo item `serializaton`,
  r=0.960); `data integration` on the bench (`data ingestion`, r=0.800);
  `clustering` on the suite (`Streaming`, r=0.800); `multicloud` on the bench
  (`what is multicloud methodology disadvantages`, j=0.600). `idempotency` is
  not in the book (`idempotent` is): the bare `idempotent writes` and the
  causal `why does idempotent writes matter` die on the topical-chunk check.
- `data lake` cleared every guard and lost the bare cap race; it is reported
  as a cap skip, not dropped silently.
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

OUT = ROOT / "data" / "finetune" / "new-forms-v2-2026-10-15.json"
DATA = ROOT / "data" / "finetune"
SEALED_JSON = ROOT / "artifacts" / "datasets" / "sealed-forms.json"
PROBE_USER = ROOT / "artifacts" / "probes" / "probe-user-forms-2026-10-14.py"

similarity = x2d.similarity
normalized = x2d.normalized
norm_tokens = x2d.norm_tokens

# The v2 budget. Target total 180-230 accepted rows; the brief's bucket tilde
# counts (24 + ~20 + 12-16 + ~20 + ~20 + ~55) sum to ~153-165, below the 180
# floor, so the two new buckets (bare, causal) carry the difference with
# generous caps while every stated maximum holds (cards 3, flips 16, fragments
# 20, refusals 65).
MAX_PER_CARD = 3          # deficit cards: max 3 accepted forms each
MAX_BARE = 30
MAX_FLIPS = 16
MAX_CAUSALS = 32
MAX_FRAGMENTS = 20
MAX_REFUSALS = 65

# ---------------------------------------------------------------------------
# Content tokens: digits are content (ddr4/ddr5), stopwords are not. Same set
# as v1 (it is what the in-book guard and the topical-pin check both use).
# ---------------------------------------------------------------------------
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOP_TOKENS = frozenset("""
what whats how hows why whys when where which who whose
is are was were am do does did done can could should would will shall
has have had be been being not no yes
the a an of to in at for and or but with about from by as into than then
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
# Sealed suite + cross-check (unchanged from v1).
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
# Bucket 1: deficit cards. `pins` is now the gold set only (strict: a form is
# kept only when a gold chunk is in the preflight top-5; the column/row gold
# set drops ch06-067 per the v2 brief). The first forms are the v2 pick, the
# rest stay as the v1 tail so the 3-slot cap can still fill if a pick fails a
# guard. (class, question) in acceptance order.
# ---------------------------------------------------------------------------
CARDS = [
    {
        "key": "time-series",
        "source_card": "Time Series",
        "pins": ("ch05-045", "ch05-046"),
        "tolerate": frozenset(),
        "topic": "time series",
        "forms": [
            # v2 pick: named / contraction / possessive (all showed ch05-045
            # in the v1 preflight)
            ("named", "what is the purpose of time series data"),
            ("contraction", "what's the deal with time series"),
            ("possessive", "time series data's purpose"),
            # v1 tail (backups)
            ("bare", "Time Series"),          # sealed item itself -> guard 2
            ("lower", "time series"),         # normalized == sealed item
            ("named", "what is time series"),
            ("named", "what is a time series"),
            ("restate", "what are time series"),
            ("bare", "time series data"),
            ("named", "what does time series mean"),
            ("bare", "time series databases"),
            ("explain", "explain time series"),
            ("contraction", "what's a time series?"),
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
        "pins": ("ch06-066", "app01-008"),
        "tolerate": frozenset(),
        "topic": "column-oriented row-oriented columnar",
        "forms": [
            # v2 pick (all showed ch06-066 in the v1 preflight)
            ("named", "what is the difference between column-oriented and "
                      "row-oriented storage"),
            ("explain", "explain column-oriented databases"),
            ("contraction", "what's the deal with column-oriented databases"),
            # v1 tail (backups)
            ("bare", "column-oriented vs row-oriented"),   # sealed item
            ("named", "what is column-oriented storage"),
            ("named", "what is a columnar database"),
            ("restate", "what are column-oriented databases"),
            ("named", "how do column-oriented databases store data"),
            ("bare", "columnar vs row-oriented storage"),
            ("bare", "columnar serialization"),
            ("contraction", "how's column-oriented storage used"),
            ("possessive", "column-oriented storage's purpose"),
            ("punctuation", "column-oriented???"),
            ("punctuation", "column-oriented storage..."),
            ("meaning-of", "meaning of column-oriented storage"),
            ("meaning-of", "column-oriented means what"),
            ("compound", "what is column-oriented storage and how is it "
                         "used"),
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
        "pins": ("ch06-066", "app01-008"),
        "tolerate": frozenset(),
        "topic": "row-oriented column-oriented",
        "forms": [
            # v2 pick (all showed ch06-066 in the v1 preflight)
            ("named", "what is row-oriented storage"),
            ("explain", "explain row-oriented storage"),
            ("contraction", "what's the deal with row-oriented databases"),
            # v1 tail (backups)
            ("bare", "row-oriented vs column-oriented"),   # sealed item
            ("named", "what is a row-oriented database"),
            ("restate", "what are row-oriented databases"),
            ("named", "how do row-oriented databases store data"),
            ("bare", "row-oriented serialization"),
            ("named", "what is the difference between row-oriented and "
                      "columnar serialization"),
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
        "tolerate": frozenset(),
        "topic": "location",
        "forms": [
            # v2 pick: named / contraction / meaning-of (all showed ch07-046)
            ("named", "what is a location"),
            ("contraction", "what's the deal with location"),
            ("meaning-of", "meaning of location"),
            # v1 tail (backups)
            ("named", "what is location"),
            ("named", "why is location important"),
            ("named", "how is location used"),
            ("named", "why does location matter"),
            ("bare", "location"),                 # visible-ten target string
            ("contraction", "what's location"),
            ("possessive", "location's role"),
            ("possessive", "location's importance"),
            ("punctuation", "location???"),
            ("punctuation", "location..."),
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
        "tolerate": frozenset(),
        "topic": "data engineering lifecycle",
        "forms": [
            # v2 pick: named / contraction / named-stages (all showed ch02-002)
            ("named", "what is the DE lifecycle"),
            ("contraction", "what's the DE lifecycle"),
            ("named", "what are the stages of the data engineering lifecycle"),
            # v1 tail (backups)
            ("bare", "DE lifecycle"),             # visible-ten target string
            ("bare", "data engineering lifecycle"),  # already a train row
            ("named", "what is DE lifecycle"),
            ("named", "what is the data engineering lifecycle"),
            ("named", "how does the data engineering lifecycle work"),
            ("named", "why does the data engineering lifecycle matter"),
            ("named", "what does the data engineering lifecycle consist of"),
            ("contraction", "what's the deal with the DE lifecycle"),
            ("possessive", "the DE lifecycle's purpose"),
            ("possessive", "the data engineering lifecycle's stages"),
            ("punctuation", "the DE lifecycle..."),
            ("meaning-of", "meaning of DE lifecycle"),
            ("compound", "what is the DE lifecycle and how is it used"),
            ("casing", "Data Engineering Lifecycle"),  # train row normalized
            ("polite", "hey can you tell me about the DE lifecycle"),
            ("explain", "explain the DE lifecycle"),
            ("bare", "undercurrents of the data engineering lifecycle"),
            ("named", "how do the stages of the data engineering lifecycle "
                       "fit together"),
            ("explain", "explain the data engineering lifecycle stages"),
            ("restate", "what are the data engineering lifecycle stages"),
        ],
    },
    {
        "key": "ddr4-vs-ddr5",
        "source_card": "ddr4 vs ddr5",
        "pins": ("ch06-011",),
        "tolerate": frozenset(("ddr4",)),
        "topic": "ddr5 ram memory",
        "forms": [
            # v2 pick: named / named / bare (v1's first three gold-shown)
            ("named", "why is ddr5 faster than ddr4"),
            ("named", "is ddr5 better than ddr4"),
            ("bare", "ddr5"),
            # v1 tail (backups)
            ("bare", "ddr4 vs ddr5"),             # visible-ten target string
            ("flip", "ddr5 vs ddr4"),             # visible-ten target string
            ("named", "what is the difference between ddr4 and ddr5"),
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
        "tolerate": frozenset(),
        "topic": "lambda kappa architecture",
        "forms": [
            # v2 pick: flip / named / named (v1's first three gold-shown;
            # the flip direction stays in the card, as in v1)
            ("flip", "kappa vs lambda"),
            ("named", "what is lambda architecture"),
            ("named", "what is kappa architecture"),
            # v1 tail (backups)
            ("bare", "lambda vs kappa"),          # probe-user-forms item
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
        "tolerate": frozenset(("autoscanning",)),
        "topic": "automated scanning",
        "forms": [
            # v2 pick: bare / contraction / shorthand (v1's first three
            # gold-shown; one shared card cap for both spellings)
            ("bare", "auto scanning"),
            ("contraction", "what's auto scanning?"),
            ("shorthand", "autoscanning"),
            # v1 tail (backups)
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

# ---------------------------------------------------------------------------
# Bucket 2: bare topics. One bare noun-phrase per distinct book topic, drawn
# from the book's own headings (data/index.json). Acceptance requires guards
# 1-6 to pass AND a top-5 preflight passage whose text carries every content
# token of the topic (that passage becomes the pin) — "verify each retrieves a
# real pin chunk". reverse etl is kept at the tail as a guard record: it is
# already an x2d bare and dies in guard 1. materialized view is left out for
# the same reason (its trained form "a materialized view" is a near-twin; the
# candidate-dedupe log is not a rejection, so it would slip through).
# ---------------------------------------------------------------------------
BARE_TOPICS = [
    # the brief's named candidates that are in the book
    "data catalog",
    "data lineage",
    "data governance",
    "data quality",
    "schema evolution",
    "serialization",
    "orchestration",
    # more heading-backed topics
    "data wrangling",
    "data virtualization",
    "data marts",
    "data modeling",
    "data integration",
    "data ethics",
    "data privacy",
    "caching",
    "compression",
    "partitioning",
    "clustering",
    "observability",
    "webhooks",
    "microservices",
    "infrastructure as code",
    "schema registry",
    "zero-copy cloning",
    "data versioning",
    "fault tolerance",
    "data durability",
    "hybrid cloud",
    "multicloud",
    "data maturity",
    "shuffle hash join",
    "distributed joins",
    "dead-letter queue",
    "event-driven architecture",
    "time to live",
    "separation of compute and storage",
    "semantic layer",
    "idempotent writes",
    "cold data",
    "data lakehouse",
    "data products",
    "data warehouse",
    "data lake",
    "reverse etl",       # already a train bare -> guard 1 rejects
]

# ---------------------------------------------------------------------------
# Bucket 3: order-flipped pairs on non-sealed, non-trained comparisons. Each
# entry is (side_a, side_b); both directions become candidates (class flip).
# All sides are the book's own "X Versus Y" headings. The first 8 pairs fill
# the cap; "security theater / security habit" is the backup.
# ---------------------------------------------------------------------------
FLIP_PAIRS = [
    ("eventual", "strong consistency"),            # ch06-023
    ("monolith", "modular"),                       # Monolith Versus Modular
    ("serverless", "servers"),                     # Serverless Versus Servers
    ("synchronous", "asynchronous ingestion"),
    ("single-tenant", "multitenant storage"),
    ("tight", "loose coupling"),
    ("data lifecycle", "data engineering lifecycle"),
    ("single machine", "distributed storage"),
    ("security theater", "security habit"),        # backup pair
]

# ---------------------------------------------------------------------------
# Bucket 4: the causal class. Topicful shapes across diverse chapters + the
# three safe bare causals (moved here from v1's fragments, per the brief).
# Topicful causal rows need a top-5 passage carrying the topic tokens; the
# bare causals pin the preflight's top passage.
# ---------------------------------------------------------------------------
CAUSAL_TEMPLATES = (
    "why does {} matter",
    "why do data engineers care about {}",
    "why is {} important",
    "how come {}",
    "what makes {} important",
)
CAUSAL_TOPICS = [
    "data catalog",
    "data lineage",
    "data governance",
    "data quality",
    "schema evolution",
    "serialization",
    "data wrangling",
    "data virtualization",
    "caching",
    "compression",
    "partitioning",
    "observability",
    "orchestration",
    "data modeling",
    "data integration",
    "data ethics",
    "data privacy",
    "data marts",
    "microservices",
    "webhooks",
    "fault tolerance",
    "data versioning",
    "multicloud",
    "dead-letter queues",
    "time to live",
    "idempotent writes",
    "distributed joins",
    "zero-copy cloning",
    "schema registry",
    "data maturity",
]
CAUSAL_BARE = ("how come", "why though", "and why")

# ---------------------------------------------------------------------------
# Bucket 5a: fragment shapes (v1 list minus the three bare causals, which now
# live in bucket 4). Guard 2 decides; 'how does' and 'what is' are generated
# so the rejection is on the record.
# ---------------------------------------------------------------------------
FRAGMENTS = [
    "how does",
    "what is",
    "why is",
    "how to",
    "why not",
    "how so",
    "how",
    "why",
    "what for",
    "how about",
    "so what",
    "what else",
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
# Bucket 5b: refusals, unchanged from v1 (second-book contamination seeds +
# invented everyday topics; none of the sealed controls is reused).
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
    heading_by_id = {chunk["chunk_id"]: (chunk.get("heading") or "").strip()
                     for chunk in index["chunks"]}
    text_by_id = {chunk["chunk_id"]: (chunk.get("text") or "").lower()
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

    def tokens_present_in(text, tokens):
        return all(re.search(
            r"(?<![a-z0-9])" + re.escape(tok) + r"(?![a-z0-9])", text
        ) is not None for tok in tokens)

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
    pin_notes = []
    worst_suite, worst_bench, worst_visible, worst_probe = [], [], [], []

    def note_reject(cand, reason, detail: object = ""):
        rejects.append({"question": cand["question"], "class": cand["class"],
                        "reason": reason, "detail": str(detail)[:220]})

    def run_checks(cand):
        """(reason, detail) or (None, None); fills cand['note_parts']."""
        question = cand["question"]
        expect = cand["expect"]
        card = cand["card"]
        topical = cand["topical"]
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
        cand["_suite"] = (best[0], best[1], best[2], best[3])

        best_bench = (0.0, 0.0, None, None)
        for bench_form in bench_forms:
            for form in forms:
                r, j = similarity(form, bench_form)
                if r > best_bench[0]:
                    best_bench = (r, j, bench_form, form)
        worst_bench.append((best_bench[0], best_bench[1], question,
                            best_bench[2], best_bench[3]))
        cand["_bench"] = (best_bench[0], best_bench[1], best_bench[2],
                          best_bench[3])

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
        elif card is not None:
            # deficit cards: strict gold pin, keep only if a gold chunk is in
            # the preflight top-5
            hit = next((pin for pin in card["pins"] if pin in shown), None)
            if hit is None:
                return "gold-pin-not-shown", (
                    f"gold {list(card['pins'])} not in {shown[:5]}")
            cand["pin_out"] = hit
            parts.append(f"pin {hit} in top-5")
        elif topical is not None:
            # bare / flip / topicful causal: a top-5 chunk must carry every
            # topic token; that chunk is the pin
            hit = next(
                (h for h in passages if tokens_present_in(
                    text_by_id.get(h["chunk_id"], h.get("text", "").lower()),
                    topical)),
                None,
            )
            if hit is None:
                return "no-topical-chunk", (
                    f"no top-5 chunk carries {topical} (top: {shown[:5]})")
            cand["pin_out"] = hit["chunk_id"]
            pin_notes.append((question, hit["chunk_id"], topical))
            parts.append(
                f"pin {hit['chunk_id']} in top-5 "
                f"(topic chunk: {heading_by_id.get(hit['chunk_id'], '?')})")
        else:
            # fragments and bare causals: pin the preflight's top passage
            cand["pin_out"] = shown[0]
            parts.append(f"fragment/causal: pin = preflight top passage "
                         f"({heading_by_id.get(shown[0], '?')})")
        if canon != question:
            parts.append(f"asked as: {canon!r}")

        cand["note_parts"] = parts
        return None, None

    def cap_bucket(cand):
        """(cap key, limit) for a candidate."""
        if cand["expect"] == "refusal":
            return "refusal", MAX_REFUSALS
        if cand["card"] is not None:
            return f"card:{cand['card']['key']}", MAX_PER_CARD
        return cand["bucket"], {
            "bare": MAX_BARE, "flip": MAX_FLIPS, "causal": MAX_CAUSALS,
            "fragment": MAX_FRAGMENTS,
        }[cand["bucket"]]

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

    # candidate order: deficit cards, bares, flips, causals, fragments,
    # refusals
    candidates = []
    for card in CARDS:
        for class_name, question in card["forms"]:
            candidates.append({
                "question": question, "class": class_name, "card": card,
                "topical": None, "bucket": "card",
                "source_card": card["source_card"], "expect": "cited",
            })
    for topic in BARE_TOPICS:
        candidates.append({
            "question": topic, "class": "bare", "card": None,
            "topical": tuple(dict.fromkeys(content_tokens(topic))),
            "bucket": "bare", "source_card": f"bare:{topic}",
            "expect": "cited",
        })
    for side_a, side_b in FLIP_PAIRS:
        for direction, question in ((1, f"{side_a} vs {side_b}"),
                                    (2, f"{side_b} vs {side_a}")):
            candidates.append({
                "question": question, "class": "flip", "card": None,
                "topical": tuple(dict.fromkeys(content_tokens(question))),
                "bucket": "flip",
                "source_card": f"flip:{side_a} vs {side_b}",
                "expect": "cited",
            })
    for step, topic in enumerate(CAUSAL_TOPICS):
        template = CAUSAL_TEMPLATES[step % len(CAUSAL_TEMPLATES)]
        question = template.format(topic)
        candidates.append({
            "question": question, "class": "causal", "card": None,
            "topical": tuple(dict.fromkeys(content_tokens(topic))),
            "bucket": "causal", "source_card": f"causal:{template}",
            "expect": "cited",
        })
    for question in CAUSAL_BARE:
        candidates.append({
            "question": question, "class": "causal", "card": None,
            "topical": None, "bucket": "causal",
            "source_card": "causal:bare", "expect": "cited",
        })
    for question in FRAGMENTS:
        candidates.append({
            "question": question, "class": "fragment", "card": None,
            "topical": None, "bucket": "fragment",
            "source_card": "fragment-shape", "expect": "cited",
        })
    for class_name, question in REFUSALS:
        candidates.append({
            "question": question, "class": class_name, "card": None,
            "topical": None, "bucket": "refusal",
            "source_card": f"refusal:{' '.join(content_tokens(question)[:2])}",
            "expect": "refusal",
        })

    for cand in candidates:
        check_and_accept(cand)

    rows = [{k: v for k, v in row.items() if not k.startswith("_")}
            for row in accepted]
    OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")

    by_expect = Counter(row["expect"] for row in rows)
    by_class = Counter(f"{row['expect']}/{row['class']}" for row in rows)
    by_card = Counter(row["source_card"] for row in rows)
    rej_by_reason = Counter(rej["reason"].split(":")[0] for rej in rejects)
    bucket_of = {}
    for cand in candidates:
        bucket_of[cand["question"]] = cand["bucket"]
    by_bucket = Counter(bucket_of.get(row["question"], "?") for row in rows)

    print()
    print("================ summary ================")
    print(f"generated candidates: {len(candidates)}  "
          f"(cards {sum(len(c['forms']) for c in CARDS)}, bares "
          f"{len(BARE_TOPICS)}, flips {2 * len(FLIP_PAIRS)}, causals "
          f"{len(CAUSAL_TOPICS) + len(CAUSAL_BARE)}, fragments "
          f"{len(FRAGMENTS)}, refusals {len(REFUSALS)})")
    print(f"accepted: {len(rows)}  by expect: {dict(sorted(by_expect.items()))}")
    print(f"rejected: {len(rejects)}  cap skips: {len(cap_skips)}")
    print(f"by bucket: {dict(sorted(by_bucket.items()))}")
    print(f"by expect/class: {dict(sorted(by_class.items()))}")
    print(f"accepted by source_card: {dict(sorted(by_card.items()))}")
    print(f"rejections by guard: {dict(sorted(rej_by_reason.items()))}")
    print(f"cap counts (accepted per cap bucket): "
          f"{dict(sorted(cap_counts.items()))}")
    print(f"retrieval errors: {retrieval_errors}  ctx cache: {len(ctx_cache)}")
    print(f"reading repairs (cited, logged): {len(repair_notes)}")
    for q, reading in repair_notes[:10]:
        print(f"  repair {q!r} -> {reading!r}")
    print(f"topical pins computed at preflight (accepted + cap-skipped): "
          f"{len(pin_notes)}")
    for q, chunk_id, tokens in pin_notes[:40]:
        print(f"  topical {q!r} -> {chunk_id} tokens={list(tokens)}")
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
    print("accepted rows only, worst suite similarity (top 5):")
    accepted_q = {row["question"] for row in accepted}
    ranked = sorted((c for c in candidates if c["question"] in accepted_q),
                    key=lambda c: -c.get("_suite", (0,))[0])
    for cand in ranked[:5]:
        r, j, item, form = cand["_suite"]
        print(f"  r={r:.3f} j={j:.3f} {cand['question']!r} vs {item!r}")
    print("accepted rows only, worst bench similarity (top 5):")
    ranked = sorted((c for c in candidates if c["question"] in accepted_q),
                    key=lambda c: -c.get("_bench", (0,))[0])
    for cand in ranked[:5]:
        r, j, bench_form, form = cand["_bench"]
        print(f"  r={r:.3f} j={j:.3f} {cand['question']!r} vs {bench_form!r}")
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
        gained = sorted(set(card.get("_pins_shown") or ()))
        print(f"  {card['source_card']}: topic {card['topic']!r} "
              f"tokens={tokens} absent={missing or 'none'} "
              f"tolerate={sorted(card['tolerate']) or 'none'} "
              f"gold={list(card['pins'])}")
        print(f"    gold chunks shown in accepted preflights: {gained}")

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
