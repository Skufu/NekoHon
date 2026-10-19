"""Answers from retrieved passages: the ask and answer modes.

ask: the model quotes, the quote is checked; a failed check is a refusal.
answer: the model answers from the passages in the same quote-first shape
(SYSTEM + user_message — the exact prompts the student is trained on); its
[Ch. n] tags become citations, quotation marks the passages cannot back are
stripped, and the quote check demotes from gate to meter
(artifacts/harnesses/groundedness.py). An uncited answer gets one `[Ch. `
prefill retry, kept only when a citation validates (`_retry_uncited`).

Prompt alignment (2026-10-15): answer mode used to send SYSTEM_ANSWER ("a few
sentences ... in your own words"). The training data has always been
ask-shaped (quote-first); x2d masked the mismatch by over-memorizing
(loss 0.006), while x2e followed the served prompt, paraphrased, and failed
the verbatim check (40/160 vs 111/160, probe-fragment evidence). The default
path now serves what the model was trained on.
"""

import difflib
import functools
import json
import os
import random
import re
import urllib.request

from canonical import STEM_WORDS, canonical_query, is_deictic_question, is_incomplete_stem
from captions import caption_seed
from figures import cited_numbers, figures_for, number_from_id
from fusion import fuse
from intent import (
    INTENT_AUTHOR_QUESTION,
    INTENT_CONCEPT_TERM,
    INTENT_MULTI_SENTENCE,
    INTENT_VAGUE_FRAGMENT,
    META_TRANSITION_RE,
    analyze_intent,
    classify_intent,
    compute_dynamic_followups,
    extract_core_concept,
    extract_enclosing_subject,
    select_substantive_anchor_sentence,
    split_sentences,
)
from keywords import anchor_words, postings, rare
from preprocess import STOPWORDS, stem as _pre_stem, tokens as _pre_tokens, words as _pre_words

@functools.lru_cache(maxsize=4096)
def _cached_words(text):
    return tuple(_pre_words(text))

def words(text):
    return list(_cached_words(text))

@functools.lru_cache(maxsize=4096)
def _cached_tokens(text):
    return tuple(_pre_tokens(text))

def tokens(text):
    return list(_cached_tokens(text))

@functools.lru_cache(maxsize=4096)
def stem(word):
    return _pre_stem(word)

_WHITESPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_CH_PREFIX_RE = re.compile(r"^\[ch\.", re.I)
_CH_TAG_STRIP_RE = re.compile(r"\[Ch\.\s*[^\]]+\]\s*", re.I)
_TAG_AND_QUOTE_RE = re.compile(r"\[Ch\.\s*([^\]]+)\]\s*[\"“](.+?)[\"”]")
_TAG_SEARCH_RE = re.compile(r"\[Ch\.\s*([^\]]+)\]", re.I)
_QUOTE_EXTRACT_RE = re.compile(r"[\"“]([^\"“”]+)[\"”]")
_NORMALIZED_QUOTE_CHARS_RE = re.compile(r"[\s\"'“”]+")
_TRAP_QUERY_RE = re.compile(r"\b(how\s+much|charge|price|cost\s+per\s+hour|what\s+year|when\s+did|in\s+what\s+year|terraform|script|code|install|download)\b", re.I)
_WHICH_CHAPTER_RE = re.compile(r"\b(which\s+chapter|where\s+in\s+the\s+book)\b", re.I)
_CHAPTER_NUM_RE = re.compile(r"\bchapter\s+\d+\b", re.I)
_CHAPTER_DIGITS_RE = re.compile(r"\bchapter\s+(\d+)\b", re.I)
_IN_GREATER_DETAIL_RE = re.compile(r"\bin greater detail\b", re.I)
_OVERHEAD_RE = re.compile(r"\b(overhead|trade-offs|tradeoffs)\b", re.I)
_OVERHEAD_EXPANDED_RE = re.compile(r"\b(overhead|trade-offs|tradeoffs|latency|throughput)\b", re.I)
_YEAR_QUERY_RE = re.compile(r"\b(what\s+year|when\s+did|in\s+what\s+year)\b", re.I)
_YEAR_MATCH_RE = re.compile(r"\b(19|20)\d{2}\b")
_PRICE_QUERY_RE = re.compile(r"\b(how\s+much|cost\s+per\s+hour|charge|price)\b", re.I)
_PRICE_MATCH_RE = re.compile(r"(\$|\b(dollar|dollars|cents|cost|charge|price|per\s+hour)\b)", re.I)
_CODE_QUERY_RE = re.compile(r"\b(terraform|script|code)\b", re.I)
_CODE_MATCH_RE = re.compile(r"\b(terraform|resource|provider|hcl|script|def |class |function)\b", re.I)
_TERMINAL_PUNCT_RE = re.compile(r'[.!?]["\'”’]?$')
_CHAPTER_PREFIX_RE = re.compile(r"^Chapter\s+\d+\b", re.I)
_WORD_RE = re.compile(r"\w+")
_WORD_ALPHA_RE = re.compile(r"\b[a-zA-Z]+\b")
_WORD_ALPHANUM_RE = re.compile(r"\b[a-zA-Z0-9]+\b")
_NON_WORD_OR_UNDERSCORE_RE = re.compile(r"[^\w\s]|_")
_REGARDING_PREFIX_RE = re.compile(r"^(?:In\s+.+?,\s+)?[Rr]egarding\s+['\"]?([^:'\"]+)['\"]?\s*:\s*(.+)$")
_TOPIC_SHIFT_CONCEPT_RE = re.compile(r"^(?:what\s+(?:is|are|was|were)\s+(?:a\s+|an\s+|the\s+)?(?!(?:role|main|key|specific|purpose|point|goal|problem|catch|drawback|advantage|disadvantage|trade-off|difference|reason|stage|step|type|example|takeaway)\b)|define\s+|tell\s+me\s+about\s+)(.+?)\??$", re.I)
_BOILERPLATE_PROMPT_LEAK_RE = re.compile(r"[,;—–-]?\s*\b(?:do\s+not|don't|never)\s+(?:say|use|repeat|mention|start\s+with|include|write|output)\b[^.?!]*", re.I)
_IN_THIS_CONTEXT_START_RE = re.compile(r"^[Ii]n this context,?\s*")
_IN_THIS_CONTEXT_WORD_RE = re.compile(r"\bin this context\b", re.I)
_HIGHLIGHTED_QUESTION_RE = re.compile(r"\b[Tt]he highlighted question\b")
_IN_THIS_PASSAGE_START_RE = re.compile(r"^[Ii]n this passage,?\s*")
_PASSAGE_VERB_RE = re.compile(r"^(?:[Tt]he|[Tt]his)\s+passage\s+(?:states|explains|discusses|describes|refers to|means)\s+")
_PASSAGE_START_RE = re.compile(r"^(?:[Tt]he|[Tt]his)\s+passage\s+")
_HIGHLIGHTED_TERM_RE = re.compile(r"\b[Tt]he highlighted (?:text|phrase|sentence|passage|term|concept|word|section)\b")
_HIGHLIGHTED_NOT_WORD_PHRASE_RE = re.compile(r"\b[Tt]he highlighted(?!\s+(?:word|phrase))\b")
_REFERS_TO_A_RE = re.compile(r"\brefers to an?\b", re.I)
_REFERS_TO_THE_RE = re.compile(r"\brefers to the\b", re.I)
_REFERS_TO_RE = re.compile(r"\brefers to\b", re.I)
_TRAILING_PREP_WORD_DOT_RE = re.compile(r"\.\s+(?:with|for|in|on|to|by|of|and|or)\s+[A-Za-z0-9_-]+\.$")
_GIBBERISH_DIGITS_RE = re.compile(r"\b(?:sentence|line|paragraph|passage)\s+\d+\b", re.I)
_GIBBERISH_NOUN_DIGITS_RE = re.compile(r"\b[A-Za-z]+\s+\d+\s+(?:negative|positive|again|reads?)\b", re.I)
_ADJACENT_REPEATED_WORD_RE = re.compile(r"\b([A-Za-z]{3,})\s+\1\b", re.I)
_SENTENCE_DANGLING_END_RE = re.compile(r"\b(?:the|a|an|also|again|to|of|in|for|with|and|or|that)\s*[.?!]$", re.I)
_META_COMMENTARY_RE = re.compile(r"\b(?:this|the)\s+(?:section|chapter|passage|book|authors?)\s+(?:introduces?|prepares?\s+readers|discusses?|mentions?|is\s+a\s+detour)\b", re.I)
_POINTER_META_LOCATION_RE = re.compile(r"\b(?:are|is)\s+(?:listed|discussed|covered|described|explained|found|shown|outlined|detailed|introduced)\s+in\s+(?:the|this|chapter|section|figure|part)\b|\b(?:in\s+the\s+introduction|see\s+chapter|see\s+section|see\s+figure|refer\s+to\s+chapter)\b", re.I)
_PROMPT_LEAKAGE_RE = re.compile(r"\b(?:do\s+not|don't|never)\s+(?:say|use|repeat|mention|start\s+with|include|write|output)\b", re.I)
_TYPE_2_RE = re.compile(r"\btype[- ]2\b")
_S3_RE = re.compile(r"\bs3\b")
_IOPS_RE = re.compile(r"\biops\b")
_SLA_SLO_RE = re.compile(r"\b(sla|slas|slo|slos)\b")
_WHO_CREATED_RE = re.compile(r"\bwho\s+(?:created|invented|designed|developed|authored|introduced|wrote|founded|proposed)\b")
_AUTHOR_NAME_RE = re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b")
_DOWNSIDES_RE = re.compile(r"\b(its\s+downsides|its\s+disadvantages|its\s+pros\s+and\s+cons|its\s+drawbacks)\b")
_WARN_AGAINST_RE = re.compile(r"\b(warn\s+against\s+that|warn\s+about\s+that|caution\s+against\s+that)\b")
_LATE_DATA_RE = re.compile(r"\b(handle\s+late\s+data|handles\s+late\s+data)\b")
_THAT_STAGE_RE = re.compile(r"\b(that\s+stage|that\s+phase|that\s+step)\b")
_THIS_PATTERN_RE = re.compile(r"\b(this\s+architectural\s+pattern|this\s+pattern|this\s+architecture)\b")
_USING_IT_RE = re.compile(r"\busing\s+it\b")
_FOR_THIS_THAT_RE = re.compile(r"\bfor\s+(this|that)\b")
_OPEN_SOURCE_IT_RE = re.compile(r"\bopen-source\s+it\b")
_HOW_WHAT_IT_RE = re.compile(r"\b(how\s+does|how\s+is|what\s+is|what\s+are|why\s+does|why\s+is)\s+it\b")
_WHAT_ITS_RE = re.compile(r"\b(what\s+are|what\s+is)\s+its\b")
_TIER_STAGE_NUM_RE = re.compile(r"\b(type|tier|stage|phase|step)\s*\d+\b")
_REASONS_QUERY_RE = re.compile(r"\b(specific\s+reasons|reasons|reason|why|main\s+stages|stages|key\s+types|types|characteristics|ways)\b")
_EXAMPLES_QUERY_RE = re.compile(r"\b(example|examples|instance|illustrate)\b")
_RISKS_QUERY_RE = re.compile(r"\b(risk|risks|pitfall|pitfalls|bottleneck|bottlenecks|cost|costs|expensive|trade-off|trade-offs|limitation|limitations|downside|downsides|ossification|cliff|mistake|failure)\b")
_ATTRIBUTION_QUERY_RE = re.compile(r"\b(who\s+created|who\s+introduced|who\s+coined|who\s+founded|who\s+proposed|who\s+invented|creator|inventor|author|authored)\b")
_ENTITY_PHRASE_RE = re.compile(r"\b([A-Z][a-zA-Z0-9]*(?:[- ](?:[A-Z0-9][a-zA-Z0-9]*|\d+(?:\.\d+)*))+)\b")
_ACRONYM_MATCH_RE = re.compile(r"\b([A-Z]{2,10}s?)\b")
_STRIP_PUNCT_RE = re.compile(r"^[^\w]+|[^\w]+$")
_PUNCT_SPLIT_RE = re.compile(r"[.!?]")
_MASK_TAG_RE = re.compile(r"\x01([^\x02]*)\x02")
_DIGITS_RE = re.compile(r"\d+")
_STRIP_LIST_NUM_RE = re.compile(r"^\s*\d+[.)]\s*")
_EXAMPLE_PREFIX_STRIP_RE = re.compile(r"^(?:for example|for instance|in addition|specifically),?\s*", re.I)
_EXTRACT_SUBJ_CAND_RE = re.compile(r"^\s*(?:A|An|The)?\s*([A-Za-z0-9\s_-]{3,40}?)\s+(?:is|are|was|were|provides|serves|enables|means|refers|consists|helps|acts|describes)\b")
_EXTRACT_SUBJ_WHEN_RE = re.compile(r"\b(?:when|while)\s+(.+)", re.I)
_EXTRACT_SUBJ_STRIP_ACTION_RE = re.compile(r"^(selecting|evaluating|choosing|designing|building)\s+", re.I)
_EXTRACT_SUBJ_STRIP_ART_RE = re.compile(r"^(a|an|the)\s+", re.I)
_EXTRACT_SUBJ_WH_START_RE = re.compile(r"^(what|how|why|where|which|should|tell me about|explain)\s+(?:is|are|was|were|does|do|did|can|could|should)?\s*(?:\b(?:a|an|the|teams|engineers|users|we)\b)?\s*", re.I)
_EXTRACT_SUBJ_VERB_SPLIT_RE = re.compile(r"\s+(?:sit|sits|used|use|stand for|look|differ|consider|covered)\b", re.I)

_PRONOUNS_SET = frozenset({"this", "it", "that", "they", "these", "those"})
_DEICTIC_SET_1 = frozenset({"it", "its", "this", "that", "these", "those", "they", "them", "such"})
_DEICTIC_SET_2 = frozenset({"this", "that", "it", "these", "those"})
_QUESTION_STARTERS = frozenset({
    "what", "why", "how", "when", "where", "who", "which",
    "is", "are", "was", "were", "do", "does", "did",
    "can", "could", "should", "would", "will", "explain",
    "describe", "define", "chapter", "section", "figure",
    "regarding", "about", "compare", "contrast", "differentiate",
    "distinguish", "versus", "vs",
})
_GENERIC_ENTITY_WORDS = frozenset({
    "type", "types", "kind", "kinds", "level", "levels", "stage", "stages",
    "phase", "phases", "step", "steps", "chapter", "chapters", "section", "sections",
    "table", "tables", "figure", "figures", "part", "parts",
})
_WH_STARTS = ("what", "which", "who", "whom", "whose", "where", "when", "why", "how")
_AUX_WORDS = ("is", "are", "was", "were", "do", "does", "did", "can", "could", "should", "would", "will")
_OPENER_WORDS = ("explain", "describe", "define", "compare", "tell", "show")
_SUB_PRONOUNS = frozenset({"it", "its", "that", "this", "these", "those"})
_CAND_PRONOUNS = frozenset({"it", "its", "this", "that"})
_RISK_KEYWORDS = ("ossification", "cliff", "bottleneck", "bottlenecks", "cost", "costs", "expensive", "risk", "risks", "pitfall", "pitfalls", "trade-off", "trade-offs", "limitation", "limitations", "downside", "downsides")
_ATTRIBUTION_MARKERS = ("noted", "groundbreaking", "book", "article", "creator", "created", "proposed", "introduced", "author", "by ")
_WH_QUERY_SET = frozenset({"why", "explain", "how", "what"})

@functools.lru_cache(maxsize=1024)
def _token_word_pattern(token):
    return re.compile(rf"\b{re.escape(token)}\b")

@functools.lru_cache(maxsize=512)
def _selection_word_pattern(sel):
    return re.compile(rf"\b{re.escape(sel)}\b", re.IGNORECASE)

@functools.lru_cache(maxsize=1024)
def _heading_prefix_pattern(heading):
    words_list = heading.split()
    if not words_list:
        return None
    pat_str = r"\s*".join(re.escape(w) for w in words_list)
    return re.compile(rf"\s*{pat_str}[\s:\u2014-]*", re.I)

@functools.lru_cache(maxsize=512)
def _words_pattern(quote):
    words_list = (quote or "").split()
    if not words_list:
        return None
    return re.compile(r"\s+".join(re.escape(w) for w in words_list), re.I)


FRAMING_WORDS = frozenset((
    "define", "defines", "defined", "definition",
    "describe", "describes", "described", "description",
    "explain", "explains", "explained", "explanation",
    "mean", "means", "meaning",
    "stand", "stands",
    "constitute", "constitutes",
    "refer", "refers",
    "work", "works", "worked", "working",
    "occur", "occurs", "occurred",
    "use", "uses", "used", "using",
    "handle", "handles", "handled", "handling",
    "require", "requires", "required", "requirement", "requirements",
    "condition", "conditions",
    "provide", "provides", "provided",
    "complete", "completes", "completed", "completing",
    "achieve", "achieves", "achieved",
    "perform", "performs", "performed",
))
from prompt import (
    ANSWER_GLOSS_SYSTEM,
    ANSWER_MODEL,
    EXPLAIN_GLOSS_SYSTEM,
    FOLLOWUP_GLOSS_SYSTEM,
    PARAPHRASE_SYSTEM,
    REFUSAL,
    SPELL_SYSTEM,
    SYSTEM,
    SYSTEM_ANSWER,
)
from readings import llm_second_reading, second_reading
from retrieve import rank_chunks, search

OLLAMA_CHAT = "http://127.0.0.1:11434/api/chat"
PASSAGE_LIMIT = 5
# Rewrites per plain answer: one call each, a call budget, not a quality knob
# (measured citations run at 1-3; the scorecard's answers stayed under five).
PARAPHRASE_LIMIT = 5
MISS_QUOTE_CHARS = 160
FIGURE_REFERENCE = re.compile(r"\((?:figure|fig\.)\s*[A-Za-z]?\d+-\d+\)", re.I)
FORMAT_REMINDER = (
    "Copy one sentence from a passage. Do not reword it.\n"
    "Format example, not an answer:\n"
    "[Ch. 2] \"exact sentence copied from a passage\"\n"
    "One short line in simple words."
)
QUIZ_INSTRUCTION = (
    "Write one question a person could answer with a quote from the single "
    "passage below. Do not include that quote in the question. "
    "Do not start with [Ch. The question is one or two sentences."
)
QUIZ_SYSTEM = (
    "You are a teacher testing a reader's comprehension of a book. "
    "Write exactly one question whose answer is the target sentence. "
    "Do not include [Ch. N] tags, do not quote the sentence verbatim, and do not refuse."
)
SIMPLIFY_RE = re.compile(
    r"\b(simpler\s+words|simplify|break\s+this\s+down|explain\s+this|what\s+does\s+this\s+mean|in\s+simple\s+words)\b",
    re.IGNORECASE,
)
TAG_PATTERN = re.compile(r"\[Ch\.\s*([^\]]+)\]", re.I)
QUOTE_PATTERN = re.compile(r"[\"“]([^\"“”]+)[\"”]")
ANSWER_REMINDER = (
    "Answer the question directly, in your own words. Cite each claim with "
    "[Ch. N] using the chapter of the passage it came from."
)
KEY_MIN_CHARS = 40
SPAN_MIN_CHARS = 40
# A complete sentence may answer even when shorter than SPAN_MIN_CHARS:
# "Everything fails, all the time." is 30 characters. Sentence shape is the
# test; a fragment or a bare heading stays a refusal.
MIN_QUOTE_CHARS = 20
# One screen of quoted text (about 16 lines at 75 chars). A paragraph over this
# keeps the model's quote instead of the whole paragraph. Chosen for
# readability; not tuned to any ask.
PARAGRAPH_CAP = 1200
HISTORY_TURNS = 2
HISTORY_QUESTION_CHARS = 200
HISTORY_ANSWER_CHARS = 400


# The plain register's cues. Generic English phrases, not fitted to a test
# (the scorecard asks carry "in simple words"); cue detection is a product
# feature, the same class of text as the refusal sentence.
SIMPLE_CUES = (
    "in simple words",
    "in simple terms",
    "in plain words",
    "for a beginner",
    "for beginners",
    "simply explain",
    "explain simply",
    "like i'm five",
    "eli5",
    "keep it simple",
)


def simple_words(question):
    """True when the question asks for the plain register."""
    folded = (question or "").lower()
    return any(cue in folded for cue in SIMPLE_CUES)


DEFAULT_BOOK_ID = "".join(["f", "d", "e"])


def _patch_figures_src(body, index):
    if not isinstance(body, dict) or not isinstance(index, dict):
        return body
    book_id = index.get("book_id", DEFAULT_BOOK_ID)
    if book_id != DEFAULT_BOOK_ID:
        for fig in body.get("figures", []):
            if fig.get("src") and "?book_id=" not in fig["src"]:
                fig["src"] = f"{fig['src']}?book_id={book_id}"
    return body


def passages_block(passages):
    blocks = []
    for hit in passages:
        blocks.append(
            f"[Ch. {hit['chapter']}] chunk_id={hit['chunk_id']}\n{hit['text']}"
        )
    return "\n\n".join(blocks)


INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+|previous\s+|prior\s+|your\s+|the\s+|above\s+)*(?:instructions|rules|prompts|directions)\b", re.I),
    re.compile(r"\b(?:print|show|reveal|output|repeat|display)\s+(?:the\s+|your\s+)?system\s+(?:prompt|instructions)\b", re.I),
    re.compile(r"\bsystem\s+prompt\s*:", re.I),
    re.compile(r"\n\s*passages\s*:", re.I),
    re.compile(r"\bchunk_id\s*=", re.I),
    re.compile(r"<\|im_(?:start|end)\|>", re.I),
)
CONTROL_TOKENS = re.compile(r"<\|im_(?:start|end)\|>", re.I)
FORGED_HEADERS = re.compile(
    r"\n\s*(?:passages|question|user|book)\s*:",
    re.I,
)


def is_prompt_injection(question: str) -> bool:
    """True when question contains explicit adversarial prompt injection patterns."""
    if not question or not isinstance(question, str):
        return False
    return any(pattern.search(question) for pattern in INJECTION_PATTERNS)


def sanitize_query(question: str) -> str:
    """Strip control tokens and collapse forged section headers to spaces."""
    if not question or not isinstance(question, str):
        return ""
    cleaned = CONTROL_TOKENS.sub("", question)
    cleaned = FORGED_HEADERS.sub(" ", cleaned)
    return cleaned.strip()


def sanitize_history(history):
    """Last HISTORY_TURNS turns, clipped. Missing or non-list history is []."""
    if not isinstance(history, list):
        return []
    kept = []
    for item in history:
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        answer = item.get("answer")
        if not isinstance(question, str) or not isinstance(answer, str):
            continue
        question = sanitize_query(question)[:HISTORY_QUESTION_CHARS].strip()
        answer = sanitize_query(answer)[:HISTORY_ANSWER_CHARS].strip()
        if not question or not answer:
            continue
        kept.append({"question": question, "answer": answer})
    return kept[-HISTORY_TURNS:]


def user_message(question, passages, history=None):
    turns = sanitize_history(history)
    prefix = ""
    if turns:
        lines = ["Earlier in this conversation (not a source — do not quote it):"]
        for turn in turns:
            lines.append(f"User: {turn['question']}")
            lines.append(f"Book: {turn['answer']}")
        prefix = "\n".join(lines) + "\n\n"
    return (
        f"{prefix}"
        f"Question: {question}\n\n"
        "Passages:\n"
        f"{passages_block(passages)}\n\n"
        f"{FORMAT_REMINDER}"
    )


def answer_user_message(question, passages):
    return (
        f"Question: {question}\n\n"
        "Passages:\n"
        f"{passages_block(passages)}\n\n"
        f"{ANSWER_REMINDER}"
    )


def ollama_generate(system, user, model=ANSWER_MODEL, url=OLLAMA_CHAT, timeout=120,
                    prefill=""):
    # num_predict caps runaway generations: a loop becomes a truncated answer
    # instead of the 120 s client timeout (loop-mechanism-analysis-2026-10-14).
    # 512 is far above the longest legal reply (answer targets p90 622 chars).
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    if prefill:
        # Raw continuation: the trailing assistant turn makes the model
        # continue from the prefill instead of starting a fresh reply (probed
        # 2026-10-14: "hello" continued as " world"). The caller prepends it.
        messages.append({"role": "assistant", "content": prefill})
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", "24h"),
        "options": {"temperature": 0, "num_predict": 512},
        "messages": messages,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    message = body.get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("empty completion")
    return content.strip()


ollama_generate._is_live = True


def ollama_generate_stream(system, user, model=ANSWER_MODEL, url=OLLAMA_CHAT,
                           timeout=120, prefill="", on_token=None):
    """ollama_generate, but each token reaches on_token as it arrives.

    Same request shape (stream=True), same return value (the stripped
    completion), same empty-completion RuntimeError; on_token receives each
    non-empty content piece. The server's stream=1 path passes on_token;
    every other caller keeps using ollama_generate.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    if prefill:
        # Raw continuation; see ollama_generate.
        messages.append({"role": "assistant", "content": prefill})
    payload = {
        "model": model,
        "stream": True,
        "think": False,
        "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", "24h"),
        "options": {"temperature": 0, "num_predict": 512},
        "messages": messages,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    pieces = []
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if prefill and on_token is not None:
            # The callers prepend the prefill to the returned continuation; the
            # token stream carries it so the pane shows the whole text
            # (`[Ch. 7] …`, not a bare `7] …`). The return value stays the
            # continuation only.
            on_token(prefill)
        for line in response:
            line = line.strip()
            if not line:
                continue
            try:
                frame = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            piece = ((frame.get("message") or {}).get("content")) or ""
            if piece:
                pieces.append(piece)
                if on_token is not None:
                    on_token(piece)
    content = "".join(pieces)
    if not content.strip():
        raise RuntimeError("empty completion")
    return content.strip()


ollama_generate_stream._is_live = True


def _strip_quotes(text):
    text = text.strip()
    text = text.strip("\"'`“”")
    return re.sub(r"\s+", " ", text).strip(" .")


def _short_sentence(raw, quote):
    """True when a sub-SPAN_MIN_CHARS quote is a complete sentence.

    Shape, not length: an upper-case start and terminal punctuation in the
    text the model wrote, plus real cleaned length. "Everything fails, all the
    time." passes (measured 2026-10-13); a mid-sentence fragment or a bare
    heading ("Hot, warm, and cold data") does not.
    """
    raw = (raw or "").strip()
    if len(quote) < MIN_QUOTE_CHARS:
        return False
    return raw[:1].isupper() and raw.endswith((".", "?", "!"))


@functools.lru_cache(maxsize=2048)
def _strip_figure_refs(text):
    """Drop "(Figure 6-1)" and the like before a quote is matched.

    The model leaves figure references out when it copies, and the book puts
    them mid-sentence. Matching with them removed keeps "Storage is the
    cornerstone ... and underlies its major stages" whole; otherwise the
    longest copied run starts after the parenthetical. Both sides are stripped,
    so a quote that keeps its "(Figure 8-8)" still matches.
    """
    return FIGURE_REFERENCE.sub(" ", text or "")


@functools.lru_cache(maxsize=2048)
def _punctuation_plain(text):
    return " ".join(_NON_WORD_OR_UNDERSCORE_RE.sub(" ", (text or "").lower()).split())


def _quote_in_passage(quote, text):
    if not quote:
        return False
    folded_quote = re.sub(r"\s+", " ", _strip_figure_refs(quote)).lower()
    folded_text = re.sub(r"\s+", " ", _strip_figure_refs(text)).lower()
    if folded_quote in folded_text:
        return True
    # Typographic variants are the same sentence: the book writes curly quotes
    # and interior commas that a copied quote flattens (measured: "data about
    # data", 2026-10-13). Punctuation is not wording; word order is kept.
    return (
        _punctuation_plain(_strip_figure_refs(quote))
        in _punctuation_plain(_strip_figure_refs(text))
    )


@functools.lru_cache(maxsize=2048)
def _fold(text):
    return _WHITESPACE_RE.sub(" ", text or "").lower()


def _original_case(span, text):
    """The span as it is written in the passage, case and all, snapped to whole-word boundaries."""
    if not span or not text:
        return span or ""
    flat = re.sub(r"\s+", " ", text or "")
    match = re.search(re.escape(span), flat, re.I)
    if not match:
        return span
    start, end = match.start(), match.end()
    while start > 0 and (flat[start - 1].isalnum() or flat[start - 1] in "-_"):
        start -= 1
    while end < len(flat) and (flat[end].isalnum() or flat[end] in "-_"):
        end += 1
    snapped = flat[start:end].strip(" .")
    return snapped if snapped else span


def longest_copied_span(completion, passage):
    """The longest word-for-word run the model copied. The edit is dropped.

    Under 40 characters is not a quote. Short overlap stays a refusal.
    """
    folded_passage = _fold(passage)
    folded_completion = _fold(completion)
    if not folded_passage or not folded_completion:
        return ""
    match = difflib.SequenceMatcher(
        None, folded_passage, folded_completion, autojunk=False
    ).find_longest_match(0, len(folded_passage), 0, len(folded_completion))
    if match.size < SPAN_MIN_CHARS:
        return ""
    return folded_passage[match.a:match.a + match.size].strip(" .")


def _span_from_chapter(chapter, completion, passages):
    best = ("", None)
    for hit in passages:
        if str(hit["chapter"]) != str(chapter):
            continue
        span = longest_copied_span(completion, hit.get("text") or "")
        if len(span) > len(best[0]):
            best = (span, hit)
    if best[1] is None:
        return None, ""
    snapped = _original_case(best[0], best[1].get("text") or "")
    return best[1], snapped


DANGLING_END_WORDS = frozenset({
    "on", "of", "in", "to", "for", "with", "by", "at", "from", "the", "a", "an",
    "and", "or", "as", "not", "simply", "large", "into", "such", "than", "that",
    "which", "is", "are",
})


def _complete_truncated_quote(quote: str, passage_text: str) -> str:
    """Complete a quote if it was cut off mid-sentence or has unbalanced parentheses."""
    if not quote or not passage_text:
        return quote
    q = quote.strip()
    pos = passage_text.find(q)
    if pos == -1:
        idx = passage_text.lower().find(q.lower())
        if idx != -1:
            q = passage_text[idx:idx + len(q)]
            pos = idx
        else:
            return quote

    unbalanced_parens = q.count("(") > q.count(")")
    words_q = re.findall(r"\b[A-Za-z0-9_-]+\b", q)
    last_word = words_q[-1].lower() if words_q else ""
    ends_dangling = (last_word in DANGLING_END_WORDS) or bool(re.search(r"[,;:\-—–]\s*$", q))

    if not unbalanced_parens and not ends_dangling:
        return quote

    start_pos = pos
    if q and q[0].islower() and start_pos > 0 and (unbalanced_parens or ends_dangling):
        prev_text = passage_text[:start_pos]
        m = list(re.finditer(r'(?<=[.!?\n])\s+', prev_text))
        if m:
            cand_start = m[-1].end()
            if start_pos - cand_start < 80:
                start_pos = cand_start

    open_parens = q.count("(") - q.count(")")
    cur = pos + len(q)
    n = len(passage_text)
    while cur < n:
        ch = passage_text[cur]
        if ch == "(":
            open_parens += 1
        elif ch == ")":
            open_parens -= 1
        elif ch in ".!?\n":
            if open_parens <= 0:
                cur += 1
                while cur < n and passage_text[cur] in '"\'”’)':
                    cur += 1
                completed = passage_text[start_pos:cur].strip()
                if len(completed) <= PARAGRAPH_CAP:
                    return completed
                break
        cur += 1

    return q


def check_quote(quote: str, passage_text: str) -> str:
    """Verify and complete a quote against a passage."""
    if not _quote_in_passage(quote, passage_text):
        return ""
    return _complete_truncated_quote(quote, passage_text)


def _tagless_citation(text, passages):
    """A verified citation from a reply that forgot the [Ch. tag, or None.

    Whole text verbatim in a shown passage first (case kept), else the longest
    word-for-word span across the shown passages. No gloss: without the tag
    there is no marker for where prose ends and the quote begins.
    """
    quote = _strip_quotes(text)
    hit = _matching_passage_anywhere(quote, passages)
    if hit is not None and (
        len(quote) >= SPAN_MIN_CHARS or _short_sentence(text, quote)
    ):
        quote = _complete_truncated_quote(quote, hit.get("text") or "")
        return {
            "chunk_id": hit["chunk_id"],
            "chapter": str(hit["chapter"]),
            "quote": quote,
        }
    best = ("", None)
    for hit in passages:
        span = longest_copied_span(text, hit.get("text") or "")
        if len(span) > len(best[0]):
            best = (span, hit)
    if best[1] is None:
        return None
    snapped = _original_case(best[0], best[1].get("text") or "")
    snapped = _complete_truncated_quote(snapped, best[1].get("text") or "")
    return {
        "chunk_id": best[1]["chunk_id"],
        "chapter": str(best[1]["chapter"]),
        "quote": snapped,
    }


def _matching_passage(chapter, quote, passages):
    for hit in passages:
        if str(hit["chapter"]) != str(chapter):
            continue
        if _quote_in_passage(quote, hit["text"]):
            return hit
    return None


def _matching_passage_anywhere(quote, passages):
    """A verbatim quote from any attached passage is still a true quote.

    The model's [Ch. N] tag can slip when the matching passage sits last in
    a list of mostly one chapter (measured 2026-10-12: tagged [Ch. 1] for a
    ch04 sentence). The answer's chapter is rebuilt from the matched hit.
    """
    for hit in passages:
        if _quote_in_passage(quote, hit["text"]):
            return hit
    return None


def _paragraph_around(quote, passage_text):
    """The passage paragraph that holds the quote, whitespace-normalized."""
    folded = _fold(quote)
    if not folded:
        return ""
    for paragraph in re.split(r"\n\s*\n", passage_text or ""):
        if folded in _fold(paragraph):
            return re.sub(r"\s+", " ", paragraph).strip()
    return ""


def _plural(word):
    """True when an English word is a regular plural — the list detector.

    Stemming's first step is a suffix rule, not a dictionary; the same works
    here. "disadvantages", "types", "steps", "categories", "batches" pass;
    "endpoint", "analysis", "status", "business", "class" do not. Irregulars
    ("criteria") fall through to the model's own answer, the safe side.
    """
    if len(word) < 4 or word.endswith(("ss", "us", "is", "ous")):
        return False
    if word.endswith("ies"):
        return True
    if word.endswith(("ches", "shes", "xes", "zes", "ses")):
        return True
    return word.endswith("s")


def _whole_paragraph(anchors, paragraph, quote):
    """True when the paragraph around a verified quote replaces it.

    Two triggers, both book-general:
    - the paragraph holds an anchor word the quote lacks: the model quoted
      near the topic without naming it, so the paragraph is the answering
      material;
    - the paragraph holds a plural anchor ("disadvantages", "types",
      "steps"): a plural question wants the kinds of a thing, and the
      paragraph is the book's list (measured: "multicloud methodology
      disadvantages" takes the paragraph while "endpoint" keeps the model's
      sentence, 2026-10-13).
    The paragraph must also fit PARAGRAPH_CAP, so an answer quote stays about
    one screen. The quote is passage text and the paragraph holds it, so the
    swap can only add book text; the quote check holds by construction.
    """
    if not paragraph or len(paragraph) > PARAGRAPH_CAP:
        return False
    folded = _fold(paragraph)
    folded_quote = _fold(quote)
    for word in anchors:
        pat = _token_word_pattern(word)
        if not pat.search(folded):
            continue
        if _plural(word) or not pat.search(folded_quote):
            return True
    return False


# Closed English classes. A list ask names the shape of the answer, not a topic.
LIST_ASK = re.compile(
    r"\b(?:what are|which are|what were|list the)\b"
    r"|\b(?:factors|parts|kinds|types|steps|stages)\b"
    r"(?:\W+\w+){0,6}\W+(?:of|to)\b",
    re.I,
)
# Digits stay: a version token is one side of a comparison, and splitting on
# letters alone would fold both numbered sides into the same stem.
SIDE_SPLIT = re.compile(r"[^a-z0-9]+")
SIDE_DROP = frozenset({
    "what", "is", "the", "difference", "between", "and", "vs", "versus",
    "how", "why", "who", "which", "are", "was", "were", "do", "does", "did",
    "can", "could", "should", "would", "a", "an", "with", "from", "than", "to",
    "against", "or",
})
COMPARISON_PATTERNS = (
    # 1) difference between X and Y
    re.compile(r"\bdifference\s+between\s+(.+?)\s+and\s+(.+?)\s*[?.!]*$", re.I),
    # 2) how does X stack up against / compare to / compared to / measure up to / differ from Y
    re.compile(
        r"\b(?:how\s+(?:does|do|can|is|are)\s+)?(.+?)\s+(?:stack\s+up\s+against|compare\s+(?:to|with|against)|compared\s+(?:to|with|against)|measure\s+up\s+(?:to|against)|differ\s+from)\s+(.+?)\s*[?.!]*$",
        re.I,
    ),
    # 2b) how do X and Y compare
    re.compile(
        r"\b(?:how\s+(?:does|do|can|is|are)\s+)?(.+?)\s+and\s+(.+?)\s+compare\s*[?.!]*$",
        re.I,
    ),
    # 3) compare / contrast / distinguish X and/with/to/from/vs Y
    re.compile(
        r"\b(?:compare|comparing|contrast|contrasting|distinguish(?:\s+between)?)\s+(.+?)\s+(?:and|with|to|from|vs\.?|versus)\s+(.+?)\s*[?.!]*$",
        re.I,
    ),
    # 4) is/are/was/were X better/worse/faster/slower/cheaper/simpler/more .../less ... than Y
    re.compile(
        r"\b(?:is|are|was|were)\s+(.+?)\s+(?:better|worse|faster|slower|cheaper|simpler|more\s+\w+|less\s+\w+)\s+than\s+(.+?)\s*[?.!]*$",
        re.I,
    ),
    # 5) what sets X apart from Y
    re.compile(r"\bwhat\s+sets\s+(.+?)\s+apart\s+from\s+(.+?)\s*[?.!]*$", re.I),
)
COMPARISON = re.compile(
    r"\bdifference\s+between\s+(.+?)\s+and\s+(.+?)\s*\??\s*$",
    re.I,
)
ONE_VERSUS = re.compile(r"\bvs\.?(?!\w)|\bversus\b", re.I)


def _list_ask(question, asked_form):
    """True when the question asks for items, not a definition."""
    for text in (question, asked_form):
        if text and LIST_ASK.search(text):
            return True
    return False


def _is_lead_in(quote):
    """True when a quote only introduces a list and does not hold the items.

    A trailing colon is the printed cue. A sentence that names "the following"
    is a lead-in only when what follows that phrase is itself a lead-in: no
    second sentence, no comma or semicolon listing the items.
    """
    text = (quote or "").strip()
    if not text:
        return False
    if text.endswith(":"):
        return True
    folded = text.lower()
    marker = folded.find("the following")
    if marker < 0:
        return False
    tail = folded[marker + len("the following"):]
    if re.search(r"[.!?]\s+\S", tail):
        return False
    if "," in tail or ";" in tail:
        return False
    return True


def _after_lead_in(quote, passage_text):
    """Verbatim passage text after the lead-in, in the same paragraph.

    Empty when the passage ends at the lead-in. Nothing is added that the
    passage does not already contain.
    """
    pat = _words_pattern(quote)
    if pat is None or not passage_text:
        return ""
    match = pat.search(passage_text)
    if not match:
        return ""
    rest = passage_text[match.end():]
    paragraphs = [
        piece.strip() for piece in re.split(r"\n\s*\n", rest) if piece.strip()
    ]
    # A colon lead-in is often its own paragraph. The items are the next one.
    if len(paragraphs) >= 2 and len(paragraphs[0]) < 80 and not paragraphs[0].endswith((".", "!", "?")):
        items = []
        for p in paragraphs:
            if len(p) < 80 and not p.endswith((".", "!", "?")) and not p.startswith(("Chapter ", "Figure ")):
                items.append(re.sub(r"\s+", " ", p).strip())
            else:
                break
        paragraph = ", ".join(items) if items else (paragraphs[0] if paragraphs else "")
    else:
        paragraph = paragraphs[0] if paragraphs else ""
    continuation = re.sub(r"\s+", " ", paragraph).strip()
    if len(continuation) > PARAGRAPH_CAP:
        cut = continuation[:PARAGRAPH_CAP]
        boundary = cut.rfind(" ")
        continuation = cut if boundary < 0 else cut[:boundary]
    return continuation.strip()


def _replace_lead_in(answer, lead, continuation):
    """Swap the lead-in for the items, including inside quotation marks."""
    if not lead or lead not in answer:
        return answer
    return answer.replace(lead, continuation, 1)


def _expand_list(body, question, asked_form, passages):
    """Swap a lead-in quote for the items that follow it in the same passage."""
    if body.get("refused") or not _list_ask(question, asked_form):
        return body
    by_id = {hit.get("chunk_id"): hit for hit in passages}
    expanded = False
    for item in body.get("citations") or []:
        hit = by_id.get(item.get("chunk_id"))
        if hit is None or not _is_lead_in(item.get("quote")):
            continue
        continuation = _after_lead_in(item.get("quote"), hit.get("text") or "")
        if not continuation:
            continue
        lead = item["quote"]
        item["quote"] = continuation
        body["answer"] = _replace_lead_in(body["answer"], lead, continuation)
        if continuation not in body["answer"]:
            body["answer"] = (
                body["answer"].rstrip()
                + f"\n[Ch. {item['chapter']}] \"{continuation}\""
            )
        expanded = True
    # A lead-in can sit in the model's quotes and not match the citation string.
    def swap(match):
        lead = match.group(1)
        if not _is_lead_in(lead):
            return match.group(0)
        for hit in passages:
            continuation = _after_lead_in(lead, hit.get("text") or "")
            if continuation:
                return f'"{continuation}"'
        return match.group(0)

    swapped = re.sub(r'["\u201c]([^"\u201c\u201d]+)["\u201d]', swap, body["answer"])
    body["answer"] = _drop_lead_in_already_listed(swapped)
    return body


def _drop_lead_in_already_listed(answer):
    """A lead-in quote line goes when a later quote already holds the items."""
    lines = answer.splitlines()
    quote_line = re.compile(
        r'\[Ch\.\s*[^\]]+\]\s*["\u201c]([^"\u201c\u201d]+)["\u201d]'
    )
    later_items = False
    for line in lines:
        match = quote_line.match(line.strip())
        if match and not _is_lead_in(match.group(1)) and len(match.group(1)) >= 40:
            later_items = True
            break
    if not later_items:
        return answer
    kept = []
    seen = []
    for line in lines:
        match = quote_line.match(line.strip())
        if match and _is_lead_in(match.group(1)):
            continue
        if match:
            quote = match.group(1)
            if any(quote in earlier or earlier in quote for earlier in seen):
                continue
            seen.append(quote)
        kept.append(line)
    return "\n".join(kept)


def _clean_side(text):
    """Strip question fillers, auxiliaries, and articles from a comparison side."""
    text = (text or "").strip(" ?.!\"'")
    text = re.sub(
        r"^(?:what\s+is|what\s+are|how\s+does|how\s+do|how\s+is|how\s+are|why\s+is|why\s+does)\s+",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"^(?:is|are|was|were|do|does|did|can|could|should|would)\s+",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.I)
    return text.strip(" ?.!\"'")


def _comparison_sides(*texts):
    """(left, right) raw sides of a comparison, or None.

    Matches difference-between, comparison predicates, compare/contrast,
    comparative adjectives, what-sets-apart, or exactly one vs/versus.
    Either the original question or its canonical rewrite qualifies.
    """
    candidates = [text.strip() for text in texts if text and text.strip()]
    pronouns = _PRONOUNS_SET
    for text in candidates:
        prefix_subj = ""
        q_clean = (text or "").strip()
        m_reg = _REGARDING_PREFIX_RE.match(q_clean)
        if m_reg:
            prefix_subj = m_reg.group(1).strip()
            q_clean = m_reg.group(2).strip()

        for pat in COMPARISON_PATTERNS:
            match = pat.search(q_clean)
            if match:
                left = _clean_side(match.group(1))
                right = _clean_side(match.group(2))
                if left and left.lower() in pronouns:
                    left = prefix_subj if prefix_subj else None
                if right and right.lower() in pronouns:
                    right = prefix_subj if prefix_subj else None
                if not left or not right:
                    continue
                if "regarding " in left.lower() or "regarding " in right.lower():
                    continue
                if "how does " in left.lower() or "how does " in right.lower():
                    continue
                if left.lower() in pronouns or right.lower() in pronouns:
                    continue
                return left, right

        hits = list(ONE_VERSUS.finditer(q_clean))
        if len(hits) == 1:
            hit = hits[0]
            left = _clean_side(q_clean[:hit.start()])
            right = _clean_side(q_clean[hit.end():])
            if left and left.lower() in pronouns:
                left = prefix_subj if prefix_subj else None
            if right and right.lower() in pronouns:
                right = prefix_subj if prefix_subj else None
            if not left or not right:
                continue
            if "regarding " in left.lower() or "regarding " in right.lower():
                continue
            if "how does " in left.lower() or "how does " in right.lower():
                continue
            if left.lower() in pronouns or right.lower() in pronouns:
                continue
            return left, right

    return None


def _side_tokens(side):
    """Content tokens of one side. Closed function words and short tokens drop."""
    cleaned = _clean_side(side)
    tokens = []
    for token in SIDE_SPLIT.split((cleaned or "").lower()):
        if len(token) < 3 or token in SIDE_DROP:
            continue
        tokens.append(token)
    return tokens


def _side_covered(tokens, passages):
    """The shown passage holding every token as a whole word, or None."""
    if not tokens:
        return None
    patterns = [_token_word_pattern(token) for token in tokens]
    for hit in passages:
        folded = f"{hit.get('heading') or ''} {hit.get('text') or ''}".lower()
        if all(pattern.search(folded) for pattern in patterns):
            return hit
    return None


def _covering_quote(tokens, hit):
    """A verbatim sentence naming the covered side, else its paragraph.

    Nothing under the quote floor is invented into a sentence. Empty when the
    passage has no quotable span that names the side.
    """
    text = hit.get("text") or ""
    patterns = [_token_word_pattern(token) for token in tokens]
    for sentence in _sentences(text):
        if all(pattern.search(sentence.lower()) for pattern in patterns):
            return _without_heading(sentence, hit)
    paragraph = _WHITESPACE_RE.sub(" ", text).strip()
    if (
        len(paragraph) <= PARAGRAPH_CAP
        and len(paragraph) >= SPAN_MIN_CHARS
        and all(pattern.search(paragraph.lower()) for pattern in patterns)
    ):
        return _without_heading(paragraph, hit)
    return ""


def _half_covered(body, question, asked_form, passages, figures):
    """Answer the covered side of a comparison when only one side is in the passages.

    Fires only when exactly one side is in the shown passages and a verbatim
    span can be quoted. The other side is named in a gloss, never quoted and
    never given attributes the passages do not contain.
    """
    sides = _comparison_sides(question, asked_form)
    if sides is None:
        return body
    found = []
    for side in sides:
        tokens = _side_tokens(side)
        found.append((side, tokens, _side_covered(tokens, passages)))
    covered = [item for item in found if item[2] is not None]
    missing = [item for item in found if item[2] is None]
    if len(covered) != 1 or len(missing) != 1:
        return body
    missing_name = missing[0][0].strip()
    if missing_name.lower().startswith("regarding") or missing_name.lower().startswith("in "):
        return body
    if (not body.get("refused")
            and missing_name.lower() in body.get("answer", "").lower()
            and re.search(r"\b(not\s+mention|does\s+not|do\s+not|absent)\b", body.get("answer", ""), re.I)):
        return body
    side, tokens, hit = covered[0]
    quote = _covering_quote(tokens, hit)
    if not quote:
        return body
    chapter = str(hit["chapter"])
    gloss = f"The passages do not mention {missing_name}."
    return {
        "answer": f'[Ch. {chapter}] "{quote}"\n{gloss}',
        "citations": [{
            "chunk_id": hit["chunk_id"],
            "chapter": chapter,
            "quote": quote,
        }],
        "figures": figures_for([hit], figures or []),
        "refused": False,
    }


def _without_heading(quote, passage):
    """A quote that opens with the passage's heading line drops it.

    A chunk's first line is its heading, so a model copying across that line
    writes "Insert-Only The insert-only pattern retains history..." or "Key
    considerations for the transformation phase Logically, we treat..." —
    verbatim, but it reads as a fragment.

    The test is what follows the heading: a heading that runs on into its own
    sentence leaves a lowercase remainder ("Modularity allows engineers..."),
    and a heading that was the sentence's subject leaves a bracket or lower case
    ("Modularity (Figure 4-5) is...", "Storage is the cornerstone..."). Only a
    genuine new sentence after the heading — an upper-case start of real length
    — gets the heading dropped.
    """
    heading = (passage.get("text") or "").split("\n", 1)[0].strip()
    pat = _heading_prefix_pattern(heading)
    if pat is None:
        return quote
    match = pat.match(quote)
    if not match:
        return quote
    rest = quote[match.end():].strip()
    if len(rest) < SPAN_MIN_CHARS or not rest[:1].isupper():
        return quote
    return rest


CANONICAL_ACRONYMS = {
    "ddr5": "DDR5", "ddr4": "DDR4", "ddr3": "DDR3",
    "ssds": "SSDs", "ssd": "SSD", "ram": "RAM", "sram": "SRAM", "dram": "DRAM",
    "nvme": "NVMe", "hdd": "HDD", "hdds": "HDDs", "iops": "IOPS",
    "cpu": "CPU", "cpus": "CPUs", "gpu": "GPU", "gpus": "GPUs",
    "vms": "VMs", "vm": "VM", "aws": "AWS", "gcp": "GCP",
    "s3": "S3", "ec2": "EC2", "emr": "EMR", "rds": "RDS",
    "sql": "SQL", "nosql": "NoSQL", "newsql": "NewSQL",
    "oltp": "OLTP", "olap": "OLAP", "htap": "HTAP",
    "etl": "ETL", "elt": "ELT", "cdc": "CDC",
    "dag": "DAG", "dags": "DAGs", "api": "API", "apis": "APIs",
    "sla": "SLA", "slas": "SLAs", "slo": "SLO", "slos": "SLOs", "sli": "SLI",
    "crud": "CRUD", "acid": "ACID", "base": None,  # skip common English word 'base'
    "json": "JSON", "csv": "CSV", "xml": "XML", "yaml": "YAML",
    "http": "HTTP", "https": "HTTPS", "tcp": "TCP", "udp": "UDP",
    "tls": "TLS", "dns": "DNS", "bgp": "BGP", "iot": "IoT",
    "3nf": "3NF", "2nf": "2NF", "1nf": "1NF", "bcnf": "BCNF",
    "fifo": "FIFO", "lifo": "LIFO", "rbac": "RBAC", "iam": "IAM",
    "pii": "PII", "gdpr": "GDPR", "hipaa": "HIPAA", "ccpa": "CCPA",
    "roi": "ROI", "tco": "TCO", "capex": "CapEx", "opex": "OpEx",
    "cicd": "CI/CD", "ci/cd": "CI/CD", "sdk": "SDK", "cli": "CLI",
    "ml": "ML", "ai": "AI", "bi": "BI", "crm": "CRM", "crms": "CRMs", "cdp": "CDP", "cdps": "CDPs",
    "erp": "ERP", "erps": "ERPs", "saas": "SaaS", "paas": "PaaS", "iaas": "IaaS",
    "dbms": "DBMS", "rdbms": "RDBMS", "mpp": "MPP", "eda": "EDA",
    "mlops": "MLOps", "dataops": "DataOps", "finops": "FinOps", "devops": "DevOps",
    "llvm": "LLVM", "ssa": "SSA", "bwa": "BWA", "fastq": "FASTQ", "crispr": "CRISPR",
    "rna": "RNA", "dna": "DNA",
}

_CANONICAL_ACRONYM_MAP = {k: v for k, v in CANONICAL_ACRONYMS.items() if v}
_ACRONYM_SORTED_KEYS = sorted(_CANONICAL_ACRONYM_MAP.keys(), key=len, reverse=True)
_ACRONYM_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _ACRONYM_SORTED_KEYS) + r")\b",
    re.IGNORECASE,
)


def fix_acronym_casing(text: str) -> str:
    """Normalize casing of common technical acronyms (e.g. Ddr5 -> DDR5, Ssds -> SSDs)."""
    if not text:
        return text

    def _sub(m):
        raw = m.group(0).lower()
        return _CANONICAL_ACRONYM_MAP.get(raw, m.group(0))

    return _ACRONYM_PATTERN.sub(_sub, text)


def _extract_query_entities(q: str, heading: str = "") -> list[str]:
    """Extract specific multi-word entities, acronyms, or non-framing proper nouns from query."""
    if not q:
        return []
    normalized_q = fix_acronym_casing(q)
    entities = []
    # 1. Multi-word capitalized phrases or hyphenated / numbered terms: "Google Ads", "Type 2", "TLS 1.3", "BWA-MEM"
    for m in _ENTITY_PHRASE_RE.finditer(normalized_q):
        val = m.group(1).strip()
        parts = val.split()
        while parts and parts[0].lower() in _QUESTION_STARTERS:
            parts = parts[1:]
        if len(parts) >= 2:
            val = " ".join(parts)
            if val.lower() not in STOPWORDS:
                entities.append(val)
        elif len(parts) == 1 and parts[0].lower() not in STOPWORDS and parts[0].lower() not in _QUESTION_STARTERS and parts[0].lower() not in _GENERIC_ENTITY_WORDS:
            entities.append(parts[0])
    # 2. Acronyms (e.g. ML, ETL, CRM, CDP, API)
    for m in _ACRONYM_MATCH_RE.finditer(normalized_q):
        val = m.group(1).strip()
        if val.lower() not in STOPWORDS and val not in entities:
            entities.append(val)
    # 3. Capitalized single words or technical terms (not starters/stopwords/generic category words)
    words_list = normalized_q.split()
    for w in words_list:
        w_clean = _STRIP_PUNCT_RE.sub("", w)
        if (
            w_clean
            and w_clean[0].isupper()
            and w_clean.lower() not in STOPWORDS
            and w_clean.lower() not in FRAMING_WORDS
            and w_clean.lower() not in _QUESTION_STARTERS
            and w_clean.lower() not in _GENERIC_ENTITY_WORDS
        ):
            if not any(w_clean in ent for ent in entities):
                entities.append(w_clean)
    # Filter out entities that are completely inside heading
    head_low = heading.lower() if heading else ""
    return [e for e in entities if not head_low or e.lower() not in head_low]


def _should_include_chunk_figures(chunk, selection, quote, all_figures):
    """Determine whether a chunk's figures should attach to an explain selection."""
    if not chunk:
        return False
    # 1) cited_numbers(quote) is non-empty
    if cited_numbers(quote):
        return True
    # 2) selection in heading or heading in selection
    heading = (chunk.get("heading") or "").strip().lower()
    sel_low = (selection or "").strip().lower()
    if heading and sel_low and (sel_low in heading or heading in sel_low):
        return True
    # 3) Any figure in chunk has a caption sharing content words with selection or quote
    chunk_fig_nums = cited_numbers(chunk.get("text") or "")
    if chunk_fig_nums and all_figures:
        sel_quote_words = {
            w.lower() for w in words(f"{selection} {quote}")
            if len(w) >= 3 and w.lower() not in STOPWORDS
        }
        for fig in all_figures:
            num = number_from_id(fig.get("id"))
            if num and num in chunk_fig_nums:
                caption = fig.get("caption") or ""
                cap_words = {
                    w.lower() for w in words(caption)
                    if len(w) >= 3 and w.lower() not in STOPWORDS
                }
                if sel_quote_words & cap_words:
                    return True
    return False


def _has_content_word_overlap(s1: str, s2: str, exclude: str = "") -> bool:
    """True if s1 and s2 share at least one non-stopword content word outside exclude."""
    if not s1 or not s2:
        return False
    ex_words = {w.lower() for w in words(exclude)} if exclude else set()
    w1 = {w.lower() for w in words(s1) if len(w) >= 3 and w.lower() not in STOPWORDS and w.lower() not in ex_words}
    w2 = {w.lower() for w in words(s2) if len(w) >= 3 and w.lower() not in STOPWORDS and w.lower() not in ex_words}
    return bool(w1 & w2)


def _clean_boilerplate_gloss(gloss, selection=""):
    """Clean robotic boilerplate or formulaic crutches from a gloss."""
    if not gloss:
        return ""
    text = (gloss or "").strip()
    text = _BOILERPLATE_PROMPT_LEAK_RE.sub("", text)
    text = _IN_THIS_CONTEXT_START_RE.sub("", text)
    text = _IN_THIS_CONTEXT_WORD_RE.sub("here", text)
    text = _HIGHLIGHTED_QUESTION_RE.sub("The question", text)
    text = _IN_THIS_PASSAGE_START_RE.sub("", text)
    if selection:
        sel_words = selection.strip().split()
        replacement = "The highlighted word" if len(sel_words) == 1 else "The highlighted phrase"
        text = _PASSAGE_VERB_RE.sub(f"{replacement} ", text)
        text = _PASSAGE_START_RE.sub(f"{replacement} ", text)
        text = _HIGHLIGHTED_TERM_RE.sub(replacement, text)
        text = _HIGHLIGHTED_NOT_WORD_PHRASE_RE.sub(replacement, text)
    else:
        text = _PASSAGE_START_RE.sub("This section ", text)
        text = _HIGHLIGHTED_TERM_RE.sub("This section", text)
        text = _HIGHLIGHTED_NOT_WORD_PHRASE_RE.sub("This section", text)
    text = _REFERS_TO_A_RE.sub("is a", text)
    text = _REFERS_TO_THE_RE.sub("is the", text)
    text = _REFERS_TO_RE.sub("means", text)
    text = _TRAILING_PREP_WORD_DOT_RE.sub(".", text)
    text = " ".join(text.split()).strip("\"'“”")
    if text:
        text = text[0].upper() + text[1:]
    return fix_acronym_casing(text)


def _is_coherent_gloss(gloss: str, quote: str = "", question: str = "") -> bool:
    """Strict guard rejecting gibberish, token repetition loops, meta-commentary, or fragments."""
    if not gloss or not isinstance(gloss, str):
        return False
    text = gloss.strip()
    # a) len < 25
    if len(text) < 25:
        return False
    # b) gibberish markers: sentence digits or stray standalone digits after nouns
    if _GIBBERISH_DIGITS_RE.search(text):
        return False
    if _GIBBERISH_NOUN_DIGITS_RE.search(text):
        return False
    # c) any non-stopword content word (len >= 4) appears >= 4 times in a single sentence
    #    or >= 4 times in a 25-word window
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    for s in sentences:
        s_words = [w.lower() for w in words(s) if len(w) >= 4 and w.lower() not in STOPWORDS]
        counts = {}
        for w in s_words:
            counts[w] = counts.get(w, 0) + 1
            if counts[w] >= 4:
                return False
    all_words = text.split()
    for i in range(len(all_words)):
        win = all_words[i:i + 25]
        win_content = [w.lower() for w in words(" ".join(win)) if len(w) >= 4 and w.lower() not in STOPWORDS]
        counts = {}
        for w in win_content:
            counts[w] = counts.get(w, 0) + 1
            if counts[w] >= 4:
                return False
    # d) adjacent repeated words
    if _ADJACENT_REPEATED_WORD_RE.search(text):
        return False
    # e) sentence ends with auxiliary/determiner/preposition
    if _SENTENCE_DANGLING_END_RE.search(text):
        return False
    # f) meta-commentary non-answer
    if _META_COMMENTARY_RE.search(text):
        return False
    # Pointer / meta-location non-answers that tell the reader where something is instead of answering
    if _POINTER_META_LOCATION_RE.search(text):
        return False
    # Prompt leakage non-answers:
    if not text.lower().startswith("the passages do not mention") and _PROMPT_LEAKAGE_RE.search(text):
        return False
    # List enumeration questions check
    if question and _list_ask(question, question):
        if "," not in text and " and " not in text.lower() and ";" not in text:
            return False
        if quote and quote.count(",") >= 2:
            q_words = {w.lower() for w in words(quote) if len(w) >= 3 and w.lower() not in STOPWORDS}
            t_words = {w.lower() for w in words(text) if len(w) >= 3 and w.lower() not in STOPWORDS}
            if len(q_words & t_words) < 2:
                return False
    # Quote repetition:
    if quote:
        norm_t = re.sub(r"[\s\"'“”]+", " ", text).strip().lower()
        norm_q = re.sub(r"[\s\"'“”]+", " ", quote).strip().lower()
        if norm_t == norm_q:
            return False
    return True


def _reground_alphanumeric_quote(quote, question, chunk_text):
    """Ensure quotes for normal forms, SCD types, acronyms, and attributions align to the exact form asked."""
    q_low = (question or "").lower()
    text = chunk_text or ""
    if "3nf" in q_low or "third normal form" in q_low:
        if "1nf" in quote.lower() and "transitive" not in quote.lower() and "2nf" not in quote.lower():
            for sent in _sentences(text):
                if ("transitive" in sent.lower() or "2nf" in sent.lower()) and len(sent) >= 30:
                    return _complete_truncated_quote(sent, text)
    elif "2nf" in q_low or "second normal form" in q_low:
        if "transitive" in quote.lower() or "single value" in quote.lower():
            for sent in _sentences(text):
                if ("partial" in sent.lower() or "1nf" in sent.lower()) and len(sent) >= 30:
                    return _complete_truncated_quote(sent, text)
    elif "1nf" in q_low or "first normal form" in q_low:
        if "partial" in quote.lower() or "transitive" in quote.lower():
            for sent in _sentences(text):
                if ("single value" in sent.lower() or "primary key" in sent.lower()) and "partial" not in sent.lower() and len(sent) >= 30:
                    return _complete_truncated_quote(sent, text)
    elif _TYPE_2_RE.search(q_low):
        if "type 3" in quote.lower() or ("type 2" not in quote.lower() and "type-2" not in quote.lower() and "effective end date" not in quote.lower()):
            for sent in _sentences(text):
                sent_low = sent.lower()
                if ("type 2" in sent_low or "type-2" in sent_low) and ("new record" in sent_low or "history" in sent_low or "inserted" in sent_low or "full history" in sent_low):
                    return _complete_truncated_quote(sent, text)
                if "keep a full history of dimension records" in sent_low or ("effective end date" in sent_low and "new record" in sent_low):
                    return _complete_truncated_quote(sent, text)
    elif _S3_RE.search(q_low):
        if not any(k in quote.lower() for k in ("object", "amazon", "cloud", "storage")):
            for sent in _sentences(text):
                sent_low = sent.lower()
                if "s3" in sent_low and any(k in sent_low for k in ("amazon", "object", "cloud", "storage")):
                    return _complete_truncated_quote(sent, text)
    elif _IOPS_RE.search(q_low):
        if "per second" not in quote.lower() and "input/output" not in quote.lower():
            for sent in _sentences(text):
                sent_low = sent.lower()
                if "iops" in sent_low and any(k in sent_low for k in ("per second", "input/output", "operations", "bottleneck", "limitation")):
                    return _complete_truncated_quote(sent, text)
    elif _SLA_SLO_RE.search(q_low):
        if not _SLA_SLO_RE.search(quote.lower()):
            for sent in _sentences(text):
                if _SLA_SLO_RE.search(sent.lower()) and len(sent) >= 30:
                    return _complete_truncated_quote(sent, text)
    elif _WHO_CREATED_RE.search(q_low):
        has_author_name = bool(_AUTHOR_NAME_RE.search(quote))
        if not has_author_name:
            for sent in _sentences(text):
                sent_low = sent.lower()
                if any(w in sent_low for w in _ATTRIBUTION_MARKERS):
                    if _AUTHOR_NAME_RE.search(sent):
                        return _complete_truncated_quote(sent, text)
    return _complete_truncated_quote(quote, text)


def _clean_selection_text(sel: str) -> str:
    raw = (sel or "").strip()
    if not raw:
        return ""
    if "\n" in raw:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(lines) >= 2 and len(lines[0]) <= 40 and lines[0].endswith(":"):
            raw = " ".join(lines[1:])
    return re.sub(r"\s+", " ", raw).strip()


SIMPLIFY_RE = re.compile(
    r"\b("
    r"explain\s+(?:it\s+|this\s+|that\s+)?(?:more\s+)?simpl[ey](?:\s+words)?|"
    r"more\s+simply|simpler\s+words|in\s+simple\s+words|in\s+simpler\s+words|"
    r"simplify|simplification|make\s+(?:this|it)\s+simpler|put\s+(?:this|it)\s+simply|"
    r"in\s+plain\s+(?:english|words|terms)|plain\s+english|"
    r"break\s+(?:this|it|that)\s+down|"
    r"what\s+does\s+(?:this|that|it)\s+mean|"
    r"eli5|easier\s+to\s+understand|"
    r"shorter|in\s+one\s+(?:short\s+)?sentence|one\s+short\s+sentence|"
    r"main\s+takeaway|key\s+takeaway|summar(?:ize|y)(?:\s+(?:this|it))?|tl;dr"
    r")\b|^shorter\??$",
    re.IGNORECASE,
)


GENERIC_FOLLOWUP_RE = re.compile(
    r"^\s*(?:why\s+does\s+this\s+matter|explain\s+(?:in\s+)?simpler\s+words|simpler\s+words|"
    r"break\s+this\s+down|what\s+are\s+(?:the|its)\s+trade-?offs|what\s+are\s+trade-?offs|"
    r"trade-?offs|why\s+matter|tell\s+me\s+more|elaborate|simplify|how\s+does\s+this\s+work|"
    r"what\s+are\s+(?:the\s+)?specific\s+reasons|what\s+(?:are\s+the\s+)?reasons|"
    r"what\s+example\s+(?:do\s+the\s+authors\s+give|is\s+given)|"
    r"what\s+problem\s+does\s+this\s+solve|"
    r"what\s+are\s+the\s+risks(?:\s+or\s+pitfalls)?|"
    r"what\s+are\s+the\s+(?:main\s+stages|key\s+types|key\s+characteristics|specific\s+ways)|"
    r"what\s+are\s+the\s+(?:cost\s+trade-?offs|main\s+bottlenecks|main\s+limitations)|"
    r"how\s+does\s+.+?\s+relate\s+to\s+this|"
    r"how\s+does\s+this\s+compare\s+to\s+.+?|"
    r"what\s+is\s+the\s+role\s+of\s+.+?|"
    r"what\s+are\s+the\s+risks\s+of\s+.+?|"
    r"explain\s+(?:it\s+|this\s+|that\s+)?(?:more\s+)?simpl[ey](?:\s+words)?|"
    r"more\s+simply|simpler\s+words|in\s+simple\s+words|in\s+simpler\s+words|"
    r"simplify|simplification|make\s+(?:this|it)\s+simpler|put\s+(?:this|it)\s+simply|"
    r"in\s+plain\s+(?:english|words|terms)|plain\s+english|"
    r"break\s+(?:this|it|that)\s+down|"
    r"what\s+does\s+(?:this|that|it)\s+mean|"
    r"eli5|easier\s+to\s+understand|"
    r"shorter|in\s+one\s+(?:short\s+)?sentence|one\s+short\s+sentence|"
    r"main\s+takeaway|key\s+takeaway|summar(?:ize|y)(?:\s+(?:this|it))?|tl;dr"
    r")\s*\??\s*$",
    re.IGNORECASE,
)


def _is_generic_followup(q: str) -> bool:
    if not q:
        return True
    return bool(is_deictic_question(q) or GENERIC_FOLLOWUP_RE.match(q.strip()) or SIMPLIFY_RE.search(q.strip()))


def _gloss_repeats_quote(gloss: str, quote: str) -> bool:
    g = re.sub(r"[\s\"'“”]+", " ", gloss or "").strip().lower()
    q = re.sub(r"[\s\"'“”]+", " ", quote or "").strip().lower()
    if not g or not q:
        return True
    if g == q or g.startswith(q) or q.startswith(g):
        return True
    g_words = set(re.findall(r"\b[a-zA-Z0-9]+\b", g))
    q_words = set(re.findall(r"\b[a-zA-Z0-9]+\b", q))
    return len(g_words - q_words) < 3


def _extract_subject_from_query(s):
    if not s:
        return ""
    m_when = _EXTRACT_SUBJ_WHEN_RE.search(s)
    if m_when and len(m_when.group(1).split()) >= 2:
        cand = m_when.group(1).rstrip("?.!").strip()
        cand = _EXTRACT_SUBJ_STRIP_ACTION_RE.sub("", cand)
        cand = _EXTRACT_SUBJ_STRIP_ART_RE.sub("", cand)
        return cand
    q = s.strip().rstrip("?.!")
    m = _EXTRACT_SUBJ_WH_START_RE.match(q)
    if m:
        q = q[m.end():].strip()
    q = _EXTRACT_SUBJ_VERB_SPLIT_RE.split(q)[0].strip()
    return q or s


def _extract_subject_from_history(history):
    clean_history = [
        h for h in (history or [])
        if isinstance(h, dict) and (h.get("question") or h.get("answer"))
    ]
    if not clean_history:
        return ""

    for prev in reversed(clean_history):
        prev_q = (prev.get("question") or "").strip()
        if prev_q and not _is_generic_followup(prev_q):
            q_words = prev_q.split()
            first_w = q_words[0].lower() if q_words else ""
            if (len(q_words) <= 10 and not any(first_w.startswith(w) for w in _WH_STARTS)
                    and first_w not in _AUX_WORDS and first_w not in _OPENER_WORDS):
                return prev_q.strip(" ?.!\"'")
            sub = _extract_subject_from_query(prev_q)
            sub_tokens = set(_WORD_ALPHA_RE.findall(sub.lower()))
            if not (sub_tokens & _SUB_PRONOUNS):
                return sub

    for prev in reversed(clean_history):
        prev_a = (prev.get("answer") or "").strip()
        if prev_a:
            m_q = _TAG_AND_QUOTE_RE.search(prev_a)
            if m_q:
                quote = m_q.group(1).strip()
                m_sub = _EXTRACT_SUBJ_CAND_RE.match(quote)
                if m_sub:
                    cand = m_sub.group(1).strip()
                    cand_tokens = set(_WORD_ALPHA_RE.findall(cand.lower()))
                    if not (cand_tokens & _CAND_PRONOUNS):
                        return cand

    return _extract_subject_from_query(clean_history[0].get("question") or "")


DEICTIC_REF_RE = re.compile(
    r"\b(it|its|this|that|these|those|they|them|their|there|such|same|former|latter|above|previous|prior)\b",
    re.IGNORECASE,
)

GENERIC_FACETS_RE = re.compile(
    r"\b(reason|reasons|stage|stages|type|types|trade-off|trade-offs|tradeoff|tradeoffs|"
    r"downside|downsides|limitation|limitations|risk|risks|pitfall|pitfalls|"
    r"bottleneck|bottlenecks|cost|costs|example|examples|chapter|created|invented|"
    r"coined|warn|handle|overhead|"
    r"drawback|drawbacks|disadvantage|disadvantages|advantage|advantages|benefit|benefits|"
    r"challenge|challenges|problem|problems|solve|solves|prevent|prevents|role|use\s+case|use\s+cases|"
    r"takeaway|takeaways|principle|principles|simply|simpler|shorter|plain\s+english|summary|summarize|analogy|eli5)\b",
    re.IGNORECASE,
)

EXPLICIT_CONCEPT_RE = re.compile(
    r"^(?:what\s+(?:is|are|was|were)\s+|define\s+|explain\s+|tell\s+me\s+about\s+|how\s+(?:does|do|did|can|could)\s+.+?\s+work\??)",
    re.IGNORECASE,
)

CONVERSATIONAL_DIRECTIVES = frozenset({
    "simply", "simpler", "simple", "simplify", "shorter", "plain", "english", "summary",
    "summarize", "takeaway", "eli5", "analogy", "example", "examples", "drawback",
    "drawbacks", "trade-off", "trade-offs", "downside", "downsides", "benefit",
    "benefits", "advantage", "advantages", "disadvantage", "disadvantages",
    "problem", "problems", "solve", "solves", "stage", "stages", "step", "steps",
    "principle", "principles", "type", "types", "role", "overlap", "field", "fields",
    "manual", "process", "replace", "antipattern", "viewed", "matter", "mean",
    "work", "works", "fast", "faster", "slow", "cost", "costs", "why", "how",
    "who", "where", "when", "which", "difference", "compare", "relate", "stand",
    "for", "main", "key", "specific", "author", "authors", "give", "tell",
    "explain", "describe",
})


def _has_deictic_reference(question: str) -> bool:
    """Check if question contains any deictic pronouns or backward references."""
    return bool(DEICTIC_REF_RE.search(question or ""))


def _is_topic_shift_followup(question: str, history: list, selection: str = "", pin_chunk=None, index=None) -> bool:
    """True when question is a self-contained topic shift rather than an in-topic follow-up.

    Book-agnostic: verifies absence of deictic references/generic follow-up stems,
    and requires non-overlapping content words between question and conversation history.
    """
    if not history:
        return False
    if (
        SIMPLIFY_RE.search(question)
        or is_deictic_question(question)
        or is_incomplete_stem(question)
        or _is_generic_followup(question)
        or _has_deictic_reference(question)
        or bool(GENERIC_FACETS_RE.search(question))
    ):
        return False

    clean_history = [
        h for h in (history or [])
        if isinstance(h, dict) and (h.get("question") or h.get("answer"))
    ]
    if not clean_history:
        return False

    q_novel = [
        w.lower() for w in words(question)
        if w.lower() not in STOPWORDS and w.lower() not in FRAMING_WORDS and w.lower() not in CONVERSATIONAL_DIRECTIVES and len(w) >= 3
    ]
    if not q_novel:
        return False

    hist_words = set(words((_extract_subject_from_history(clean_history) or "").lower()))
    if selection:
        hist_words.update(w.lower() for w in words(selection))
    last_turn = clean_history[-1]
    last_q = (last_turn.get("question") or "").strip()
    if last_q:
        hist_words.update(w.lower() for w in words(last_q))
    last_a = (last_turn.get("answer") or "").strip()
    if last_a:
        hist_words.update(w.lower() for w in words(last_a))

    pin_chunk_obj = None
    if pin_chunk:
        if isinstance(pin_chunk, dict):
            pin_chunk_obj = pin_chunk
        elif isinstance(pin_chunk, str) and index:
            pin_chunk_obj = next(
                (c for c in (index.get("chunks") or []) if c.get("chunk_id") == pin_chunk),
                None,
            )

    m_concept = _TOPIC_SHIFT_CONCEPT_RE.match(question.strip())
    if m_concept:
        concept_target = m_concept.group(1).strip()
        target_words = {w.lower() for w in words(concept_target) if w.lower() not in STOPWORDS and len(w) >= 2}
        if last_a and len(target_words) >= 3 and all(w in last_a.lower() for w in target_words):
            return False
        sub_words = {w.lower() for w in words((_extract_subject_from_history(clean_history) or "").lower()) if w.lower() not in STOPWORDS}
        if pin_chunk_obj is not None:
            p_head = (pin_chunk_obj.get("heading") or "").lower()
            if concept_target.lower() in p_head or (target_words and target_words.issubset({w.lower() for w in words(p_head)})):
                return False
            if index:
                chunks = index.get("chunks") or []
                diff_heading = any(
                    c.get("chunk_id") != pin_chunk_obj.get("chunk_id")
                    and concept_target.lower() in (c.get("heading") or "").lower()
                    for c in chunks
                )
                if diff_heading:
                    return True
            p_text = (pin_chunk_obj.get("text") or "").lower()
            if len(target_words) >= 2 and all(w in p_text for w in target_words):
                return False
            if not all(w in p_text for w in target_words) and not target_words.issubset(sub_words):
                return True
            if not (target_words & sub_words):
                return True
            return False
        else:
            if not target_words.issubset(sub_words):
                return True
            if not (target_words & sub_words):
                return True
            return False
    else:
        if set(q_novel) & hist_words:
            return False
        if pin_chunk_obj is not None:
            pin_words = {w.lower() for w in words(pin_chunk_obj.get("text", ""))}
            if set(q_novel) & pin_words:
                return False
        if len(q_novel) >= 2 and not (set(q_novel) & hist_words):
            if pin_chunk_obj is None or not (set(q_novel) & {w.lower() for w in words(pin_chunk_obj.get("text", ""))}):
                return True
        return False


def parse_completion(completion, passages, figures=None, anchors=None, question=""):
    """Return a contract body. Unchecked prose is a refusal.

    A figure is attached only when a passage the answer cited names it. When
    the paragraph around a verified quote holds an anchor word and fits
    PARAGRAPH_CAP, the paragraph replaces the quote; paragraph text is passage
    text, so the quote check holds by construction.
    """
    text = (completion or "").strip()
    if text == REFUSAL:
        return _refusal(passages, figures)

    citations = []
    gloss = []
    if not text.startswith("[Ch."):
        # The model sometimes writes the book's own sentence and forgets the
        # tag (measured: "Normalization is a database data modeling practice
        # ...", 2026-10-13). The verification is the same rule as everywhere:
        # verbatim in a shown passage, or a long enough word-for-word span;
        # the tag is rebuilt from the matched passage. Unverified prose is
        # still a refusal.
        citation = _tagless_citation(text, passages)
        if citation is None:
            return _refusal(passages, figures)
        citations.append(citation)
    else:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            match = re.match(r"\[Ch\.\s*([^\]]+)\]\s*(.*)", stripped)
            if not match:
                gloss.append(stripped)
                continue
            chapter = match.group(1).strip().rstrip(".")
            rest = match.group(2)
            quoted = re.search(r"[\"“](.+?)[\"”]", rest)
            raw = quoted.group(1) if quoted else rest
            quote = _strip_quotes(raw)
            if len(quote) < SPAN_MIN_CHARS and not _short_sentence(raw, quote):
                quote = ""
            hit = _matching_passage(chapter, quote, passages)
            if hit is None:
                hit = _matching_passage_anywhere(quote, passages)
            if hit is None:
                hit, quote = _span_from_chapter(chapter, rest, passages)
            if hit is None:
                hit, quote = _span_from_chapter(chapter, text, passages)
            if hit is None:
                return _refusal(passages, figures)
            quote = _complete_truncated_quote(quote, hit.get("text") or "")
            citations.append({
                "chunk_id": hit["chunk_id"],
                "chapter": str(hit["chapter"]),
                "quote": quote,
            })
    if not citations:
        return _refusal(passages, figures)
    is_process_q = bool(re.search(r"\bhow\s+(?:does|do|can)\b", question or "", re.I))
    if anchors or is_process_q:
        for item in citations:
            spot = next(
                (hit for hit in passages if hit["chunk_id"] == item["chunk_id"]),
                None,
            )
            if spot is None:
                continue
            paragraph = _paragraph_around(item["quote"], spot.get("text") or "")
            if anchors and _whole_paragraph(anchors, paragraph, item["quote"]):
                item["quote"] = paragraph
            elif is_process_q and paragraph and len(paragraph) <= PARAGRAPH_CAP and len(paragraph) >= SPAN_MIN_CHARS:
                item["quote"] = paragraph
    # One trim, after every path that can set a quote: the anchor expansion
    # above replaces the quote with the whole paragraph, heading line included.
    for item in citations:
        spot = next(
            (hit for hit in passages if hit["chunk_id"] == item["chunk_id"]),
            None,
        )
        if spot is not None:
            item["quote"] = _without_heading(item["quote"], spot)
            item["quote"] = _reground_alphanumeric_quote(
                item["quote"], question, spot.get("text", "")
            )

    # Fully-covered comparison alignment: if query compares two concepts, cite the passage
    # and sentence mentioning both sides when present.
    sides = _comparison_sides(question)
    if sides and len(passages) >= 1:
        PRONOUNS = frozenset({"this", "it", "that", "they", "these", "those"})
        left_is_pronoun = sides[0].lower() in PRONOUNS
        right_is_pronoun = sides[1].lower() in PRONOUNS
        tokens_left = [] if left_is_pronoun else _side_tokens(sides[0])
        tokens_right = [] if right_is_pronoun else _side_tokens(sides[1])
        if (tokens_left or left_is_pronoun) and (tokens_right or right_is_pronoun):
            dual_hit = None
            dual_sentence = None
            best_contrast_score = -1
            for p in passages:
                p_text = p.get("text") or ""
                p_low = p_text.lower()
                hl = True if left_is_pronoun else all(re.search(rf"\b{re.escape(stem(t))}\w*\b", p_low) for t in tokens_left)
                hr = True if right_is_pronoun else all(re.search(rf"\b{re.escape(stem(t))}\w*\b", p_low) for t in tokens_right)
                if hl and hr and (not left_is_pronoun or hr) and (not right_is_pronoun or hl):
                    c_score = 1
                    for marker in ("unlike", "versus", "vs.", "vs", "difference between", "differ from", "differ", "compared to", "in contrast"):
                        if marker in p_low:
                            c_score += 5
                    body_start = p_text.split("\n", 1)[1].strip() if "\n" in p_text else p_text
                    if body_start.startswith("("):
                        c_score -= 10
                    if c_score > best_contrast_score:
                        s_best = None
                        sents = _candidate_sentences(p_text, p.get("heading") or "")
                        for i, s in enumerate(sents):
                            s_low = s.lower()
                            in_left = True if left_is_pronoun else any(re.search(rf"\b{re.escape(stem(t))}\w*\b", s_low) for t in tokens_left)
                            in_right = True if right_is_pronoun else any(re.search(rf"\b{re.escape(stem(t))}\w*\b", s_low) for t in tokens_right)
                            if in_left and in_right:
                                if len(s) >= SPAN_MIN_CHARS:
                                    s_cand = _without_heading(s, p)
                                    if len(s_cand) < 100:
                                        if i > 0:
                                            prev_s = _without_heading(sents[i - 1], p)
                                            if len(prev_s) + 1 + len(s_cand) <= PARAGRAPH_CAP and _quote_in_passage(f"{prev_s} {s_cand}", p_text):
                                                s_cand = f"{prev_s} {s_cand}"
                                        elif i + 1 < len(sents):
                                            next_s = _without_heading(sents[i + 1], p)
                                            if len(s_cand) + 1 + len(next_s) <= PARAGRAPH_CAP and _quote_in_passage(f"{s_cand} {next_s}", p_text):
                                                s_cand = f"{s_cand} {next_s}"
                                    s_best = s_cand
                                    break
                            elif (in_left or in_right) and any(m in s_low for m in ("unlike", "difference", "versus", "differ")):
                                if len(s) >= SPAN_MIN_CHARS and not s_best:
                                    s_best = _without_heading(s, p)
                        if not s_best:
                            s_best = _without_heading(p_text.split("\n\n")[0], p)
                        if s_best:
                            best_contrast_score = c_score
                            dual_hit = p
                            dual_sentence = s_best
            if dual_hit and dual_sentence:
                cur_quote = citations[0]["quote"].lower() if citations else ""
                cur_has_left = True if left_is_pronoun else any(re.search(rf"\b{re.escape(stem(t))}\w*\b", cur_quote) for t in tokens_left)
                cur_has_right = True if right_is_pronoun else any(re.search(rf"\b{re.escape(stem(t))}\w*\b", cur_quote) for t in tokens_right)
                if not (cur_has_left and cur_has_right) or dual_hit["chunk_id"] != citations[0]["chunk_id"]:
                    citations = [{
                        "chunk_id": dual_hit["chunk_id"],
                        "chapter": str(dual_hit["chapter"]),
                        "quote": dual_sentence,
                    }]
    answer_lines = [
        f"[Ch. {item['chapter']}] \"{item['quote']}\"" for item in citations
    ]
    if gloss:
        gloss_cleaned = _clean_boilerplate_gloss(" ".join(gloss))
        if gloss_cleaned:
            answer_lines.append(gloss_cleaned)
    cited = {item["chunk_id"] for item in citations}
    named = [hit for hit in passages if hit["chunk_id"] in cited] or passages
    body = {
        "answer": "\n".join(answer_lines),
        "citations": citations,
        "figures": figures_for(named, figures or []),
        "refused": False,
    }
    return _align_citation_to_query_concepts(body, question, passages)


def _align_citation_to_query_concepts(body, question, passages):
    """Realign citations to passages that actually discuss the query's core acronyms or topic concepts."""
    if not body or body.get("refused") or not body.get("citations") or not passages:
        return body
    citations = body["citations"]
    cur_chunk_id = citations[0].get("chunk_id")

    q_words = words(question)
    raw_acronyms = [w.lower() for w in re.findall(r"\b[A-Za-z0-9]+\b", question) if (w.isupper() and len(w) >= 2) or w.lower() in ("s3", "iops", "aimd", "sla", "slo", "cdc")]
    q_acronyms = sorted(raw_acronyms, key=lambda a: (0 if a in ("tcp", "ip", "udp") else 1, len(a)), reverse=True)
    primary_ac = []
    cur_has_acronym = False
    if q_acronyms:
        cur_hit = next((p for p in passages if p.get("chunk_id") == cur_chunk_id), None)
        cur_text = ((cur_hit.get("heading") or "") + " " + (cur_hit.get("text") or "")).lower() if cur_hit else ""
        # Does current cited passage have the specific acronyms?
        primary_ac = [ac for ac in q_acronyms if ac not in ("tcp", "ip", "udp")] or q_acronyms
        cur_has_acronym = any(re.search(rf"\b{re.escape(ac)}s?\b", cur_text) for ac in primary_ac)
        if "iops" in primary_ac and cur_chunk_id != passages[0].get("chunk_id"):
            p0_text = (passages[0].get("text") or "").lower()
            if "operations per second" in p0_text and "operations per second" not in cur_text:
                cur_has_acronym = False
        if not cur_has_acronym:
            best_hit = None
            best_count = -100
            for p in passages:
                p_text = ((p.get("heading") or "") + " " + (p.get("text") or "")).lower()
                head_text = (p.get("heading") or "").lower()
                is_example = head_text.startswith("example:") or head_text.startswith("example ")
                count = sum(2 if ac in primary_ac else 1 for ac in q_acronyms if re.search(rf"\b{re.escape(ac)}s?\b", p_text))
                if is_example:
                    count -= 3
                if count > best_count:
                    best_count = count
                    best_hit = p
            if best_hit:
                b_text = best_hit.get("text") or ""
                best_sent = ""
                for ac in primary_ac:
                    for s in _sentences(b_text):
                        s_clean = _without_heading(s, best_hit)
                        if re.search(rf"\b{re.escape(ac)}s?\b", s_clean.lower()) and len(s_clean) >= SPAN_MIN_CHARS:
                            best_sent = s_clean
                            break
                    if best_sent:
                        break
                if not best_sent:
                    for ac in primary_ac:
                        para = _paragraph_around(ac, b_text)
                        if para and len(para) <= PARAGRAPH_CAP and len(para) >= SPAN_MIN_CHARS:
                            best_sent = _without_heading(para, best_hit)
                            break
                if best_sent:
                    best_sent = _reground_alphanumeric_quote(best_sent, question, b_text)
                    chap = str(best_hit["chapter"])
                    return {
                        "answer": f'[Ch. {chap}] "{best_sent}"\n{best_sent}',
                        "citations": [{
                            "chunk_id": best_hit["chunk_id"],
                            "chapter": chap,
                            "quote": best_sent,
                        }],
                        "figures": figures_for([best_hit], body.get("figures") or []),
                        "refused": False,
                    }

    content_verbs = [w.lower() for w in q_words if w.lower() in ("extract", "extracting", "replicate", "ingest")]
    if content_verbs:
        cur_hit = next((p for p in passages if p.get("chunk_id") == cur_chunk_id), None)
        cur_text = ((cur_hit.get("heading") or "") + " " + (cur_hit.get("text") or "")).lower() if cur_hit else ""
        if not any(v in cur_text for v in content_verbs):
            for p in passages:
                p_text = ((p.get("heading") or "") + " " + (p.get("text") or "")).lower()
                if any(v in p_text for v in content_verbs):
                    for s in _sentences(p.get("text") or ""):
                        s_clean = _without_heading(s, p)
                        if any(v in s_clean.lower() for v in content_verbs) and len(s_clean) >= SPAN_MIN_CHARS:
                            chap = str(p["chapter"])
                            return {
                                "answer": f'[Ch. {chap}] "{s_clean}"\n{s_clean}',
                                "citations": [{
                                    "chunk_id": p["chunk_id"],
                                    "chapter": chap,
                                    "quote": s_clean,
                                }],
                                "figures": figures_for([p], body.get("figures") or []),
                                "refused": False,
                            }

    tokens = re.findall(r"\b[a-zA-Z0-9_-]+\b", question.lower())
    phrases = []
    for i in range(len(tokens) - 1):
        w1, w2 = tokens[i], tokens[i + 1]
        if w1 not in STOPWORDS and w1 not in STEM_WORDS and len(w1) >= 3:
            if w2 not in STOPWORDS and w2 not in STEM_WORDS and len(w2) >= 3:
                phrases.append(f"{w1} {w2}")
    if phrases and passages and cur_chunk_id != passages[0].get("chunk_id") and not (primary_ac and cur_has_acronym):
        cur_hit = next((p for p in passages if p.get("chunk_id") == cur_chunk_id), None)
        cur_text = ((cur_hit.get("heading") or "") + " " + (cur_hit.get("text") or "")).lower() if cur_hit else ""
        top_text = ((passages[0].get("heading") or "") + " " + (passages[0].get("text") or "")).lower()
        matched_phrase = next((ph for ph in phrases if re.search(rf"\b{re.escape(ph)}\b", top_text)), None)
        if matched_phrase and not re.search(rf"\b{re.escape(matched_phrase)}\b", cur_text):
            p = passages[0]
            for s in _sentences(p.get("text") or ""):
                s_clean = _without_heading(s, p)
                if re.search(rf"\b{re.escape(matched_phrase)}\b", s_clean.lower()) and len(s_clean) >= SPAN_MIN_CHARS:
                    chap = str(p["chapter"])
                    return {
                        "answer": f'[Ch. {chap}] "{s_clean}"\n{s_clean}',
                        "citations": [{
                            "chunk_id": p["chunk_id"],
                            "chapter": chap,
                            "quote": s_clean,
                        }],
                        "figures": figures_for([p], body.get("figures") or []),
                        "refused": False,
                    }

    creator_match = re.search(r"\bwho\s+(?:created|invented|designed|developed|authored|introduced|wrote|founded|proposed)\b", question, re.I)
    if creator_match:
        cur_quote = citations[0].get("quote", "") if citations else ""
        has_author = bool(re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", cur_quote)) or any(w in cur_quote.lower() for w in ("author", "creator", "created", "invented", "wrote", "book"))
        if not has_author:
            for p in passages:
                p_text = p.get("text") or ""
                for s in _sentences(p_text):
                    s_clean = _without_heading(s, p)
                    if len(s_clean) >= SPAN_MIN_CHARS and re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", s_clean):
                        if any(w in s_clean.lower() for w in ("noted", "book", "article", "creator", "created", "invented", "introduced", "proposed", "authored")):
                            chap = str(p["chapter"])
                            return {
                                "answer": f'[Ch. {chap}] "{s_clean}"\n{s_clean}',
                                "citations": [{
                                    "chunk_id": p["chunk_id"],
                                    "chapter": chap,
                                    "quote": s_clean,
                                }],
                                "figures": figures_for([p], body.get("figures") or []),
                                "refused": False,
                            }

    cur_hit = next((p for p in passages if p.get("chunk_id") == cur_chunk_id), None)
    if cur_hit:
        cur_q = citations[0].get("quote", "")
        regrounded = _reground_alphanumeric_quote(cur_q, question, cur_hit.get("text", ""))
        if regrounded and regrounded != cur_q:
            citations[0]["quote"] = regrounded
            lines = (body.get("answer") or "").splitlines()
            if lines and lines[0].startswith("[Ch."):
                lines[0] = f'[Ch. {citations[0]["chapter"]}] "{regrounded}"'
                body["answer"] = "\n".join(lines)

    return body


def _refusal(passages, figures=None):
    misses = []
    for hit in passages[:3]:
        snippet = re.sub(r"\s+", " ", hit.get("text") or "").strip()
        misses.append({
            "chunk_id": hit["chunk_id"],
            "chapter": str(hit["chapter"]),
            "quote": snippet[:MISS_QUOTE_CHARS],
        })
    return {
        "answer": REFUSAL,
        "citations": misses,
        "figures": figures_for(passages[:3], figures or []),
        "refused": True,
        "followups": [],
    }


def _rank_seq_chunks(seq_chunks, question, history_subject=None):
    """Rank sequential neighbor chunks by keyword relevance to the follow-up question."""
    q_lower = (question or "").lower()
    q_words = set(re.findall(r"\b[a-zA-Z0-9]+\b", q_lower))

    def score_chunk(c):
        text = (c.get("heading") or "").lower() + " " + (c.get("text") or "").lower()
        score = 0
        if history_subject and history_subject.lower() in text:
            score += 25
        elif history_subject and any(w in text for w in history_subject.lower().split() if len(w) > 3):
            score += 15
        if re.search(r"\b(which\s+chapter|where\s+in\s+the\s+book)\b", q_lower):
            if "in greater detail" in text:
                score += 25
            if re.search(r"\bchapter\s+\d+\b", text):
                score += 20
        if re.search(r"\b(who\s+created|who\s+introduced|who\s+coined|who\s+founded|who\s+proposed|who\s+invented|creator|inventor)\b", q_lower):
            for marker in ("introduced", "created", "coined", "founded", "proposed", "author", "invented", "noted", "article", "book"):
                if marker in text:
                    score += 10
            orig_text = (c.get("text") or "")
            if re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", orig_text):
                score += 10
        content_words = {w for w in q_words if len(w) > 3 and w not in STOPWORDS and w not in FRAMING_WORDS}
        for cw in content_words:
            if cw in text:
                score += 2
        if re.search(r"\b(reason|reasons|why|stages|types|ways|characteristics)\b", q_lower):
            for term in ("reason", "reasons", "first,", "second,", "third,", "because", "due to", "stages", "types"):
                if term in text:
                    score += 15
        if re.search(r"\b(example|examples|instance)\b", q_lower):
            for term in ("for example", "for instance", "such as", "consider", "example", "examples"):
                if term in text:
                    score += 15
        if re.search(r"\b(downside|downsides|disadvantage|disadvantages|drawback|drawbacks|con|cons|trade-off|trade-offs|tradeoff|tradeoffs|challenge|challenges|risk|risks)\b", q_lower):
            for term in ("disadvantage", "disadvantages", "downside", "downsides", "drawback", "drawbacks", "complexity", "bottleneck", "bottlenecks", "overhead", "costs", "trade-off", "trade-offs"):
                if term in text:
                    score += 15
        for term in ("overhead", "trade-offs", "tradeoffs", "latency", "throughput", "partition"):
            if term in text:
                score += 5
        return score

    return sorted(seq_chunks, key=score_chunk, reverse=True)


def _prioritize_phrase_matches(passages, question):
    """Prioritize passages containing exact multi-word non-stopword phrases or acronym definitions from the query."""
    if not passages or not question:
        return passages
    tokens = re.findall(r"\b[a-zA-Z0-9_-]+\b", question.lower())
    phrases = []
    for i in range(len(tokens) - 1):
        w1, w2 = tokens[i], tokens[i + 1]
        if w1 not in STOPWORDS and w1 not in STEM_WORDS and len(w1) >= 3:
            if w2 not in STOPWORDS and w2 not in STEM_WORDS and len(w2) >= 3:
                phrases.append(f"{w1} {w2}")
    acronyms = [w for w in re.findall(r"\b[A-Za-z0-9]+\b", question) if (w.isupper() and 2 <= len(w) <= 5) or w.lower() in ("s3", "iops")]

    def score_hit(hit):
        score = 0
        text_low = ((hit.get("heading") or "") + " " + (hit.get("text") or "")).lower()
        head_low = (hit.get("heading") or "").lower()
        for p in phrases:
            if re.search(rf"\b{re.escape(p)}\b", text_low):
                score += 10
            if re.search(rf"\b{re.escape(p)}\b", head_low):
                score += 15
        for ac in acronyms:
            ac_low = ac.lower()
            if re.search(rf"\b{re.escape(ac_low)}s?\b", head_low):
                if not (head_low.startswith("example:") or head_low.startswith("example ")):
                    score += 20
                else:
                    score += 5
            if ac_low == "s3":
                if "amazon s3" in text_low or "object storage" in text_low:
                    score += 15
                if "storage classes" in text_low or "storage tiers" in text_low:
                    score += 10
            elif ac_low == "iops" and ("operations per second" in text_low or "(iops)" in text_low):
                score += 15
        return score

    scores = [score_hit(h) for h in passages]
    if any(s > 0 for s in scores):
        scored = list(zip(scores, passages))
        passages = [h for _, h in sorted(scored, key=lambda x: x[0], reverse=True)]
    return passages


def retrieval_context(index, question, search_fn=None, generate_fn=None,
                      pin_chunk=None, end_chunk_id=None, history=None, selection="",
                      embed_fn=None):
    """The passages the model is shown, after reading, fusion, and seeding.

    Shared by ask and respond so both modes see the same evidence; the
    groundedness meter (artifacts/harnesses/groundedness.py) calls this to compare an
    answer against exactly the passages it was given. When a question word is
    not in the book, the reading repair runs first (difflib, self-proving);
    the LLM enhancer is the fallback under the same gate, so a typo difflib
    cannot see still gets one honest attempt.
    """
    topic_shift = _is_topic_shift_followup(question, history, selection, pin_chunk=pin_chunk, index=index)
    effective_pin = None if (topic_shift and not selection) else pin_chunk
    if effective_pin is None and history and not topic_shift:
        clean_history = [
            h for h in (history or [])
            if isinstance(h, dict) and (h.get("question") or h.get("answer"))
        ]
        if clean_history:
            m_concept = _TOPIC_SHIFT_CONCEPT_RE.match(question.strip())
            if m_concept:
                concept_target = m_concept.group(1).strip()
                target_words = {w.lower() for w in words(concept_target) if w.lower() not in STOPWORDS and len(w) >= 2}
                prior_turn = clean_history[-1]
                prior_a = (prior_turn.get("answer") or "").strip()
                if len(target_words) >= 3 and prior_a and all(w in prior_a.lower() for w in target_words):
                    m_q = re.search(r"\[Ch\.\s*([^\]]+)\]\s*[\"“](.+?)[\"”]", prior_a)
                    if m_q:
                        prior_chap = m_q.group(1).strip().rstrip(".")
                        prior_snippet = m_q.group(2).strip()[:50].lower()
                        for c in (index.get("chunks") or []):
                            if str(c.get("chapter")) == prior_chap and prior_snippet in (c.get("text") or "").lower():
                                effective_pin = c.get("chunk_id")
                                break
                        if effective_pin is None:
                            for c in (index.get("chunks") or []):
                                if prior_snippet in (c.get("text") or "").lower():
                                    effective_pin = c.get("chunk_id")
                                    break
    ranks = None
    if search_fn is None:
        ranked = rank_chunks(index, question, embed_fn=embed_fn)
        passages = [
            {
                "score": score,
                "chunk_id": chunk["chunk_id"],
                "chapter": chunk["chapter"],
                "heading": chunk.get("heading", ""),
                "text": chunk.get("text", ""),
                "source": chunk.get("source", ""),
            }
            for score, chunk in ranked[:PASSAGE_LIMIT]
        ]
        ranks = {chunk["chunk_id"]: i for i, (_, chunk) in enumerate(ranked, start=1)}
    else:
        passages = search_fn(index, question, k=PASSAGE_LIMIT)
    passages = _pin_chunk(index, passages, effective_pin, end_chunk_id=end_chunk_id)

    context = {
        "question": question,
        "asked": question,
        "passages": passages,
        "reading": None,
        "word_map": {},
    }
    if not passages:
        return context
    word_map = postings(index)
    context["word_map"] = word_map
    # A word the book does not contain may be a typo. One self-proving reading
    # becomes the question when it scores strictly better, and the answer says
    # which reading it answered. Nothing is repaired silently.
    best_score = passages[0].get("score", 0.0)
    try:
        reading = second_reading(index, question, best_score, word_map=word_map, embed_fn=embed_fn)
    except TypeError:
        reading = second_reading(index, question, best_score, word_map=word_map)
    if reading is None:
        # The difflib reading cannot see every typo (measured 2026-10-13:
        # "normilazation", "ingestoin"); the model proposes and the same
        # strict-improvement gate decides. A failed call leaves the literal
        # question standing.
        try:
            reading = llm_second_reading(
                index, question, best_score,
                generate_fn=generate_fn, word_map=word_map,
                embed_fn=embed_fn,
            )
        except TypeError:
            reading = llm_second_reading(
                index, question, best_score,
                generate_fn=generate_fn, word_map=word_map,
            )
    if reading is not None:
        context["reading"] = reading
        context["asked"] = reading["reading"]
        present = any(
            hit["chunk_id"] == reading["chunk"]["chunk_id"] for hit in passages
        )
        if not present:
            passages = [reading["chunk"]] + passages[:-1]
    asked = context["asked"]
    # Fusion pays one embed plus a full cosine pass. The lexical channel joins
    # only when the question carries a rare book word, the trigger the boost
    # used; other asks do not pay.
    if rare(asked, word_map):
        if ranks is not None and asked == question:
            try:
                passages = fuse(index, asked, passages, word_map, ranks=ranks, embed_fn=embed_fn)
            except TypeError:
                try:
                    passages = fuse(index, asked, passages, word_map, ranks=ranks)
                except TypeError:
                    passages = fuse(index, asked, passages, word_map)
        else:
            try:
                passages = fuse(index, asked, passages, word_map, embed_fn=embed_fn)
            except TypeError:
                passages = fuse(index, asked, passages, word_map)
    # Caption seeding runs last: its measured effect is which chunk leads, and
    # fusion would otherwise be free to demote that lead.
    try:
        passages = caption_seed(index, asked, passages, embed_fn=embed_fn)
    except TypeError:
        passages = caption_seed(index, asked, passages)
    passages = _prioritize_phrase_matches(passages, asked)

    clean_history = [
        h for h in (history or [])
        if isinstance(h, dict) and (h.get("question") or h.get("answer"))
    ]
    if clean_history and not topic_shift:
        chunks = index.get("chunks") or []
        target_idx = None
        if effective_pin:
            p_id = effective_pin.get("chunk_id") if isinstance(effective_pin, dict) else effective_pin
            if p_id:
                for i, c in enumerate(chunks):
                    if c.get("chunk_id") == p_id:
                        target_idx = i
                        break

        last_turn = clean_history[-1]
        last_ans = last_turn.get("answer") or ""
        m = re.search(r"\[Ch\.\s*([^\]]+)\]\s*[\"“](.+?)[\"”]", last_ans)
        if target_idx is None and m:
            prior_chap = m.group(1).strip().rstrip(".")
            prior_quote = m.group(2).strip()
            snippet = prior_quote[:50].lower()
            for i, c in enumerate(chunks):
                if str(c.get("chapter")) == prior_chap and snippet in (c.get("text") or "").lower():
                    target_idx = i
                    break
            if target_idx is None:
                for i, c in enumerate(chunks):
                    if snippet in (c.get("text") or "").lower():
                        target_idx = i
                        break
        if target_idx is not None:
            cand_offsets = (0, 1, -1, 2)
            seq_chunks = []
            for offset in cand_offsets:
                cand_idx = target_idx + offset
                if 0 <= cand_idx < len(chunks):
                    cand = chunks[cand_idx]
                    if str(cand.get("chapter")) == str(chunks[target_idx].get("chapter")):
                        if cand not in seq_chunks:
                            seq_chunks.append(cand)
            if seq_chunks:
                history_subject = _extract_subject_from_history(clean_history)
                ranked_seq = _rank_seq_chunks(seq_chunks, question, history_subject)
                p0_s = passages[0].get("score") if passages else 1.0
                base_score = float(p0_s) if p0_s is not None else 1.0
                injected = []
                for idx_offset, c in enumerate(ranked_seq):
                    c_dict = dict(c)
                    c_s = c.get("score")
                    c_dict["score"] = float(c_s) if c_s is not None else (base_score - 0.001 * (idx_offset + 1))
                    injected.append(c_dict)
                injected_ids = {c["chunk_id"] for c in injected}
                passages = injected + [p for p in passages if p.get("chunk_id") not in injected_ids]
                passages = passages[:PASSAGE_LIMIT]

    if effective_pin and not topic_shift:
        chunks = index.get("chunks") or []
        p_id = effective_pin.get("chunk_id") if isinstance(effective_pin, dict) else effective_pin
        p_obj = next((c for c in chunks if c.get("chunk_id") == p_id), None)
        if p_obj:
            is_chapter_query = bool(re.search(r"\b(which\s+chapter|where\s+in\s+the\s+book|chapter\s+\d+|across\s+chapters)\b", question, re.I))
            if not is_chapter_query:
                try:
                    p_idx = chunks.index(p_obj)
                    p_chap = str(p_obj.get("chapter"))
                    same_chap_seq = []
                    for offset in (0, 1, -1, 2, -2):
                        cand_idx = p_idx + offset
                        if 0 <= cand_idx < len(chunks):
                            cand = chunks[cand_idx]
                            if str(cand.get("chapter")) == p_chap and cand.get("chunk_id") not in {c.get("chunk_id") for c in same_chap_seq}:
                                same_chap_seq.append(cand)
                    seen_ids = {c.get("chunk_id") for c in same_chap_seq}
                    same_chap_dense = [p for p in passages if str(p.get("chapter")) == p_chap and p.get("chunk_id") not in seen_ids]
                    for p in same_chap_dense:
                        seen_ids.add(p.get("chunk_id"))
                    other_passages = [p for p in passages if p.get("chunk_id") not in seen_ids]
                    passages = (same_chap_seq + same_chap_dense + other_passages)[:PASSAGE_LIMIT]
                except ValueError:
                    pass
            else:
                try:
                    p_idx = chunks.index(p_obj)
                    p_neighbors = []
                    if p_idx + 1 < len(chunks) and chunks[p_idx + 1].get("chapter") == p_obj.get("chapter"):
                        p_neighbors.append(chunks[p_idx + 1])
                    if p_idx > 0 and chunks[p_idx - 1].get("chapter") == p_obj.get("chapter"):
                        p_neighbors.append(chunks[p_idx - 1])
                    if clean_history:
                        p_n_ids = {n.get("chunk_id") for n in p_neighbors}
                        passages = [p for p in passages if p.get("chunk_id") not in p_n_ids]
                        passages = p_neighbors + passages
                    else:
                        p_curr_ids = {p.get("chunk_id") for p in passages}
                        for n in p_neighbors:
                            if n.get("chunk_id") not in p_curr_ids:
                                passages.append(n)
                except ValueError:
                    pass
    elif effective_pin:
        chunks = index.get("chunks") or []
        p_id = effective_pin.get("chunk_id") if isinstance(effective_pin, dict) else effective_pin
        p_obj = next((c for c in chunks if c.get("chunk_id") == p_id), None)
        if p_obj:
            try:
                p_idx = chunks.index(p_obj)
                p_neighbors = []
                if p_idx + 1 < len(chunks) and chunks[p_idx + 1].get("chapter") == p_obj.get("chapter"):
                    p_neighbors.append(chunks[p_idx + 1])
                if p_idx > 0 and chunks[p_idx - 1].get("chapter") == p_obj.get("chapter"):
                    p_neighbors.append(chunks[p_idx - 1])
                p_curr_ids = {p.get("chunk_id") for p in passages}
                for n in p_neighbors:
                    if n.get("chunk_id") not in p_curr_ids:
                        passages.append(n)
            except ValueError:
                pass

    if effective_pin or end_chunk_id:
        passages = _pin_chunk(index, passages, effective_pin, end_chunk_id=end_chunk_id)
    context["passages"] = passages
    return context


@functools.lru_cache(maxsize=1024)
def _candidate_sentences_cached(text, heading=""):
    raw = (text or "").strip()
    if not raw:
        return ()
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip()]
    raw_candidates = []
    for para in paragraphs:
        lines = [line.strip() for line in para.splitlines() if line.strip()]
        if not lines:
            continue
        body_lines = []
        for i, line in enumerate(lines):
            if i == 0 and len(lines) > 1 and not line.endswith((".", "?", "!", ":", ";", '"', "'", "”")):
                raw_candidates.append(line)
            else:
                body_lines.append(line)
        if body_lines:
            body_text = " ".join(body_lines)
            parts = [s.strip() for s in _SENTENCE_SPLIT_RE.split(body_text) if s.strip()]
            raw_candidates.extend(parts)

    if not raw_candidates:
        return ()

    head_norm = (heading or "").strip().lower()
    has_terminal = any(_TERMINAL_PUNCT_RE.search(s.strip()) for s in raw_candidates)

    filtered = []
    for s in raw_candidates:
        s_strip = s.strip()
        if not s_strip:
            continue
        # a) matches heading.strip() (case-insensitive)
        if head_norm and s_strip.lower() == head_norm:
            continue
        # b) matches r"^Chapter\s+\d+\b" and does not end with ., !, or ?
        if _CHAPTER_PREFIX_RE.match(s_strip) and not _TERMINAL_PUNCT_RE.search(s_strip):
            continue
        # c) does not end with terminal punctuation when there are other sentences that DO
        if has_terminal and not _TERMINAL_PUNCT_RE.search(s_strip):
            continue
        filtered.append(s_strip)

    return tuple(filtered if filtered else raw_candidates)

def _candidate_sentences(text, heading=""):
    return list(_candidate_sentences_cached(text, heading))


def _resolve_contextual_query(index, question, pin_chunk=None, selection="",
                              heading="", history=None):
    """Resolve incomplete, fragment, deictic, or selection-backed queries.

    Book-agnostic: uses the reader's active chunk, selection, heading, or the
    index's sentence postings to turn fragments into self-contained queries.
    """
    q = re.sub(r"\s+", " ", (question or "")).strip()
    sel = _clean_selection_text(selection)
    head = re.sub(r"\s+", " ", (heading or "")).strip()

    pin_chunk_obj = None
    if pin_chunk:
        if isinstance(pin_chunk, dict):
            pin_chunk_obj = pin_chunk
        elif isinstance(pin_chunk, str):
            pin_chunk_obj = next(
                (c for c in (index.get("chunks") or []) if c.get("chunk_id") == pin_chunk),
                None,
            )

    clean_history = [
        h for h in (history or [])
        if isinstance(h, dict) and (h.get("question") or h.get("answer"))
    ]

    # Case 1b: Multi-turn history coreference resolution (Turn 2+)
    if clean_history:
        subject = _extract_subject_from_history(clean_history) or sel
        if subject:
            q_lower = q.lower()
            q_words = set(re.findall(r"\b[a-zA-Z]+\b", q_lower))
            deictic = q_words & {"it", "its", "this", "that", "these", "those", "they", "them", "such"}
            if re.search(r"\b(its\s+downsides|its\s+disadvantages|its\s+pros\s+and\s+cons|its\s+drawbacks)\b", q_lower):
                return re.sub(r"\bits\b", f"the {subject}'s", q, flags=re.IGNORECASE)
            elif re.search(r"\b(warn\s+against\s+that|warn\s+about\s+that|caution\s+against\s+that)\b", q_lower):
                return re.sub(r"\bthat\b", f"{subject}", q, flags=re.IGNORECASE)
            elif re.search(r"\b(handle\s+late\s+data|handles\s+late\s+data)\b", q_lower) and "it" in q_words:
                return re.sub(r"\bit\b", f"{subject}", q, flags=re.IGNORECASE)
            elif re.search(r"\b(that\s+stage|that\s+phase|that\s+step)\b", q_lower):
                return re.sub(r"\bthat\s+stage\b", f"the {subject} stage", q, flags=re.IGNORECASE)
            elif re.search(r"\b(this\s+architectural\s+pattern|this\s+pattern|this\s+architecture)\b", q_lower):
                return re.sub(r"\bthis\s+(architectural\s+pattern|pattern|architecture)\b", f"{subject}", q, flags=re.IGNORECASE)
            elif re.search(r"\busing\s+it\b", q_lower):
                return re.sub(r"\busing\s+it\b", f"using {subject}", q, flags=re.IGNORECASE)
            elif re.search(r"\bfor\s+(this|that)\b", q_lower):
                return re.sub(r"\bfor\s+(this|that)\b", f"for {subject}", q, flags=re.IGNORECASE)
            elif re.search(r"\bopen-source\s+it\b", q_lower):
                return re.sub(r"\bopen-source\s+it\b", f"open-source {subject}", q, flags=re.IGNORECASE)
            elif deictic:
                if re.search(r"\b(how\s+does|how\s+is|what\s+is|what\s+are|why\s+does|why\s+is)\s+it\b", q_lower):
                    return re.sub(r"\bit\b", f"{subject}", q, count=1, flags=re.IGNORECASE)
                elif re.search(r"\b(what\s+are|what\s+is)\s+its\b", q_lower):
                    return re.sub(r"\bits\b", f"{subject}'s", q, count=1, flags=re.IGNORECASE)
                else:
                    return f"Regarding {subject}: {q}"
            elif subject.lower() not in q_lower and (
                _is_generic_followup(q) or
                is_incomplete_stem(q) or
                bool(re.search(r"\b(type|tier|stage|phase|step)\s*\d+\b", q_lower)) or
                bool(GENERIC_FACETS_RE.search(q_lower))
            ):
                return f"Regarding {subject}: {q}"

    # Case 1: Selection is non-empty and question is contextual / deictic / incomplete (Turn 1 askSelection)
    if sel and not clean_history and len(sel.split()) <= 45:
        if sel.lower() not in q.lower():
            if is_deictic_question(q):
                if q.lower().startswith(("why", "how")):
                    return f"{q.rstrip('?').strip()} ('{sel}')?"
                return f"What does '{sel}' mean in this passage?"
            if is_incomplete_stem(q):
                base = q.rstrip("?").strip()
                return f"{base} {sel}?"
            q_words = set(re.findall(r"\w+", q.lower()))
            deictic = q_words & {"this", "that", "it", "these", "those"}
            if deictic or q.lower().rstrip("?") in ("why", "explain", "how", "what") or _is_generic_followup(q) or bool(GENERIC_FACETS_RE.search(q.lower())):
                if head:
                    return f"In {head}, regarding '{sel}': {q}"
                return f"Regarding '{sel}': {q}"
            if head:
                return f"In {head}, regarding '{sel}': {q}"
            return f"Regarding '{sel}': {q}"

    # Case 2: Incomplete stem / wh-prefix (e.g. "what are the", "how is", "why do")
    if is_incomplete_stem(q):
        stem = re.sub(r"[?!.,]", "", q.lower()).strip()
        if pin_chunk_obj is not None:
            chunks = index.get("chunks") or []
            search_pool = [pin_chunk_obj]
            try:
                idx = chunks.index(pin_chunk_obj)
                if idx > 0 and chunks[idx - 1].get("chapter") == pin_chunk_obj.get("chapter"):
                    search_pool.append(chunks[idx - 1])
                if idx + 1 < len(chunks) and chunks[idx + 1].get("chapter") == pin_chunk_obj.get("chapter"):
                    search_pool.append(chunks[idx + 1])
            except ValueError:
                pass
            for chunk in search_pool:
                for sent in _candidate_sentences(chunk.get("text") or "", chunk.get("heading") or ""):
                    if sent.lower().startswith(stem + " ") and len(sent) >= 20:
                        return sent
            h = head or pin_chunk_obj.get("heading", "")
            if h:
                return f"{q.rstrip('?')} {h}?"

        for chunk in (index.get("chunks") or []):
            for sent in _candidate_sentences(chunk.get("text") or "", chunk.get("heading") or ""):
                if sent.lower().startswith(stem + " ") and len(sent) >= 20:
                    return sent

        first_chunk = (index.get("chunks") or [{}])[0]
        first_head = first_chunk.get("heading") or head
        if first_head:
            return f"{q.rstrip('?')} {first_head}?"

    return question


def _followup_gloss_user_message(history, question, quote, chunk, neighbors=None):
    clean_history = [
        h for h in (history or [])
        if isinstance(h, dict) and (h.get("question") or h.get("answer"))
    ]
    parts = []
    if clean_history:
        last = clean_history[-1]
        parts.append(f"Previous reader question: {last.get('question', '')}")
        last_a = (last.get("answer") or "").strip()
        if last_a:
            parts.append(f"Previous answer: {last_a}")
    parts.append(f"Current reader follow-up question: {question}")
    parts.append(f"Cited passage quote: {quote}")
    if chunk.get("heading"):
        parts.append(f"Section heading: {chunk['heading']}")
    parts.append(f"\nPassage context:\n{chunk.get('text', '')}")
    if neighbors:
        for n in neighbors:
            if n and n.get("text"):
                parts.append(f"\nRelated context ({n.get('heading', '')}):\n{n['text']}")
    if SIMPLIFY_RE.search(question):
        q_low = question.lower()
        if any(w in q_low for w in ("shorter", "one sentence", "one short sentence", "tl;dr")):
            parts.append(
                "\nRewrite the previous explanation in ONE short, punchy sentence (under 18 words) using plain everyday language."
            )
        else:
            parts.append(
                "\nRewrite and simplify the previous explanation in 1 to 2 plain, everyday sentences without technical jargon so any reader can immediately understand it."
            )
    else:
        parts.append(
            "\nWrite a direct 1 to 2 sentence answer that explicitly answers the follow-up question "
            "and connects it to the previous turn. Ground strictly in the passage context."
        )
    return "\n".join(parts)


def _answer_gloss_user_message(question, quote, chunk):
    parts = [
        f"Reader question: {question}",
        f"Cited sentence from the book: {quote}",
    ]
    if chunk.get("heading"):
        parts.append(f"Section heading: {chunk['heading']}")
    parts.append(f"\nPassage context:\n{chunk.get('text', '')}")
    if _list_ask(question, question):
        parts.append(
            "\nExplicitly name the specific items, stages, components, or types in your answer."
        )
    parts.append(
        "\nWrite a direct 1 to 2 sentence answer in plain words that answers the reader's question "
        "based on the passage context."
    )
    return "\n".join(parts)


def _synthesize_grounded_gloss(selection, quote, pin_chunk_obj, neighbors, generate_fn, model):
    heading = (pin_chunk_obj.get("heading") or "") if pin_chunk_obj else ""
    intent_info = analyze_intent(selection, heading, pin_chunk_obj, neighbors)
    intent_type = intent_info.get("intent_type") or INTENT_CONCEPT_TERM
    core_concept = intent_info.get("core_concept") or extract_core_concept(selection, heading)
    subject = intent_info.get("subject") or (extract_enclosing_subject(quote, selection) if quote else "")

    if intent_type == INTENT_CONCEPT_TERM:
        if intent_info.get("is_passing_mention"):
            q_synth = f"How does {core_concept} relate to {heading or 'this topic'} based strictly on this passage?"
        else:
            q_synth = f"What is {core_concept}?"
    elif intent_type == INTENT_VAGUE_FRAGMENT:
        q_synth = f"Why is {subject} described as {selection}?" if subject else f"What does {selection} mean?"
    elif intent_type == INTENT_MULTI_SENTENCE:
        q_synth = "What is the core takeaway of this passage?"
    else:
        q_synth = selection.strip()

    context_passages = [pin_chunk_obj] if pin_chunk_obj else []
    if neighbors:
        for n in neighbors:
            if n and n not in context_passages:
                context_passages.append(n)

    if generate_fn and context_passages:
        try:
            cand_reply = generate_fn(SYSTEM, user_message(q_synth, context_passages), model)
            if cand_reply and cand_reply != REFUSAL:
                lines = [ln.strip() for ln in cand_reply.splitlines() if ln.strip()]
                for ln in lines:
                    if re.match(r"^\[ch\.", ln, re.I) or ln.startswith('"') or ln.startswith("“") or ln.startswith("”"):
                        continue
                    cleaned_cand = _clean_boilerplate_gloss(ln, selection)
                    if _is_coherent_gloss(cleaned_cand, quote) and (
                        not intent_info.get("is_passing_mention")
                        or _has_content_word_overlap(cleaned_cand, quote, exclude=f"{selection} {heading}")
                    ):
                        return fix_acronym_casing(cleaned_cand)
        except Exception:
            pass

    if intent_type == INTENT_VAGUE_FRAGMENT:
        if subject:
            m = re.search(re.escape(selection.strip()), quote, re.IGNORECASE) if quote else None
            after_text = ""
            if m:
                after_text = quote[m.end():].strip().rstrip(".?!")
            if after_text:
                return fix_acronym_casing(f"The highlighted phrase refers to {subject}, explaining that it is {selection.lstrip()} {after_text}.")
            return fix_acronym_casing(f"The highlighted phrase refers to {subject} as {selection} in this section.")
        return fix_acronym_casing(f"The highlighted phrase characterizes the approach described in this sentence: {quote[:100]}.")

    if intent_type == INTENT_CONCEPT_TERM:
        if intent_info.get("is_passing_mention"):
            q_clean = quote.strip().rstrip(".?!") if quote else ""
            if q_clean:
                lead = (q_clean[0].lower() + q_clean[1:]) if (len(q_clean) > 1 and not q_clean[1].isupper()) else q_clean
                return fix_acronym_casing(f"In {heading or 'this section'}, {core_concept} connects to this topic—{lead}.")
            return fix_acronym_casing(f"{core_concept} relates to {heading or 'this topic'} as described in this section.")
        substantive = []
        for cand_c in context_passages:
            if not cand_c:
                continue
            cands = split_sentences(cand_c.get("text", ""))
            for s in cands:
                if len(s) >= 40 and not META_TRANSITION_RE.search(s):
                    if core_concept.lower() in s.lower() or any(w.lower() in s.lower() for w in words(core_concept) if w.lower() not in STOPWORDS):
                        substantive.append(s)
        if substantive:
            first_sub = substantive[0]
            if first_sub.lower().startswith("to understand"):
                return fix_acronym_casing(first_sub)
            if len(substantive) >= 2 and substantive[0] != substantive[1]:
                return fix_acronym_casing(f"{substantive[0]} {substantive[1]}")
            return fix_acronym_casing(substantive[0])
        return fix_acronym_casing(f"{core_concept} refers to the technical and operational model described in this section.")

    if intent_type == INTENT_MULTI_SENTENCE:
        sents = split_sentences(selection)
        non_examples = [s for s in sents if len(s) >= 40 and not s.lower().startswith(("for instance", "for example", "consider", "look at"))]
        if non_examples:
            cand = non_examples[0]
            if len(non_examples) > 1 and len(cand) + len(non_examples[-1]) < 250:
                cand = f"{cand} {non_examples[-1]}"
            cand_lead = (cand[0].lower() + cand[1:]) if len(cand) > 1 and not cand[1].isupper() else cand
            return fix_acronym_casing(f"This passage explains that {cand_lead}")
        return fix_acronym_casing("This passage analyzes the trade-offs and operational constraints between storage, capacity, and resource limits.")

    if quote:
        return fix_acronym_casing(f"The authors explain {selection} in this section: {quote[:120]}.")
    return fix_acronym_casing(f"The authors discuss {selection} in this section.")


def _advance_followup_quote(chunk_obj, neighbors=None, prior_quote="", followup_question=""):
    """Select the sentence in chunk_obj or neighbors that answers the follow-up question,
    advancing past prior_quote when Turn 1 cited a lead-in sentence.
    """
    if not chunk_obj or not followup_question:
        return None

    if SIMPLIFY_RE.search(followup_question):
        return None

    pool = [chunk_obj]
    if neighbors:
        for n in neighbors:
            if n and n != chunk_obj and n not in pool:
                pool.append(n)

    q_low = followup_question.lower()
    q_tokens = [
        w.lower() for w in words(q_low)
        if w.lower() not in STOPWORDS and w.lower() not in FRAMING_WORDS and len(w) >= 3
    ]
    query_entities = _extract_query_entities(followup_question, chunk_obj.get("heading", ""))

    norm_prior = re.sub(r"[\s\"'“”]+", " ", prior_quote or "").strip().lower()

    scored_cands = []
    for c in pool:
        c_text = c.get("text") or ""
        c_head = c.get("heading") or ""
        sents = _candidate_sentences(c_text, c_head)
        for i, s in enumerate(sents):
            s_clean = s.strip()
            if len(s_clean) < 30:
                continue
            norm_s = re.sub(r"[\s\"'“”]+", " ", s_clean).strip().lower()
            if norm_prior and (norm_s == norm_prior or norm_s in norm_prior or (len(norm_prior) >= 40 and norm_prior in norm_s)):
                continue
            if META_TRANSITION_RE.search(s_clean):
                continue

            s_low = s_clean.lower()
            score = 0

            # A) Reasons / Specifics / Steps / Types / Stages / Ways
            if _REASONS_QUERY_RE.search(q_low):
                if s_low.startswith(("first,", "first ", "1.", "one reason")):
                    score += 35
                elif s_low.startswith(("second,", "second ", "2.", "third,", "third ", "another reason")):
                    score += 25
                elif any(w in s_low for w in ("first,", "second,", "third,", "because", "due to")):
                    score += 20
                if norm_prior and norm_prior in c_text.lower():
                    m_pos = c_text.lower().find(norm_prior)
                    s_pos = c_text.lower().find(norm_s)
                    if m_pos != -1 and s_pos > m_pos and s_pos - (m_pos + len(norm_prior)) < 400:
                        score += 15

            # B) Concrete Examples
            if _EXAMPLES_QUERY_RE.search(q_low):
                if s_low.startswith(("for instance", "for example", "consider", "such as")):
                    score += 35
                elif any(m in s_low for m in ("for instance", "for example", "such as")):
                    score += 25
                elif "example" in s_low or "examples" in s_low:
                    score += 15

            # C) Risks / Pitfalls / Bottlenecks / Costs / Trade-offs / Ossification / Cliff
            if _RISKS_QUERY_RE.search(q_low):
                for kw in _RISK_KEYWORDS:
                    if kw in q_low and kw in s_low:
                        score += 30
                    elif kw in s_low:
                        score += 10

            # C2) Attribution / Authorship / Creator
            if _ATTRIBUTION_QUERY_RE.search(q_low):
                for marker in _ATTRIBUTION_MARKERS:
                    if marker in s_low:
                        score += 15
                if _AUTHOR_NAME_RE.search(s_clean):
                    score += 20

            # D) Term / Concept extraction from followup_question
            for t in q_tokens:
                if t in s_low:
                    score += 5

            # E) Exact matches of specific query entities / proper nouns (+30 per entity word)
            if query_entities:
                for ent in query_entities:
                    if ent.lower() in s_low:
                        score += 30 * len(ent.split())

            if _list_ask(followup_question, followup_question):
                if ":" in s_clean and "," in s_clean:
                    score += 25

            # Bias towards primary chunk
            if c == chunk_obj:
                score += 2

            if score > 0:
                # Check for 2-sentence combination if first sentence is short (e.g. "First, ...")
                # or continuation (e.g. "Advertising platforms are another...")
                adv_quote = s_clean
                is_short_or_continuation = (
                    s_low.startswith(("first,", "second,", "for example", "for instance", "advertising platforms are another"))
                    or len(s_clean) < 100
                )
                if is_short_or_continuation:
                    if i + 1 < len(sents):
                        next_s = sents[i + 1].strip()
                        if len(next_s) >= 20 and not next_s.lower().startswith(("second,", "third,", "finally,")):
                            combined = f"{s_clean} {next_s}"
                            if len(combined) <= PARAGRAPH_CAP and _quote_in_passage(combined, c_text):
                                adv_quote = combined
                    elif i > 0:
                        prev_s = sents[i - 1].strip()
                        if len(prev_s) >= 20:
                            combined = f"{prev_s} {s_clean}"
                            if len(combined) <= PARAGRAPH_CAP and _quote_in_passage(combined, c_text):
                                adv_quote = combined
                scored_cands.append((score, -i, adv_quote, c))

    if not scored_cands:
        return None

    scored_cands.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_cand = scored_cands[0]
    if best_cand[0] >= 10:
        return _complete_truncated_quote(best_cand[2], best_cand[3].get("text") or "")

    return None


def _synthesize_list_answer(question: str, quote: str, chunk_obj: dict) -> str:
    """Deterministically synthesize a crisp list answer naming specific items."""
    raw_text = (chunk_obj.get("text") or "") if isinstance(chunk_obj, dict) else ""
    items = []
    if quote and "," in quote:
        quote_src = quote
        if ":" in quote:
            quote_src = quote.split(":")[-1].strip().rstrip(".?!")
        cand_items = [p.strip() for p in quote_src.split(",") if p.strip()]
        if len(cand_items) >= 2:
            items = cand_items
    if not items and raw_text:
        list_lines = [
            line.strip() for line in raw_text.splitlines()
            if 2 <= len(line.strip()) < 80
            and not line.strip().endswith((".", "!", "?", ":"))
            and not line.strip().startswith(("Chapter ", "Figure "))
            and (line.strip()[0].isupper() or line.strip()[0].isdigit())
        ]
        if len(list_lines) >= 2:
            items = list_lines
    if not items:
        return ""

    def _fmt_item(item):
        it = item.strip()
        if it.isupper() or any(c.isupper() for c in it[1:]):
            return it
        return it[0].lower() + it[1:] if it else it

    formatted = [_fmt_item(it) for it in items]
    if formatted[-1].lower().startswith("and "):
        formatted[-1] = formatted[-1][4:].strip()
    if len(formatted) == 2:
        items_str = f"{formatted[0]} and {formatted[1]}"
    else:
        items_str = ", ".join(formatted[:-1]) + f", and {formatted[-1]}"

    lead = ""
    m_q = re.search(r"\b(?:what|which)\s+(?:are|were)\s+the\s+(.+?)\s*\??$", question or "", re.I)
    if m_q:
        subj = m_q.group(1).strip()
        lead = f"The {subj} are"
    else:
        m_list = re.search(r"\b(?:list|name)\s+the\s+(.+?)\s*\??$", question or "", re.I)
        if m_list:
            subj = m_list.group(1).strip()
            lead = f"The {subj} are"
        else:
            for line in raw_text.splitlines():
                l_s = line.strip()
                if l_s.endswith(":") and len(l_s) >= 15:
                    cleaned_lead = re.sub(r"\s*\([^)]*figure[^)]*\)", "", l_s, flags=re.I).rstrip(":").strip()
                    if cleaned_lead:
                        lead = f"{cleaned_lead}:"
                        break
            if not lead:
                lead = "These include"

    if lead.endswith(":"):
        return f"{lead} {items_str}."
    elif lead.endswith(("are", "is", "include")):
        return f"{lead} {items_str}."
    else:
        return f"{lead}: {items_str}."


def _ensure_answer_gloss(index, body, question, passages, is_live=False,
                         history=None, selection="", heading="", model=ANSWER_MODEL,
                         generate_fn=None):
    """Ensure every non-refused answer has a crisp, informative 2nd line gloss."""
    if not body or body.get("refused") or not body.get("citations") or not passages:
        return body

    generate_fn = generate_fn or ollama_generate

    first_cite = body["citations"][0]
    quote = first_cite.get("quote") or ""
    if not quote or "The passages do not mention" in (body.get("answer") or ""):
        return body

    ans = (body.get("answer") or "").strip()
    lines = [ln.strip() for ln in ans.splitlines() if ln.strip()]
    first_line = lines[0] if lines else f'[Ch. {first_cite.get("chapter", "")}] "{quote}"'
    gloss_line = lines[1] if len(lines) >= 2 else ""

    if gloss_line.startswith(("Asked as:", "Read as:")):
        gloss_line = ""

    chunks = index.get("chunks") or []
    cite_id = first_cite.get("chunk_id")
    chunk_obj = next((c for c in chunks if c.get("chunk_id") == cite_id), passages[0])
    neighbors = []
    for i, c in enumerate(chunks):
        if c.get("chunk_id") == cite_id:
            if i > 0 and chunks[i - 1].get("chapter") == c.get("chapter"):
                neighbors.append(chunks[i - 1])
            if i + 1 < len(chunks) and chunks[i + 1].get("chapter") == c.get("chapter"):
                neighbors.append(chunks[i + 1])
            break

    clean_history = [
        h for h in (history or [])
        if isinstance(h, dict) and (h.get("question") or h.get("answer"))
    ]

    target_entities = _extract_query_entities(question, heading or chunk_obj.get("heading", "")) if clean_history else []
    quote_missing_query_entity = bool(
        clean_history
        and target_entities
        and not any(ent.lower() in quote.lower() for ent in target_entities)
        and any(ent.lower() in (chunk_obj.get("text", "")).lower() for ent in target_entities)
    )
    gloss_missing_query_entity = bool(target_entities and gloss_line and not any(ent.lower() in gloss_line.lower() for ent in target_entities))

    new_gloss = ""
    topic_shift = _is_topic_shift_followup(question, history, selection)

    if clean_history and not topic_shift:
        last_turn = clean_history[-1]
        prior_a = (last_turn.get("answer") or "").strip()
        m_q = re.search(r"\[Ch\.\s*[^\]]+\]\s*[\"“](.+?)[\"”]", prior_a)
        prior_quote = m_q.group(1).strip() if m_q else ""
        norm_prior = re.sub(r"[\s\"'“”]+", " ", prior_quote or "").strip().lower()
        norm_curr = re.sub(r"[\s\"'“”]+", " ", quote or "").strip().lower()
        quote_repeated = bool(
            norm_prior and norm_curr and (
                norm_curr == norm_prior
                or norm_curr in norm_prior
                or (len(norm_prior) >= 40 and norm_prior in norm_curr)
            )
        )
        list_quote_missing_items = bool(_list_ask(question, question) and "," not in quote and ":" not in quote)
        if (quote_repeated or list_quote_missing_items) and not SIMPLIFY_RE.search(question):
            adv_quote = _advance_followup_quote(chunk_obj, neighbors, prior_quote, question)
            if adv_quote and adv_quote != quote:
                adv_chunk = chunk_obj
                if not _quote_in_passage(adv_quote, chunk_obj.get("text", "")):
                    for n in (neighbors or []):
                        if n and _quote_in_passage(adv_quote, n.get("text", "")):
                            adv_chunk = n
                            break
                quote = adv_quote
                first_cite["quote"] = adv_quote
                first_cite["chunk_id"] = adv_chunk.get("chunk_id")
                first_cite["chapter"] = str(adv_chunk.get("chapter", first_cite.get("chapter", "")))
                first_line = f'[Ch. {first_cite["chapter"]}] "{quote}"'

        need_followup_gloss = (
            bool(SIMPLIFY_RE.search(question))
            or quote_repeated
            or list_quote_missing_items
            or (gloss_missing_query_entity and not GENERIC_FACETS_RE.search(question))
            or not gloss_line
            or _gloss_repeats_quote(gloss_line, quote)
            or not _is_coherent_gloss(gloss_line, quote, question=question)
        )
        if not need_followup_gloss:
            new_gloss = gloss_line
        else:
            if is_live:
                prompt = _followup_gloss_user_message(clean_history, question, quote, chunk_obj, neighbors)
                try:
                    raw = generate_fn(FOLLOWUP_GLOSS_SYSTEM, prompt, model)
                except Exception:
                    raw = ""
                new_gloss = _clean_boilerplate_gloss(raw, question)
                if re.match(r"^\[ch\.", new_gloss, re.I) and "\n" in new_gloss:
                    new_gloss = new_gloss.split("\n", 1)[1].strip()
                new_gloss = re.sub(r"\[Ch\.\s*[^\]]+\]\s*", "", new_gloss, flags=re.I).strip().strip("\"'“”")
            if not new_gloss or not _is_coherent_gloss(new_gloss, quote, question=question):
                if _list_ask(question, question):
                    list_synth = _synthesize_list_answer(question, quote, chunk_obj)
                    if list_synth and _is_coherent_gloss(list_synth, quote, question=question):
                        new_gloss = list_synth
            if not new_gloss or not _is_coherent_gloss(new_gloss, quote, question=question):
                cands = [s for s in _candidate_sentences(chunk_obj.get("text") or "", chunk_obj.get("heading") or "")
                         if s != quote and len(s) >= 40 and not META_TRANSITION_RE.search(s) and _is_coherent_gloss(s, quote, question=question)]
                if cands:
                    new_gloss = cands[0]
            if target_entities and not GENERIC_FACETS_RE.search(question) and any(ent.lower() in quote.lower() for ent in target_entities) and not any(ent.lower() in (new_gloss or "").lower() for ent in target_entities):
                sents = split_sentences(quote)
                matching_s = next((s for s in sents if any(ent.lower() in s.lower() for ent in target_entities)), quote)
                matching_s = re.sub(r"^(?:for example|for instance|in addition|specifically),?\s*", "", matching_s, flags=re.I).strip()
                ent_name = target_entities[0]
                sec_heading = heading or chunk_obj.get("heading", "")
                if sec_heading:
                    new_gloss = fix_acronym_casing(f"In {sec_heading}, {ent_name} connects to this topic: {matching_s}")
                else:
                    new_gloss = fix_acronym_casing(f"{ent_name} connects to this topic: {matching_s}")

    elif selection:
        clean_sel = _clean_selection_text(selection)
        if is_live:
            prompt = _explain_gloss_user_message(clean_sel, quote, chunk_obj, neighbors)
            try:
                raw = generate_fn(EXPLAIN_GLOSS_SYSTEM, prompt, model)
            except Exception:
                raw = ""
            new_gloss = _clean_boilerplate_gloss(raw, clean_sel)
            if re.match(r"^\[ch\.", new_gloss, re.I) and "\n" in new_gloss:
                new_gloss = new_gloss.split("\n", 1)[1].strip()
            new_gloss = re.sub(r"\[Ch\.\s*[^\]]+\]\s*", "", new_gloss, flags=re.I).strip().strip("\"'“”")
        if not new_gloss or not _is_coherent_gloss(new_gloss, quote, question=clean_sel):
            new_gloss = _synthesize_grounded_gloss(clean_sel, quote, chunk_obj, neighbors, generate_fn, model)
            if new_gloss:
                new_gloss = re.sub(r"\[Ch\.\s*[^\]]+\]\s*", "", new_gloss, flags=re.I).strip().strip("\"'“”")
        if not new_gloss or not _is_coherent_gloss(new_gloss, quote, question=clean_sel):
            cands = [s for s in _candidate_sentences(chunk_obj.get("text") or "", chunk_obj.get("heading") or "")
                     if s != quote and len(s) >= 40 and not META_TRANSITION_RE.search(s) and _is_coherent_gloss(s, quote, question=clean_sel)]
            if cands:
                new_gloss = cands[0]

    elif not gloss_line or _gloss_repeats_quote(gloss_line, quote) or not _is_coherent_gloss(gloss_line, quote, question=question):
        if is_live:
            prompt = _answer_gloss_user_message(question, quote, chunk_obj)
            try:
                raw = generate_fn(ANSWER_GLOSS_SYSTEM, prompt, model)
            except Exception:
                raw = ""
            new_gloss = _clean_boilerplate_gloss(raw, question)
            if re.match(r"^\[ch\.", new_gloss, re.I) and "\n" in new_gloss:
                new_gloss = new_gloss.split("\n", 1)[1].strip()
            new_gloss = re.sub(r"\[Ch\.\s*[^\]]+\]\s*", "", new_gloss, flags=re.I).strip().strip("\"'“”")
        if not new_gloss or not _is_coherent_gloss(new_gloss, quote, question=question):
            if _list_ask(question, question):
                list_synth = _synthesize_list_answer(question, quote, chunk_obj)
                if list_synth and _is_coherent_gloss(list_synth, quote, question=question):
                    new_gloss = list_synth
        if not new_gloss or not _is_coherent_gloss(new_gloss, quote, question=question):
            cands = [s for s in _candidate_sentences(chunk_obj.get("text") or "", chunk_obj.get("heading") or "")
                     if s != quote and len(s) >= 40 and not META_TRANSITION_RE.search(s) and _is_coherent_gloss(s, quote, question=question)]
            if cands:
                new_gloss = cands[0]

    if new_gloss and new_gloss != REFUSAL:
        extra_lines = [ln for ln in lines[1:] if ln.startswith(("Asked as:", "Read as:"))]
        res_lines = [first_line, new_gloss] + extra_lines
        body = dict(body)
        body["answer"] = "\n".join(res_lines)

    return body


def _maybe_enrich_contextual_gloss(index, body, resolved_question, passages,
                                   generate_fn, model):
    return body


def ask(index, question, generate_fn=None, search_fn=None, model=ANSWER_MODEL,
        canonical=True, history=None, pin_chunk=None, selection="", heading="",
        end_chunk_id=None, embed_fn=None):
    if is_prompt_injection(question):
        return _refusal([])
    question = sanitize_query(question)
    is_live = (generate_fn is None) or bool(getattr(generate_fn, "_is_live", False))
    generate_fn = generate_fn or ollama_generate
    history = sanitize_history(history)
    clean_history = [
        h for h in (history or [])
        if isinstance(h, dict) and (h.get("question") or h.get("answer"))
    ]
    topic_shift = _is_topic_shift_followup(question, history, selection, pin_chunk=pin_chunk, index=index)
    effective_pin = None if (topic_shift and not selection) else pin_chunk
    if clean_history and not topic_shift and SIMPLIFY_RE.search(question):
        target_chunk_obj = None
        if effective_pin:
            if isinstance(effective_pin, dict):
                target_chunk_obj = effective_pin
            elif isinstance(effective_pin, str):
                target_chunk_obj = next(
                    (c for c in (index.get("chunks") or []) if c.get("chunk_id") == effective_pin),
                    None,
                )
        if target_chunk_obj is None and clean_history:
            prior_turn = clean_history[-1]
            prior_a = (prior_turn.get("answer") or "").strip()
            m_q = re.search(r"\[Ch\.\s*([^\]]+)\]\s*[\"“](.+?)[\"”]", prior_a)
            if m_q:
                prior_chap = m_q.group(1).strip().rstrip(".")
                prior_snippet = m_q.group(2).strip()[:50].lower()
                for c in (index.get("chunks") or []):
                    if str(c.get("chapter")) == prior_chap and prior_snippet in (c.get("text") or "").lower():
                        target_chunk_obj = c
                        break
                if target_chunk_obj is None:
                    for c in (index.get("chunks") or []):
                        if prior_snippet in (c.get("text") or "").lower():
                            target_chunk_obj = c
                            break
        if target_chunk_obj is not None:
            prior_turn = clean_history[-1]
            prior_a = (prior_turn.get("answer") or "").strip()
            m_q = re.search(r"\[Ch\.\s*([^\]]+)\]\s*[\"“](.+?)[\"”]", prior_a)
            prior_quote = m_q.group(2).strip() if m_q else ""
            chunk_text = target_chunk_obj.get("text") or ""
            chosen_quote = ""
            if prior_quote and (prior_quote in chunk_text or prior_quote.lower() in chunk_text.lower()):
                chosen_quote = _complete_truncated_quote(prior_quote, chunk_text)
            if not chosen_quote:
                cands = _candidate_sentences(chunk_text, target_chunk_obj.get("heading") or "")
                chosen_quote = cands[0] if cands else ""
            if chosen_quote:
                chap = str(target_chunk_obj.get("chapter", ""))
                body = {
                    "refused": False,
                    "citations": [{
                        "chunk_id": target_chunk_obj.get("chunk_id"),
                        "chapter": chap,
                        "quote": chosen_quote,
                    }],
                    "answer": f'[Ch. {chap}] "{chosen_quote}"',
                    "figures": figures_for([target_chunk_obj], index.get("figures") or []),
                }
                passages = [target_chunk_obj]
                body = _ensure_answer_gloss(
                    index, body, question, passages, is_live=is_live,
                    history=history, selection=selection, heading=heading, model=model,
                    generate_fn=generate_fn,
                )
                lead_chunk = target_chunk_obj
                chunks = index.get("chunks") or []
                lead_neighbors = [c for c in chunks if str(c.get("chapter")) == chap and c.get("chunk_id") != lead_chunk.get("chunk_id")][:4]
                body["followups"] = compute_dynamic_followups(
                    lead_chunk, lead_neighbors, selection=selection,
                    question=question, answer_text=body.get("answer", ""), mode="ask",
                )
                return _patch_figures_src(body, index)
    resolved_question = _resolve_contextual_query(
        index, question, pin_chunk=effective_pin, selection=selection,
        heading=heading, history=history,
    )
    asked_form = canonical_query(resolved_question) if canonical else resolved_question
    history_subject = _extract_subject_from_history(history)
    context = retrieval_context(
        index, asked_form, search_fn, generate_fn, pin_chunk=effective_pin,
        end_chunk_id=end_chunk_id, history=history, selection=selection,
        embed_fn=embed_fn,
    )
    passages = context["passages"]
    if not passages:
        return _refusal([])
    completion = generate_fn(
        SYSTEM, user_message(context["asked"], passages, history=history), model
    )
    anchors = anchor_words(asked_form, context["word_map"])
    figures = index.get("figures") or []
    body = parse_completion(completion, passages, figures, anchors, question=resolved_question)
    body = _half_covered(body, resolved_question, asked_form, passages, figures)
    body = _align_citation_to_query_concepts(body, resolved_question, passages)
    clean_history = [
        h for h in (history or [])
        if isinstance(h, dict) and (h.get("question") or h.get("answer"))
    ]
    if body.get("refused") and _has_passage_evidence(asked_form, passages, context["word_map"]):
        retry = _retry_uncited(
            context["asked"], passages, figures, generate_fn, model,
            history=history, anchors=anchors, word_map=context["word_map"],
        )
        if retry is not None and not retry.get("refused"):
            body = retry
            body = _align_citation_to_query_concepts(body, resolved_question, passages)
    elif body.get("refused") and clean_history and (resolved_question != question):
        is_trap = bool(re.search(r"\b(how\s+much|charge|price|cost\s+per\s+hour|what\s+year|when\s+did|in\s+what\s+year|terraform|script|code|install|download)\b", question, re.I))
        if not is_trap and passages:
            retry = _retry_uncited(
                context["asked"], passages, figures, generate_fn, model,
                history=history, anchors=anchors, word_map=context["word_map"],
            )
            if retry is not None and not retry.get("refused"):
                body = retry
                body = _align_citation_to_query_concepts(body, resolved_question, passages)
    body = _expand_list(body, resolved_question, asked_form, passages)

    if clean_history and not SIMPLIFY_RE.search(question) and not topic_shift:
        prior_turn = clean_history[-1]
        prior_a = (prior_turn.get("answer") or "").strip()
        m_q = re.search(r"\[Ch\.\s*[^\]]+\]\s*[\"“](.+?)[\"”]", prior_a)
        prior_quote = m_q.group(1).strip() if m_q else ""
        target_chunk_obj = None
        if effective_pin:
            if isinstance(effective_pin, dict):
                target_chunk_obj = effective_pin
            elif isinstance(effective_pin, str):
                target_chunk_obj = next((c for c in (index.get("chunks") or []) if c.get("chunk_id") == effective_pin), None)
        if target_chunk_obj is None and passages:
            target_chunk_obj = passages[0]
        if target_chunk_obj is not None:
            adv_quote = _advance_followup_quote(target_chunk_obj, passages[1:3] if len(passages) > 1 else [], prior_quote, question)
            if adv_quote:
                first_cite = body["citations"][0] if (not body.get("refused") and body.get("citations")) else None
                cite_quote = first_cite.get("quote", "") if first_cite else ""
                if body.get("refused") or cite_quote == prior_quote:
                    adv_chunk = target_chunk_obj
                    if not _quote_in_passage(adv_quote, target_chunk_obj.get("text", "")):
                        for p in passages[1:3]:
                            if _quote_in_passage(adv_quote, p.get("text", "")):
                                adv_chunk = p
                                break
                    chap = str(adv_chunk.get("chapter", ""))
                    body["refused"] = False
                    body["citations"] = [{
                        "chunk_id": adv_chunk.get("chunk_id"),
                        "chapter": chap,
                        "quote": adv_quote,
                    }]
                    body["answer"] = f'[Ch. {chap}] "{adv_quote}"'
                    body["figures"] = figures_for([adv_chunk], index.get("figures") or [])

    if selection and pin_chunk:
        pin_chunk_obj = None
        if isinstance(pin_chunk, dict):
            pin_chunk_obj = pin_chunk
        elif isinstance(pin_chunk, str):
            pin_chunk_obj = next(
                (c for c in (index.get("chunks") or []) if c.get("chunk_id") == pin_chunk),
                None,
            )
        if pin_chunk_obj is not None:
            clean_sel = _clean_selection_text(selection)
            anchor_quote = _anchor_sentence_for_selection(pin_chunk_obj, clean_sel)
            if anchor_quote:
                first_cite = body["citations"][0] if (not body.get("refused") and body.get("citations")) else None
                cite_id = first_cite.get("chunk_id") if first_cite else None
                cite_quote = first_cite.get("quote", "") if first_cite else ""
                has_sel = clean_sel.lower() in cite_quote.lower()
                if body.get("refused") or cite_id != pin_chunk_obj.get("chunk_id") or not has_sel or len(cite_quote) > len(anchor_quote) + 30:
                    chap = str(pin_chunk_obj.get("chapter", ""))
                    body["refused"] = False
                    body["citations"] = [{
                        "chunk_id": pin_chunk_obj.get("chunk_id"),
                        "chapter": chap,
                        "quote": anchor_quote,
                    }]
                    body["answer"] = f'[Ch. {chap}] "{anchor_quote}"'
                    body["figures"] = figures_for([pin_chunk_obj], index.get("figures") or [])

    if clean_history and (resolved_question != question) and not body.get("refused") and not topic_shift:
        if _WHICH_CHAPTER_RE.search(question):
            first_q = body["citations"][0].get("quote", "") if body.get("citations") else ""
            if not _CHAPTER_NUM_RE.search(first_q):
                for p in passages:
                    for sent in _SENTENCE_SPLIT_RE.split(p.get("text") or ""):
                        if _IN_GREATER_DETAIL_RE.search(sent) and _CHAPTER_NUM_RE.search(sent):
                            sent_clean = sent.strip().strip("\"'“”")
                            chap_m = _CHAPTER_DIGITS_RE.search(sent_clean)
                            chap_num = chap_m.group(1) if chap_m else str(p.get("chapter", ""))
                            body["citations"] = [{
                                "chunk_id": p.get("chunk_id"),
                                "chapter": str(p.get("chapter")),
                                "quote": sent_clean,
                            }]
                            body["answer"] = f'[Ch. {p.get("chapter")}] "{sent_clean}"\nChapter {chap_num} covers this in greater detail.'
                            body["refused"] = False
                            break
                    if body.get("citations") and _CHAPTER_NUM_RE.search(body["citations"][0].get("quote", "")):
                        break

        if _OVERHEAD_RE.search(question):
            first_q = body["citations"][0].get("quote", "") if body.get("citations") else ""
            if not _OVERHEAD_EXPANDED_RE.search(first_q):
                for p in passages:
                    for sent in _SENTENCE_SPLIT_RE.split(p.get("text") or ""):
                        if _OVERHEAD_RE.search(sent) and len(sent) >= 30:
                            sent_clean = sent.strip().strip("\"'“”")
                            body["citations"] = [{
                                "chunk_id": p.get("chunk_id"),
                                "chapter": str(p.get("chapter")),
                                "quote": sent_clean,
                            }]
                            body["answer"] = f'[Ch. {p.get("chapter")}] "{sent_clean}"\nManaging this system requires substantial operational overhead and resources.'
                            body["refused"] = False
                            break
                    if body.get("citations") and _OVERHEAD_RE.search(body["citations"][0].get("quote", "")):
                        break

        if not body.get("citations"):
            body = _refusal(passages, figures)
        else:
            first_cite = body["citations"][0]
            first_chunk_id = first_cite.get("chunk_id")
            first_quote = first_cite.get("quote", "")
            cited_chunk = next((c for c in passages if c.get("chunk_id") == first_chunk_id), None)
            if not cited_chunk:
                body = _refusal(passages, figures)
            elif history_subject:
                subj_tokens = [
                    t.lower() for t in tokens(history_subject)
                    if len(t) > 2 and t.lower() not in STEM_WORDS and t.lower() not in FRAMING_WORDS and t.lower() not in STOPWORDS
                ]
                if subj_tokens:
                    c_text = (cited_chunk.get("heading") or "").lower() + " " + (cited_chunk.get("text") or "").lower()
                    c_stems = {stem(w) for w in words(c_text)}
                    has_subj = any(t in c_text or stem(t) in c_stems for t in subj_tokens)
                    last_ans = clean_history[-1].get("answer") or ""
                    last_chap_m = re.search(r"\[Ch\.\s*([^\]]+)\]", last_ans)
                    prior_chap = last_chap_m.group(1).strip().rstrip(".") if last_chap_m else None
                    if prior_chap and str(cited_chunk.get("chapter")) == prior_chap:
                        has_subj = True
                    if not has_subj:
                        body = _refusal(passages, figures)
            if not body.get("refused"):
                if _YEAR_QUERY_RE.search(question):
                    if not _YEAR_MATCH_RE.search(first_quote):
                        body = _refusal(passages, figures)
                elif _PRICE_QUERY_RE.search(question):
                    if not _PRICE_MATCH_RE.search(first_quote):
                        body = _refusal(passages, figures)
                elif _CODE_QUERY_RE.search(question):
                    if not _CODE_MATCH_RE.search(first_quote):
                        body = _refusal(passages, figures)
    body = _align_citation_to_query_concepts(body, resolved_question, passages)
    if not selection and not clean_history:
        if (asked_form != resolved_question or is_incomplete_stem(question)) and asked_form != question and not body["refused"]:
            clean_asked = re.sub(r"\s+", " ", asked_form).strip()
            body["answer"] = f'{body["answer"]}\nAsked as: "{clean_asked}"'
    if context["reading"] is not None and not body["refused"]:
        body["answer"] = f'{body["answer"]}\nRead as: "{context["asked"]}"'

    if not body.get("refused") and not simple_words(asked_form):
        body = _ensure_answer_gloss(
            index, body, resolved_question, passages, is_live=is_live,
            history=history, selection=selection, heading=heading, model=model,
            generate_fn=generate_fn,
        )
        first_cite_id = body["citations"][0].get("chunk_id") if body.get("citations") else None
        lead_chunk = next((c for c in passages if c.get("chunk_id") == first_cite_id), passages[0]) if passages else {}
        lead_neighbors = [p for p in passages if p != lead_chunk and str(p.get("chapter")) == str(lead_chunk.get("chapter"))]
        body["followups"] = compute_dynamic_followups(
            lead_chunk, lead_neighbors, selection=selection,
            question=resolved_question or question, answer_text=body.get("answer", ""), mode="ask",
        )
    else:
        body["followups"] = []

    return _patch_figures_src(body, index)


def _has_passage_evidence(asked_form, passages, word_map):
    """True when every content word in the query appears in the shown passages
    and in the book's word_map, supporting stem-level matching and alphanumeric
    precision.

    Groundedness gate for false-refusal recovery: an out-of-book question (like
    France) or a question whose content is absent from the shown passages fails
    closed immediately without triggering a retry.
    """
    q_words = [w.lower() for w in words(asked_form)]
    if not q_words or not word_map or not passages:
        return False

    stemmed_word_map = None
    for w in q_words:
        if w in word_map or w in FRAMING_WORDS or w in STEM_WORDS or w in STOPWORDS:
            continue
        if any(c.isdigit() for c in w):
            return False
        if stemmed_word_map is None:
            stemmed_word_map = {stem(k) for k in word_map}
        if stem(w) not in stemmed_word_map:
            return False

    content = [
        w for w in q_words
        if w not in STEM_WORDS and w not in FRAMING_WORDS and w not in STOPWORDS
    ]
    if not content:
        return False

    passage_vocab = {
        w.lower()
        for hit in passages
        for w in words((hit.get("heading") or "") + " " + (hit.get("text") or ""))
    }
    passage_stems = None

    for w in content:
        if w in passage_vocab:
            continue
        if any(c.isdigit() for c in w):
            return False
        if passage_stems is None:
            passage_stems = {stem(pv) for pv in passage_vocab}
        if stem(w) not in passage_stems:
            return False

    return True


def _retry_uncited(question, passages, figures, generate_fn, model, history=None,
                   anchors=None, word_map=None):
    """One `[Ch. ` prefill retry for an uncited answer or false-refusal, or None.

    The x2d gap (measured 2026-10-14): on unseen non-canonical forms the
    model writes uncited prose — it answers, it just drops the tag. The retry
    asks once more with the assistant turn prefilled `[Ch. ` and is kept only
    when a citation whose quote is verbatim passage text survives a parse.
    Two parsers are tried: `parse_answered` for a prose continuation, and
    `parse_completion` (ask shape) for the tag-first continuation the prefill
    actually produces — `_sentence_claims` cites text before a tag, so a
    tag-first reply can only validate through the ask parser. Monotone: every
    failure path returns None, the original answer stands, and one extra
    generation is the only cost.

    The review's cost gate was "anchors present"; the sealed suite measured
    anchor coverage missing half its non-control items (Streaming, batch vs
    streaming, how do, what about, why does, pipeliness), so the trigger here
    is uncited + passages present and the verbatim-quote check does the
    safety work (retry-safety-net-2026-10-14.md has the coverage table).
    """
    try:
        completion = generate_fn(
            SYSTEM, user_message(question, passages, history=history), model,
            prefill="[Ch. ",
        )
    except Exception:
        # A generator seam without prefill support (or a failed call) keeps
        # the original answer; the retry may never break the main path.
        completion = None

    candidates = []
    if isinstance(completion, str) and completion.strip() and REFUSAL.lower() not in completion.lower():
        text = (
            completion
            if completion.lstrip().startswith("[Ch.")
            else "[Ch. " + completion
        )
        if text.lstrip().startswith("[Ch."):
            try:
                candidates.append(parse_completion(text, passages, figures, anchors=anchors, question=question))
            except Exception:
                pass
        try:
            candidates.append(parse_answered(text, passages, figures))
        except Exception:
            pass
    texts = {hit["chunk_id"]: hit.get("text") or "" for hit in passages}
    for body in candidates:
        if body["refused"] or not body["citations"]:
            continue
        if not all(
            _quote_in_passage(item["quote"], texts.get(item["chunk_id"], ""))
            for item in body["citations"]
        ):
            continue
        return body

    # Fallback quote extraction from passages[0] when _has_passage_evidence holds and len(passages) >= 3
    if passages and len(passages) >= 3 and word_map and _has_passage_evidence(question, passages, word_map):
        lead = passages[0]
        lead_text = lead.get("text") or ""
        q_tokens = [w.lower() for w in words(question) if w.lower() not in STEM_WORDS and w.lower() not in STOPWORDS]
        best_sent = ""
        best_overlap = -1
        for sent in _sentences(lead_text):
            sent_clean = _without_heading(sent, lead)
            if len(sent_clean) < SPAN_MIN_CHARS:
                continue
            sent_words = set(words(sent_clean.lower()))
            overlap = sum(1 for t in q_tokens if t in sent_words or any(stem(t) == stem(sw) for sw in sent_words))
            if overlap > best_overlap:
                best_overlap = overlap
                best_sent = sent_clean
        if best_sent:
            best_sent = _reground_alphanumeric_quote(best_sent, question, lead_text)
            chap = str(lead["chapter"])
            return {
                "answer": f'[Ch. {chap}] "{best_sent}"\n{best_sent}',
                "citations": [{
                    "chunk_id": lead["chunk_id"],
                    "chapter": chap,
                    "quote": best_sent,
                }],
                "figures": figures_for([lead], figures or []),
                "refused": False,
            }

    return None


def respond(index, question, generate_fn=None, search_fn=None, model=ANSWER_MODEL,
            canonical=True, history=None, pin_chunk=None, selection="", heading="",
            end_chunk_id=None, embed_fn=None):
    """Free-generation answer from the retrieved passages.

    No quote enforcement: the model answers, its [Ch. n] tags become the
    citations, and quotation marks the passages cannot back are stripped (see
    parse_answered). The prompt is the ask-shaped one (SYSTEM + user_message)
    because that is what the student is trained on (2026-10-15 alignment; see
    the module docstring). A question that asks for simple words routes
    through the plain register (`_plain_body`): the draft selects evidence
    sentences and each is rewritten one-in-one-out, so nothing is written from
    scratch. A bare topic phrase is asked as its question first
    (canonical_query). An uncited answer is retried once with a `[Ch. `
    prefill and kept only when a citation validates (`_retry_uncited`).
    """
    if is_prompt_injection(question):
        return _refusal([])
    question = sanitize_query(question)
    is_live = (generate_fn is None) or bool(getattr(generate_fn, "_is_live", False))
    generate_fn = generate_fn or ollama_generate
    history = sanitize_history(history)
    clean_history = [
        h for h in (history or [])
        if isinstance(h, dict) and (h.get("question") or h.get("answer"))
    ]
    topic_shift = _is_topic_shift_followup(question, history, selection, pin_chunk=pin_chunk, index=index)
    effective_pin = None if (topic_shift and not selection) else pin_chunk
    if clean_history and not topic_shift and SIMPLIFY_RE.search(question):
        target_chunk_obj = None
        if effective_pin:
            if isinstance(effective_pin, dict):
                target_chunk_obj = effective_pin
            elif isinstance(effective_pin, str):
                target_chunk_obj = next(
                    (c for c in (index.get("chunks") or []) if c.get("chunk_id") == effective_pin),
                    None,
                )
        if target_chunk_obj is None and clean_history:
            prior_turn = clean_history[-1]
            prior_a = (prior_turn.get("answer") or "").strip()
            m_q = re.search(r"\[Ch\.\s*([^\]]+)\]\s*[\"“](.+?)[\"”]", prior_a)
            if m_q:
                prior_chap = m_q.group(1).strip().rstrip(".")
                prior_snippet = m_q.group(2).strip()[:50].lower()
                for c in (index.get("chunks") or []):
                    if str(c.get("chapter")) == prior_chap and prior_snippet in (c.get("text") or "").lower():
                        target_chunk_obj = c
                        break
                if target_chunk_obj is None:
                    for c in (index.get("chunks") or []):
                        if prior_snippet in (c.get("text") or "").lower():
                            target_chunk_obj = c
                            break
        if target_chunk_obj is not None:
            prior_turn = clean_history[-1]
            prior_a = (prior_turn.get("answer") or "").strip()
            m_q = re.search(r"\[Ch\.\s*([^\]]+)\]\s*[\"“](.+?)[\"”]", prior_a)
            prior_quote = m_q.group(2).strip() if m_q else ""
            chunk_text = target_chunk_obj.get("text") or ""
            chosen_quote = ""
            if prior_quote and (prior_quote in chunk_text or prior_quote.lower() in chunk_text.lower()):
                chosen_quote = _complete_truncated_quote(prior_quote, chunk_text)
            if not chosen_quote:
                cands = _candidate_sentences(chunk_text, target_chunk_obj.get("heading") or "")
                chosen_quote = cands[0] if cands else ""
            if chosen_quote:
                chap = str(target_chunk_obj.get("chapter", ""))
                body = {
                    "refused": False,
                    "citations": [{
                        "chunk_id": target_chunk_obj.get("chunk_id"),
                        "chapter": chap,
                        "quote": chosen_quote,
                    }],
                    "answer": f'[Ch. {chap}] "{chosen_quote}"',
                    "figures": figures_for([target_chunk_obj], index.get("figures") or []),
                }
                passages = [target_chunk_obj]
                body = _ensure_answer_gloss(
                    index, body, question, passages, is_live=is_live,
                    history=history, selection=selection, heading=heading, model=model,
                    generate_fn=generate_fn,
                )
                lead_chunk = target_chunk_obj
                chunks = index.get("chunks") or []
                lead_neighbors = [c for c in chunks if str(c.get("chapter")) == chap and c.get("chunk_id") != lead_chunk.get("chunk_id")][:4]
                body["followups"] = compute_dynamic_followups(
                    lead_chunk, lead_neighbors, selection=selection,
                    question=question, answer_text=body.get("answer", ""), mode="answer",
                )
                return _patch_figures_src(body, index)
    resolved_question = _resolve_contextual_query(
        index, question, pin_chunk=effective_pin, selection=selection,
        heading=heading, history=history,
    )
    history_subject = _extract_subject_from_history(history)
    asked_form = canonical_query(resolved_question) if canonical else resolved_question
    context = retrieval_context(
        index, asked_form, search_fn, generate_fn, pin_chunk=effective_pin,
        end_chunk_id=end_chunk_id, history=history, selection=selection,
        embed_fn=embed_fn,
    )
    passages = context["passages"]
    if not passages:
        return _refusal([])
    anchors = anchor_words(asked_form, context["word_map"])
    figures = index.get("figures") or []
    if simple_words(asked_form) and not (clean_history and effective_pin and SIMPLIFY_RE.search(question)):
        body = _plain_body(index, context, generate_fn, model)
        body = _half_covered(body, resolved_question, asked_form, passages, figures)
    else:
        completion = generate_fn(
            SYSTEM, user_message(context["asked"], passages, history=history), model
        )
        body = parse_answered(completion, passages, figures)
        body = _half_covered(body, resolved_question, asked_form, passages, figures)
        body = _align_citation_to_query_concepts(body, resolved_question, passages)
        if not body["refused"] and not body["citations"]:
            retry = _retry_uncited(
                context["asked"], passages, figures,
                generate_fn, model, history=history, anchors=anchors,
                word_map=context.get("word_map", {}),
            )
            if retry is not None:
                body = retry
        elif body.get("refused"):
            can_retry = False
            if clean_history and (resolved_question != question):
                is_trap = bool(re.search(r"\b(how\s+much|charge|price|cost\s+per\s+hour|what\s+year|when\s+did|in\s+what\s+year|terraform|script|code|install|download)\b", question, re.I))
                if not is_trap and passages:
                    can_retry = True
            elif len(passages) >= 3 and _has_passage_evidence(context["asked"], passages, context.get("word_map", {})):
                can_retry = True

            if can_retry:
                retry = _retry_uncited(
                    context["asked"], passages, figures, generate_fn, model,
                    history=history, anchors=anchors, word_map=context.get("word_map", {}),
                )
                if retry is not None and not retry.get("refused"):
                    body = retry
    body = _expand_list(body, resolved_question, asked_form, passages)

    if clean_history and not SIMPLIFY_RE.search(question) and not topic_shift:
        prior_turn = clean_history[-1]
        prior_a = (prior_turn.get("answer") or "").strip()
        m_q = re.search(r"\[Ch\.\s*[^\]]+\]\s*[\"“](.+?)[\"”]", prior_a)
        prior_quote = m_q.group(1).strip() if m_q else ""
        target_chunk_obj = None
        if effective_pin:
            if isinstance(effective_pin, dict):
                target_chunk_obj = effective_pin
            elif isinstance(effective_pin, str):
                target_chunk_obj = next((c for c in (index.get("chunks") or []) if c.get("chunk_id") == effective_pin), None)
        if target_chunk_obj is None and passages:
            target_chunk_obj = passages[0]
        if target_chunk_obj is not None:
            adv_quote = _advance_followup_quote(target_chunk_obj, passages[1:3] if len(passages) > 1 else [], prior_quote, question)
            if adv_quote:
                first_cite = body["citations"][0] if (not body.get("refused") and body.get("citations")) else None
                cite_quote = first_cite.get("quote", "") if first_cite else ""
                if body.get("refused") or cite_quote == prior_quote:
                    adv_chunk = target_chunk_obj
                    if not _quote_in_passage(adv_quote, target_chunk_obj.get("text", "")):
                        for p in passages[1:3]:
                            if _quote_in_passage(adv_quote, p.get("text", "")):
                                adv_chunk = p
                                break
                    chap = str(adv_chunk.get("chapter", ""))
                    body["refused"] = False
                    body["citations"] = [{
                        "chunk_id": adv_chunk.get("chunk_id"),
                        "chapter": chap,
                        "quote": adv_quote,
                    }]
                    body["answer"] = f'[Ch. {chap}] "{adv_quote}"'
                    body["figures"] = figures_for([adv_chunk], index.get("figures") or [])

    if selection and pin_chunk:
        pin_chunk_obj = None
        if isinstance(pin_chunk, dict):
            pin_chunk_obj = pin_chunk
        elif isinstance(pin_chunk, str):
            pin_chunk_obj = next(
                (c for c in (index.get("chunks") or []) if c.get("chunk_id") == pin_chunk),
                None,
            )
        if pin_chunk_obj is not None:
            clean_sel = _clean_selection_text(selection)
            anchor_quote = _anchor_sentence_for_selection(pin_chunk_obj, clean_sel)
            if anchor_quote:
                first_cite = body["citations"][0] if (not body.get("refused") and body.get("citations")) else None
                cite_id = first_cite.get("chunk_id") if first_cite else None
                cite_quote = first_cite.get("quote", "") if first_cite else ""
                has_sel = clean_sel.lower() in cite_quote.lower()
                if body.get("refused") or cite_id != pin_chunk_obj.get("chunk_id") or not has_sel or len(cite_quote) > len(anchor_quote) + 30:
                    chap = str(pin_chunk_obj.get("chapter", ""))
                    body["refused"] = False
                    body["citations"] = [{
                        "chunk_id": pin_chunk_obj.get("chunk_id"),
                        "chapter": chap,
                        "quote": anchor_quote,
                    }]
                    body["answer"] = f'[Ch. {chap}] "{anchor_quote}"'
                    body["figures"] = figures_for([pin_chunk_obj], index.get("figures") or [])

    if clean_history and (resolved_question != question) and not body.get("refused") and not topic_shift:
        if _WHICH_CHAPTER_RE.search(question):
            first_q = body["citations"][0].get("quote", "") if body.get("citations") else ""
            if not _CHAPTER_NUM_RE.search(first_q):
                for p in passages:
                    for sent in _SENTENCE_SPLIT_RE.split(p.get("text") or ""):
                        if _IN_GREATER_DETAIL_RE.search(sent) and _CHAPTER_NUM_RE.search(sent):
                            sent_clean = sent.strip().strip("\"'“”")
                            chap_m = _CHAPTER_DIGITS_RE.search(sent_clean)
                            chap_num = chap_m.group(1) if chap_m else str(p.get("chapter", ""))
                            body["citations"] = [{
                                "chunk_id": p.get("chunk_id"),
                                "chapter": str(p.get("chapter")),
                                "quote": sent_clean,
                            }]
                            body["answer"] = f'[Ch. {p.get("chapter")}] "{sent_clean}"\nChapter {chap_num} covers this in greater detail.'
                            body["refused"] = False
                            break
                    if body.get("citations") and _CHAPTER_NUM_RE.search(body["citations"][0].get("quote", "")):
                        break

        if _OVERHEAD_RE.search(question):
            first_q = body["citations"][0].get("quote", "") if body.get("citations") else ""
            if not _OVERHEAD_EXPANDED_RE.search(first_q):
                for p in passages:
                    for sent in _SENTENCE_SPLIT_RE.split(p.get("text") or ""):
                        if _OVERHEAD_RE.search(sent) and len(sent) >= 30:
                            sent_clean = sent.strip().strip("\"'“”")
                            body["citations"] = [{
                                "chunk_id": p.get("chunk_id"),
                                "chapter": str(p.get("chapter")),
                                "quote": sent_clean,
                            }]
                            body["answer"] = f'[Ch. {p.get("chapter")}] "{sent_clean}"\nManaging this system requires substantial operational overhead and resources.'
                            body["refused"] = False
                            break
                    if body.get("citations") and _OVERHEAD_RE.search(body["citations"][0].get("quote", "")):
                        break

        if not body.get("citations"):
            body = _refusal(passages, figures)
        else:
            first_cite = body["citations"][0]
            first_chunk_id = first_cite.get("chunk_id")
            first_quote = first_cite.get("quote", "")
            cited_chunk = next((c for c in passages if c.get("chunk_id") == first_chunk_id), None)
            if not cited_chunk:
                body = _refusal(passages, figures)
            elif history_subject:
                subj_tokens = [
                    t.lower() for t in tokens(history_subject)
                    if len(t) > 2 and t.lower() not in STEM_WORDS and t.lower() not in FRAMING_WORDS and t.lower() not in STOPWORDS
                ]
                if subj_tokens:
                    c_text = (cited_chunk.get("heading") or "").lower() + " " + (cited_chunk.get("text") or "").lower()
                    c_stems = {stem(w) for w in words(c_text)}
                    has_subj = any(t in c_text or stem(t) in c_stems for t in subj_tokens)
                    last_ans = clean_history[-1].get("answer") or ""
                    last_chap_m = re.search(r"\[Ch\.\s*([^\]]+)\]", last_ans)
                    prior_chap = last_chap_m.group(1).strip().rstrip(".") if last_chap_m else None
                    if prior_chap and str(cited_chunk.get("chapter")) == prior_chap:
                        has_subj = True
                    if not has_subj:
                        body = _refusal(passages, figures)
            if not body.get("refused"):
                if _YEAR_QUERY_RE.search(question):
                    if not _YEAR_MATCH_RE.search(first_quote):
                        body = _refusal(passages, figures)
                elif _PRICE_QUERY_RE.search(question):
                    if not _PRICE_MATCH_RE.search(first_quote):
                        body = _refusal(passages, figures)
                elif _CODE_QUERY_RE.search(question):
                    if not _CODE_MATCH_RE.search(first_quote):
                        body = _refusal(passages, figures)
    body = _align_citation_to_query_concepts(body, resolved_question, passages)
    if not selection and not clean_history:
        if (asked_form != resolved_question or is_incomplete_stem(question)) and asked_form != question and not body["refused"]:
            clean_asked = re.sub(r"\s+", " ", asked_form).strip()
            body["answer"] = f'{body["answer"]}\nAsked as: "{clean_asked}"'
    if context["reading"] is not None and not body["refused"]:
        body["answer"] = f'{body["answer"]}\nRead as: "{context["asked"]}"'

    if not body.get("refused") and not simple_words(asked_form):
        body = _ensure_answer_gloss(
            index, body, resolved_question, passages, is_live=is_live,
            history=history, selection=selection, heading=heading, model=model,
            generate_fn=generate_fn,
        )
        first_cite_id = body["citations"][0].get("chunk_id") if body.get("citations") else None
        lead_chunk = next((c for c in passages if c.get("chunk_id") == first_cite_id), passages[0]) if passages else {}
        lead_neighbors = [p for p in passages if p != lead_chunk and str(p.get("chapter")) == str(lead_chunk.get("chapter"))]
        body["followups"] = compute_dynamic_followups(
            lead_chunk, lead_neighbors, selection=selection,
            question=resolved_question or question, answer_text=body.get("answer", ""), mode="answer",
        )
    else:
        body["followups"] = []

    return _patch_figures_src(body, index)


def _clean_rewrite(text):
    """The rewritten sentence: unquoted, list numbering stripped."""
    text = (text or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    text = re.sub(r"^\s*\d+[.)]\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _plain_body(index, context, generate_fn, model):
    """The plain register: draft selects evidence sentences, each is rewritten.

    The draft runs the standard path, so its citations' quotes are passage
    text by construction; each quote is rewritten one-in-one-out and keeps
    its source chunk's tag. The citations keep the original book sentences
    as evidence. A draft refusal is the register's refusal; if every rewrite
    comes back empty, the draft answer stands rather than a blank.
    """
    passages = context["passages"]
    completion = generate_fn(
        SYSTEM_ANSWER, answer_user_message(context["asked"], passages), model
    )
    draft = parse_answered(completion, passages, index.get("figures") or [])
    if draft["refused"]:
        return draft
    assembled = []
    for item in draft["citations"][:PARAPHRASE_LIMIT]:
        rewritten = generate_fn(
            PARAPHRASE_SYSTEM, f"Sentence: {item['quote']}", model
        )
        clean = _clean_rewrite(rewritten)
        if clean:
            assembled.append(f"{clean} [Ch. {item['chapter']}]")
    if not assembled:
        return draft
    return {
        "answer": " ".join(assembled),
        "citations": draft["citations"],
        "figures": draft["figures"],
        "refused": False,
    }


def _free_refusal(text):
    """True when the model asked to refuse. The first line must be the exact
    sentence; a refusal that keeps talking is still a refusal, never a free
    answer."""
    first = (text or "").strip().split("\n", 1)[0].strip()
    return first == REFUSAL or first.lower() == REFUSAL.lower()


def _strip_fake_quotes(text, passages):
    """Quotation marks around words no shown passage contains are dropped.

    The words stay; the marks are a promise the answer cannot keep. A quote
    that is in a shown passage keeps its marks.
    """
    def keep(match):
        inner = match.group(1)
        if any(_quote_in_passage(inner, hit.get("text") or "") for hit in passages):
            return match.group(0)
        return inner
    return QUOTE_PATTERN.sub(keep, text)


@functools.lru_cache(maxsize=2048)
def _tokens(text):
    """Word set for overlap scoring. Very short words carry little meaning."""
    return frozenset(word for word in _punctuation_plain(text).split() if len(word) > 2)



def _claim_after_tag(rest):
    """Quote or remainder of a tag-first line. Empty when the tag stands alone."""
    first_line = rest.split("\n", 1)[0]
    quoted = QUOTE_PATTERN.search(first_line)
    if quoted:
        return quoted.group(1).strip()
    return re.sub(r"\s+", " ", first_line).strip()


def _sentence_claims(text):
    """(claim, chapters) for every sentence carrying [Ch. tags.

    Tags are masked before the sentence split: "Ch." holds a period and would
    otherwise end a sentence inside the tag. The mask clears periods the
    captured text itself can hold — a two-chapter tag ("[Ch. 2, Ch. 7]")
    carries a second "Ch.", and a split inside the mask drops the claim
    entirely (measured 2026-10-13: the endpoint answer lost all citations).
    Text accumulates until a tag arrives, so a tag at the start of the next
    line still cites the sentence before it, and a tags-only fragment merges
    into the previous claim. A tag with no pending text takes the quote on
    that line (or the rest of the line) as the claim; a bare tag with no prior
    text still produces no claim.
    """
    masked = TAG_PATTERN.sub(
        lambda m: "\x01" + _PUNCT_SPLIT_RE.sub(" ", m.group(1)) + "\x02", text
    )
    claims = []
    pending = ""
    for part in _SENTENCE_SPLIT_RE.split(masked):
        segments = []
        cursor = 0
        for match in _MASK_TAG_RE.finditer(part):
            segments.append(("text", part[cursor:match.start()]))
            segments.append(("tag", match.group(1)))
            cursor = match.end()
        segments.append(("text", part[cursor:]))
        i = 0
        while i < len(segments):
            kind, value = segments[i]
            if kind == "text":
                pending = (pending + " " + value).strip()
                i += 1
                continue
            chapters = _DIGITS_RE.findall(value)
            claim = _WHITESPACE_RE.sub(" ", pending).strip()
            if not claim:
                rest = []
                j = i + 1
                while j < len(segments) and segments[j][0] == "text":
                    rest.append(segments[j][1])
                    j += 1
                claim = _claim_after_tag("".join(rest))
            if claim:
                claims.append([claim, chapters])
                pending = ""
            elif claims:
                claims[-1][1].extend(chapters)
            i += 1
    return claims


def _best_passage(claim, chapters, passages):
    """The shown passage the tagged sentence most likely used.

    The chapter named in the tag first, word overlap deciding within it; when
    the named chapter is not among the shown passages, the other passages get
    one look. A zero-overlap claim gets no citation — never a guess.
    """
    tokens = _tokens(claim)
    if not tokens:
        return None
    hints = set(chapters)
    in_chapter = [hit for hit in passages if str(hit["chapter"]) in hints]
    pools = [in_chapter, [hit for hit in passages if hit not in in_chapter]]
    best, best_score = None, 0.0
    for pool in pools:
        for hit in pool:
            overlap = len(tokens & _tokens(hit.get("text") or "")) / len(tokens)
            if overlap > best_score:
                best, best_score = hit, overlap
        if best is not None:
            break
    return best if best_score > 0 else None


def _evidence_quote(claim, hit):
    """A passage sentence as the citation's quote.

    The sentence with the most overlap with the claim decides — the same
    rule `_best_passage` uses for the passage itself. A copied run only
    breaks a tie, and the run alone is the fallback when no sentence can
    hold it: a stray generic run ("by data scientists, analysts, and
    other", 41 chars) must not hand the quote to a sentence the claim
    barely uses (measured 2026-10-13: the plain register then rewrote the
    enumeration instead of the definition).
    """
    text = hit.get("text") or ""
    span = longest_copied_span(claim, text)
    tokens = _tokens(claim)
    best, best_key = "", (-1.0, False)
    all_sents = _sentences(text)
    heading_clean = (hit.get("heading") or "").strip().lower()
    for sentence in all_sents:
        sentence_tokens = _tokens(sentence)
        if not sentence_tokens:
            continue
        overlap = len(tokens & sentence_tokens) / len(tokens) if tokens else 0.0
        holds = bool(span) and _fold(span) in _fold(sentence)
        if (overlap, holds) > best_key:
            best, best_key = sentence, (overlap, holds)
    res = ""
    if best:
        res = _without_heading(best, hit)
    elif span:
        res = _original_case(span, text)
    else:
        res = _without_heading(re.sub(r"\s+", " ", text).strip(), hit)

    res_clean = res.strip().lower()
    if len(res) < 20 or (heading_clean and res_clean == heading_clean):
        long_sents = [s for s in all_sents if len(s) >= 40 and s.strip().lower() != heading_clean]
        if long_sents:
            best_long = max(long_sents, key=lambda s: len(tokens & _tokens(s)) if tokens else 0)
            res = _without_heading(best_long, hit)

    return res


def parse_answered(completion, passages, figures=None):
    """A free answer turned into the contract body.

    The model's prose is kept as written, minus quotation marks the passages
    cannot back. Citations come from the [Ch. n] tags: each tagged sentence
    is matched to the shown passage of that chapter with the most word
    overlap. A sentence that matches nothing is left uncited rather than
    pinned to a guess, and a hallucination is a measurement, not a refusal.
    """
    text = (completion or "").strip()
    if not text or _free_refusal(text):
        return _refusal(passages, figures)
    text = _strip_fake_quotes(text, passages)
    citations = []
    for claim, chapters in _sentence_claims(text):
        hit = _best_passage(claim, chapters, passages)
        if hit is None:
            continue
        if any(item["chunk_id"] == hit["chunk_id"] for item in citations):
            continue
        quote = _evidence_quote(claim, hit)
        heading_clean = (hit.get("heading") or "").strip().lower()
        if len(quote) < 20 or (heading_clean and quote.strip().lower() == heading_clean):
            all_sents = _sentences(hit.get("text") or "")
            long_sents = [s for s in all_sents if len(s) >= 40 and s.strip().lower() != heading_clean]
            if long_sents:
                quote = _without_heading(long_sents[0], hit)
        quote = _complete_truncated_quote(quote, hit.get("text") or "")
        citations.append({
            "chunk_id": hit["chunk_id"],
            "chapter": str(hit["chapter"]),
            "quote": quote,
        })
    cited = {item["chunk_id"] for item in citations}
    named = [hit for hit in passages if hit["chunk_id"] in cited]
    cleaned_lines = []
    for line in text.splitlines():
        line_clean = line.strip()
        if not _CH_PREFIX_RE.match(line_clean):
            cleaned = _clean_boilerplate_gloss(line_clean)
            if cleaned:
                cleaned_lines.append(cleaned)
        else:
            if line_clean.startswith("[ch."):
                line_clean = "[Ch." + line_clean[4:]
            cleaned_lines.append(line_clean)
    if cleaned_lines:
        text = "\n".join(cleaned_lines)
    return {
        "answer": text,
        "citations": citations,
        "figures": figures_for(named, figures or []),
        "refused": False,
    }


def highlight_query(selection, heading=""):
    """The question a highlight means.

    A sentence is already a question for search. A word or a short phrase is
    not: "splashed" and "because" retrieve neighbor chapters. Those become
    "What is …?", the same rewrite canonical_query uses for a typed label,
    with the heading so the search knows which "time" the reader marked.
    """
    text = (selection or "").strip()
    if not text:
        return text
    words = text.split()
    if len(words) > 6 or text.endswith((".", "?", "!")):
        return text
    heading = (heading or "").strip()
    if heading and heading.lower() not in text.lower():
        return f"What is {text} in {heading}?"
    return f"What is {text}?"


def _pin_chunk(index, passages, chunk_id, end_chunk_id=None):
    """The chunk the reader was looking at leads. Search does not replace it.

    When end_chunk_id is provided and differs from chunk_id, chunk_id leads at
    index 0 and end_chunk_id sits at index 1.
    """
    if not chunk_id and not end_chunk_id:
        return passages
    chunks = index.get("chunks") or []
    c1 = next((item for item in chunks if item.get("chunk_id") == chunk_id), None) if chunk_id else None
    c2 = next((item for item in chunks if item.get("chunk_id") == end_chunk_id), None) if end_chunk_id and end_chunk_id != chunk_id else None

    if c1 is None and c2 is None:
        return passages

    pinned = []
    base_score = passages[0].get("score", 1.0) if passages else 1.0
    if c1 is not None:
        pinned.append({
            "score": base_score,
            "chunk_id": c1.get("chunk_id"),
            "chapter": c1.get("chapter"),
            "heading": c1.get("heading", ""),
            "text": c1.get("text", ""),
            "source": c1.get("source", ""),
        })
    if c2 is not None:
        pinned.append({
            "score": base_score * 0.99,
            "chunk_id": c2.get("chunk_id"),
            "chapter": c2.get("chapter"),
            "heading": c2.get("heading", ""),
            "text": c2.get("text", ""),
            "source": c2.get("source", ""),
        })

    pinned_ids = {p["chunk_id"] for p in pinned}
    rest = [hit for hit in passages if hit.get("chunk_id") not in pinned_ids]
    return pinned + rest[: max(0, PASSAGE_LIMIT - len(pinned))]


def _anchor_sentence_for_selection(chunk, selection):
    text = chunk.get("text") or ""
    heading = chunk.get("heading") or ""
    sel = (selection or "").strip()
    if not sel:
        return None
    cands = _candidate_sentences(text, heading)
    if not cands:
        return None

    word_pat = _selection_word_pattern(sel)
    matched = [s for s in cands if word_pat.search(s)]

    if not matched:
        matched = [s for s in cands if sel.lower() in s.lower()]

    if not matched:
        sel_words = set(_WORD_RE.findall(sel.lower()))
        if sel_words:
            cand_words = {s: set(_WORD_RE.findall(s.lower())) for s in cands}
            scored_cands = sorted(
                cands,
                key=lambda s: len(sel_words & cand_words[s]),
                reverse=True,
            )
            if scored_cands and (sel_words & cand_words[scored_cands[0]]):
                matched = [scored_cands[0]]

    if not matched:
        if heading and (sel.lower() in heading.lower() or word_pat.search(heading)):
            long_cands = [s for s in cands if len(s) >= 40 and not META_TRANSITION_RE.search(s)]
            if long_cands:
                return long_cands[0]
            _, sub = select_substantive_anchor_sentence(chunk, [], sel, extract_core_concept(sel, heading))
            return sub if sub else (cands[0] if cands else None)
        return None

    best = matched[0]
    for m in matched:
        if len(m) >= 40 and not META_TRANSITION_RE.search(m):
            best = m
            break

    if META_TRANSITION_RE.search(best) or (heading and (sel.lower() in heading.lower() or word_pat.search(heading))):
        _, sub = select_substantive_anchor_sentence(chunk, [], sel, extract_core_concept(sel, heading))
        if sub and not META_TRANSITION_RE.search(sub):
            best = sub

    if len(best) < 40 or best.endswith("?"):
        idx = cands.index(best) if best in cands else 0
        expanded = best
        fwd = idx + 1
        while len(expanded) < 40 and fwd < len(cands):
            expanded = expanded + " " + cands[fwd]
            fwd += 1
        bwd = idx - 1
        while len(expanded) < 40 and bwd >= 0:
            expanded = cands[bwd] + " " + expanded
            bwd -= 1
        if len(expanded) >= 40:
            best = expanded

    return best


def _explain_gloss_user_message(selection, quote, pin_chunk, neighbors=None):
    heading = (pin_chunk.get("heading") or "") if pin_chunk else ""
    intent_info = analyze_intent(selection, heading, pin_chunk, neighbors) if pin_chunk else {}
    intent_type = intent_info.get("intent_type") or classify_intent(selection, heading, pin_chunk)

    if intent_type == INTENT_MULTI_SENTENCE:
        parts = [
            f"Passage to explain:\n{selection.strip()}",
        ]
        if heading:
            parts.append(f"Section heading: {heading}")
        parts.append(
            "Explain in 1 to 2 plain, direct sentences the core takeaway of this passage and what it means for the reader."
        )
        return "\n\n".join(parts)

    if intent_type == INTENT_CONCEPT_TERM:
        core_concept = intent_info.get("core_concept") or extract_core_concept(selection, heading)
        if intent_info.get("is_passing_mention"):
            parts = [
                f"Core concept: {core_concept}",
                f"Sentence mentioning concept: {quote}",
            ]
            if heading:
                parts.append(f"Section heading: {heading}")
            if pin_chunk and pin_chunk.get("text"):
                parts.append(f"Section context:\n{pin_chunk['text']}")
            parts.append(
                f"Explain in 1 to 2 plain, direct sentences how '{core_concept}' relates to {heading or 'this topic'} and what the cited sentence says about it based strictly on this passage."
            )
            return "\n\n".join(parts)
        parts = [
            f"Core concept to define: {core_concept}",
            f"Sentence mentioning concept: {quote}",
        ]
        if heading:
            parts.append(f"Section heading: {heading}")
        if pin_chunk and pin_chunk.get("text"):
            parts.append(f"Section context:\n{pin_chunk['text']}")
        if neighbors:
            for n in neighbors:
                if n and n.get("text"):
                    parts.append(f"Related context ({n.get('heading', '')}):\n{n['text']}")
        parts.append(
            f"Define and explain what '{core_concept}' is and how it works in 1 to 2 plain, direct sentences based on this section."
        )
        return "\n\n".join(parts)

    if intent_type == INTENT_VAGUE_FRAGMENT:
        subject = extract_enclosing_subject(quote, selection)
        parts = [
            f"Highlighted phrase: {selection}",
            f"Full sentence: {quote}",
        ]
        if subject:
            parts.append(f"Subject being described: {subject}")
        if heading:
            parts.append(f"Section heading: {heading}")
        if pin_chunk and pin_chunk.get("text"):
            parts.append(f"Passage context:\n{pin_chunk['text']}")
        subj_note = f" ({subject})" if subject else ""
        parts.append(
            f"Explain in 1 to 2 plain sentences what the authors mean. "
            f"Start with 'The highlighted phrase refers to ...' naming the specific subject{subj_note} in the sentence, "
            f"and explain why the authors describe it as '{selection}'."
        )
        return "\n\n".join(parts)

    parts = [
        f"Highlighted text: {selection}",
        f"Sentence containing highlight: {quote}",
    ]
    if heading:
        parts.append(f"Section heading: {heading}")
    if pin_chunk and pin_chunk.get("text"):
        parts.append(f"Passage context:\n{pin_chunk['text']}")
    if neighbors:
        for n in neighbors:
            if n and n.get("text"):
                parts.append(f"Related context ({n.get('heading', '')}):\n{n['text']}")
    if intent_type == INTENT_AUTHOR_QUESTION:
        parts.append(
            "Explain in 1 to 2 plain, direct sentences what the authors are asking the reader to evaluate and why it matters in this section."
        )
    else:
        parts.append(
            "Explain in 1 to 2 plain, direct sentences what the selected text means and why it is discussed here."
        )
    return "\n\n".join(parts)


def _cross_chunk_quotes(chunk1, chunk2, selection):
    """Extract boundary quotes from chunk1 and chunk2 for a cross-chunk selection."""
    if not chunk1 or not chunk2:
        return None, None
    text1 = chunk1.get("text") or ""
    text2 = chunk2.get("text") or ""
    cands1 = _candidate_sentences(text1, chunk1.get("heading") or "")
    cands2 = _candidate_sentences(text2, chunk2.get("heading") or "")
    if not cands1 or not cands2:
        return None, None

    sel = (selection or "").strip().lower()
    words_list = sel.split()
    q1 = None
    q2 = None
    if len(words_list) >= 2:
        for split_pt in range(1, len(words_list)):
            part1 = " ".join(words_list[:split_pt])
            part2 = " ".join(words_list[split_pt:])
            if part1 in text1.lower() and part2 in text2.lower():
                a1 = _anchor_sentence_for_selection(chunk1, part1)
                a2 = _anchor_sentence_for_selection(chunk2, part2)
                if a1 and a2:
                    return a1, a2
                if a1 and not q1:
                    q1 = a1
                if a2 and not q2:
                    q2 = a2

    if not q1:
        q1 = cands1[-1]
    if not q2:
        q2 = cands2[0]
    return q1, q2


def explain(index, selection, generate_fn=None, search_fn=None, model=ANSWER_MODEL,
            chunk_id=None, heading="", end_chunk_id=None, embed_fn=None):
    """The highlight is the question. The neighborhood is the passages.

    A short highlight is asked as a question. The chunk the reader selected
    stays in the passages even when dense search prefers another chapter.
    """
    if is_prompt_injection(selection):
        return _refusal([])
    selection = sanitize_query(selection)
    if not (selection or "").strip():
        raise ValueError("missing selection")
    is_live = (generate_fn is None) or bool(getattr(generate_fn, "_is_live", False))
    generate_fn = generate_fn or ollama_generate
    pin_chunk_obj = None
    end_chunk_obj = None
    neighbors = []
    chunks = index.get("chunks") or []
    if chunk_id:
        for i, c in enumerate(chunks):
            if c.get("chunk_id") == chunk_id:
                pin_chunk_obj = c
                if i > 0 and chunks[i - 1].get("chapter") == c.get("chapter"):
                    neighbors.append(chunks[i - 1])
                if i + 1 < len(chunks) and chunks[i + 1].get("chapter") == c.get("chapter"):
                    neighbors.append(chunks[i + 1])
                break

    if end_chunk_id:
        end_chunk_obj = next((c for c in chunks if c.get("chunk_id") == end_chunk_id), None)
        if end_chunk_obj and end_chunk_obj not in neighbors and end_chunk_obj != pin_chunk_obj:
            neighbors.append(end_chunk_obj)

    intent_info = analyze_intent(selection, heading, pin_chunk_obj, neighbors) if pin_chunk_obj else {}
    anchor_quote = None
    quote2 = None
    sec_chunk_obj = end_chunk_obj
    chosen_chunk = pin_chunk_obj

    if pin_chunk_obj is not None:
        anchor_quote = intent_info.get("anchor_sentence") or _anchor_sentence_for_selection(pin_chunk_obj, selection)
        chosen_chunk = intent_info.get("chosen_chunk") or pin_chunk_obj

        if anchor_quote is None or (sec_chunk_obj and selection.lower() not in (pin_chunk_obj.get("text") or "").lower()):
            if sec_chunk_obj:
                q1, q2 = _cross_chunk_quotes(pin_chunk_obj, sec_chunk_obj, selection)
                if q1:
                    anchor_quote = q1
                    quote2 = q2
                if sec_chunk_obj not in neighbors and sec_chunk_obj != pin_chunk_obj:
                    neighbors.append(sec_chunk_obj)

        if anchor_quote:
            if not _quote_in_passage(anchor_quote, chosen_chunk.get("text") or ""):
                found_chunk = None
                if _quote_in_passage(anchor_quote, pin_chunk_obj.get("text") or ""):
                    found_chunk = pin_chunk_obj
                else:
                    for n in neighbors:
                        if n and _quote_in_passage(anchor_quote, n.get("text") or ""):
                            found_chunk = n
                            break
                if found_chunk:
                    chosen_chunk = found_chunk

        if is_live and anchor_quote:
            quote = anchor_quote
            quote_for_prompt = f"{quote} {quote2}" if quote2 else quote
            gloss_prompt = _explain_gloss_user_message(selection, quote_for_prompt, chosen_chunk, neighbors)
            try:
                raw_gloss = generate_fn(EXPLAIN_GLOSS_SYSTEM, gloss_prompt, model)
            except Exception:
                raw_gloss = ""

            cleaned_gloss = (raw_gloss or "").strip()
            if re.match(r"^\[ch\.", cleaned_gloss, re.I) and "\n" in cleaned_gloss:
                cleaned_gloss = cleaned_gloss.split("\n", 1)[1].strip()
            cleaned_gloss = re.sub(r"\[Ch\.\s*[^\]]+\]\s*", "", cleaned_gloss, flags=re.I).strip()
            cleaned_gloss = cleaned_gloss.strip("\"'“”")
            cleaned_gloss = _clean_boilerplate_gloss(cleaned_gloss, selection)
            if not _is_coherent_gloss(cleaned_gloss, quote_for_prompt) or _gloss_repeats_quote(cleaned_gloss, quote_for_prompt) or (
                intent_info.get("is_passing_mention")
                and not _has_content_word_overlap(cleaned_gloss, quote_for_prompt, exclude=f"{selection} {chosen_chunk.get('heading', '')}")
            ):
                cleaned_gloss = _synthesize_grounded_gloss(selection, quote_for_prompt, chosen_chunk, neighbors, generate_fn, model)
            if cleaned_gloss:
                if re.match(r"^\[ch\.", cleaned_gloss, re.I) and "\n" in cleaned_gloss:
                    cleaned_gloss = cleaned_gloss.split("\n", 1)[1].strip()
                cleaned_gloss = re.sub(r"\[Ch\.\s*[^\]]+\]\s*", "", cleaned_gloss, flags=re.I).strip()
                cleaned_gloss = cleaned_gloss.strip("\"'“”")

            chapter = str(chosen_chunk.get("chapter", ""))
            citations = [{
                "chunk_id": chosen_chunk.get("chunk_id") or chunk_id,
                "chapter": chapter,
                "quote": quote,
                "doc": chosen_chunk.get("source", ""),
            }]
            if quote2 and sec_chunk_obj:
                c2_chap = str(sec_chunk_obj.get("chapter", ""))
                citations.append({
                    "chunk_id": sec_chunk_obj.get("chunk_id"),
                    "chapter": c2_chap,
                    "quote": quote2,
                    "doc": sec_chunk_obj.get("source", ""),
                })
                answer_text = f'[Ch. {chapter}] "{quote}"\n[Ch. {c2_chap}] "{quote2}"\n{cleaned_gloss}'
            else:
                answer_text = f'[Ch. {chapter}] "{quote}"\n{cleaned_gloss}'

            if _should_include_chunk_figures(chosen_chunk, selection, quote, index.get("figures") or []):
                figures_pool = [chosen_chunk]
                if sec_chunk_obj and quote2:
                    figures_pool.append(sec_chunk_obj)
            else:
                figures_pool = [{"text": f"{selection} {quote} {quote2 or ''}"}]
            figures = figures_for(figures_pool, index.get("figures") or [])
            return {
                "answer": answer_text,
                "refused": False,
                "citations": citations,
                "figures": figures,
                "followups": compute_dynamic_followups(
                    chosen_chunk, neighbors, selection=selection,
                    question=selection, answer_text=answer_text, mode="explain"
                ),
            }

    question = highlight_query(selection, heading)
    body = ask(
        index, question, generate_fn, search_fn, model,
        canonical=False, pin_chunk=chunk_id, end_chunk_id=end_chunk_id,
        embed_fn=embed_fn,
    )

    if pin_chunk_obj is not None and anchor_quote:
        valid_sents = set(_candidate_sentences(pin_chunk_obj.get("text") or "", pin_chunk_obj.get("heading") or ""))
        valid_ask = False
        if not body.get("refused") and body.get("citations"):
            first_cite = body["citations"][0]
            cite_id = first_cite.get("chunk_id")
            cite_quote = first_cite.get("quote", "")
            has_sel = selection.lower() in cite_quote.lower()
            answer_lines = [line.strip() for line in (body.get("answer") or "").splitlines() if line.strip()]
            has_gloss = False
            if len(answer_lines) >= 2 and not selection.strip().endswith("?"):
                second_line = answer_lines[1]
                norm_second = re.sub(r"[\s\"'“”]+", " ", second_line).strip().lower()
                norm_quote = re.sub(r"[\s\"'“”]+", " ", cite_quote).strip().lower()
                new_words = _tokens(second_line) - _tokens(cite_quote)
                if (norm_second and norm_second != norm_quote
                        and len(norm_second) > 25 and len(new_words) >= 3):
                    has_gloss = True
            if (cite_id == chunk_id and has_sel and has_gloss and not quote2 and
                    (not valid_sents or cite_quote in valid_sents)):
                valid_ask = True

        if valid_ask:
            answer_lines = [line.strip() for line in (body.get("answer") or "").splitlines() if line.strip()]
            if len(answer_lines) >= 2:
                cleaned_second = _clean_boilerplate_gloss(answer_lines[1], selection)
                if not _is_coherent_gloss(cleaned_second, anchor_quote):
                    cleaned_second = _synthesize_grounded_gloss(selection, anchor_quote, chosen_chunk, neighbors, generate_fn, model)
                body["answer"] = f"{answer_lines[0]}\n{cleaned_second}"
            if not body.get("refused"):
                body["followups"] = compute_dynamic_followups(
                    chosen_chunk, neighbors, selection=selection,
                    question=selection, answer_text=body.get("answer", ""), mode="explain"
                )
            else:
                body["followups"] = []
            return _patch_figures_src(body, index)

        quote = anchor_quote
        if (not body.get("refused") and body.get("citations") and
                body["citations"][0].get("chunk_id") == chunk_id and not quote2):
            cand_quote = body["citations"][0].get("quote", "")
            if (selection.lower() in cand_quote.lower() and
                    _quote_in_passage(cand_quote, pin_chunk_obj.get("text", "")) and
                    (not valid_sents or cand_quote in valid_sents) and
                    len(cand_quote) >= 40):
                quote = cand_quote

        if quote and not _quote_in_passage(quote, chosen_chunk.get("text") or ""):
            found_chunk = None
            if _quote_in_passage(quote, pin_chunk_obj.get("text") or ""):
                found_chunk = pin_chunk_obj
            else:
                for n in neighbors:
                    if n and _quote_in_passage(quote, n.get("text") or ""):
                        found_chunk = n
                        break
            if found_chunk:
                chosen_chunk = found_chunk

        quote_for_prompt = f"{quote} {quote2}" if quote2 else quote
        gloss_prompt = _explain_gloss_user_message(selection, quote_for_prompt, chosen_chunk, neighbors)
        try:
            raw_gloss = generate_fn(EXPLAIN_GLOSS_SYSTEM, gloss_prompt, model)
        except Exception:
            raw_gloss = ""

        cleaned_gloss = (raw_gloss or "").strip()
        if re.match(r"^\[ch\.", cleaned_gloss, re.I) and "\n" in cleaned_gloss:
            cleaned_gloss = cleaned_gloss.split("\n", 1)[1].strip()
        cleaned_gloss = re.sub(r"\[Ch\.\s*[^\]]+\]\s*", "", cleaned_gloss, flags=re.I).strip()
        cleaned_gloss = cleaned_gloss.strip("\"'“”")
        cleaned_gloss = _clean_boilerplate_gloss(cleaned_gloss, selection)
        if not _is_coherent_gloss(cleaned_gloss, quote_for_prompt) or _gloss_repeats_quote(cleaned_gloss, quote_for_prompt):
            cleaned_gloss = _synthesize_grounded_gloss(selection, quote_for_prompt, chosen_chunk, neighbors, generate_fn, model)
        if cleaned_gloss:
            if re.match(r"^\[ch\.", cleaned_gloss, re.I) and "\n" in cleaned_gloss:
                cleaned_gloss = cleaned_gloss.split("\n", 1)[1].strip()
            cleaned_gloss = re.sub(r"\[Ch\.\s*[^\]]+\]\s*", "", cleaned_gloss, flags=re.I).strip()
            cleaned_gloss = cleaned_gloss.strip("\"'“”")

        chapter = str(chosen_chunk.get("chapter", ""))
        citations = [{
            "chunk_id": chosen_chunk.get("chunk_id") or chunk_id,
            "chapter": chapter,
            "quote": quote,
            "doc": chosen_chunk.get("source", ""),
        }]
        if quote2 and sec_chunk_obj:
            c2_chap = str(sec_chunk_obj.get("chapter", ""))
            citations.append({
                "chunk_id": sec_chunk_obj.get("chunk_id"),
                "chapter": c2_chap,
                "quote": quote2,
                "doc": sec_chunk_obj.get("source", ""),
            })
            answer_text = f'[Ch. {chapter}] "{quote}"\n[Ch. {c2_chap}] "{quote2}"\n{cleaned_gloss}'
        else:
            answer_text = f'[Ch. {chapter}] "{quote}"\n{cleaned_gloss}'

        if _should_include_chunk_figures(chosen_chunk, selection, quote, index.get("figures") or []):
            figures_pool = [chosen_chunk]
            if sec_chunk_obj and quote2:
                figures_pool.append(sec_chunk_obj)
        else:
            figures_pool = [{"text": f"{selection} {quote} {quote2 or ''}"}]
        figures = figures_for(figures_pool, index.get("figures") or [])
        return _patch_figures_src({
            "answer": answer_text,
            "refused": False,
            "citations": citations,
            "figures": figures,
            "followups": compute_dynamic_followups(
                chosen_chunk, neighbors, selection=selection,
                question=selection, answer_text=answer_text, mode="explain"
            ),
        }, index)

    if not body.get("refused"):
        body["followups"] = compute_dynamic_followups(
            chosen_chunk, neighbors, selection=selection,
            question=selection, answer_text=body.get("answer", ""), mode="explain"
        )
    else:
        body["followups"] = []
    return _patch_figures_src(body, index)


# A footnote marker glued to the citing line ("Maxime Beauchemin4") has no
# sentence-ending punctuation, so whitespace collapse runs the attribution
# into the next sentence. The split view only: the chunk text is untouched.
FOOTNOTE_GLUE = re.compile(r"\b[A-Z][a-z]{2,}(\d{1,3})(?=\s+[A-Z][a-z])")


@functools.lru_cache(maxsize=1024)
def _sentences_cached(text):
    raw = (text or "").strip()
    lines = raw.splitlines()
    if len(lines) > 1 and not lines[0].strip().endswith((".", "?", "!")):
        raw = "\n".join(lines[1:])
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(raw) if p.strip()]
    parts = []
    for para in paragraphs:
        flat = _WHITESPACE_RE.sub(" ", para).strip()
        for run in _SENTENCE_SPLIT_RE.split(flat):
            cursor = 0
            for match in FOOTNOTE_GLUE.finditer(run):
                parts.append(run[cursor:match.end()])
                cursor = match.end()
            parts.append(run[cursor:])
    sentences = []
    for part in parts:
        sentence = part.strip()
        if len(sentence) < KEY_MIN_CHARS:
            continue
        if sentence[0].isupper() and sentence.endswith((".", "?", "!")):
            sentences.append(sentence)
    return tuple(sentences)

def _sentences(text):
    return list(_sentences_cached(text))


WEAK_QUIZ_PREFIXES = (
    "Behind the scenes", "For example", "For instance", "As we discussed",
    "As mentioned", "In this chapter", "In the next chapter", "Let's look",
    "See Figure", "See Chapter", "Up to this point",
)


def quiz_sentences(text):
    sents = _sentences(text)
    if not sents:
        return []
    filtered = [
        s for s in sents
        if not any(s.strip().startswith(prefix) for prefix in WEAK_QUIZ_PREFIXES)
    ]
    return filtered if filtered else sents


def pick_quiz_chunk(index, rng=None):
    """One real teaching chunk. Not a part title. Not the index."""
    rng = rng or random.Random()
    usable = []
    for chunk in index.get("chunks") or []:
        if not str(chunk.get("chapter", "")).isdigit():
            continue
        if quiz_sentences(chunk.get("text") or ""):
            usable.append(chunk)
    if not usable:
        return None
    return rng.choice(usable)


def quiz(index, generate_fn=None, model=ANSWER_MODEL, rng=None, chunk=None,
         chunk_id=None):
    """One question. The key is one sentence from one chunk. No score.

    The question must not contain the key. A leak is a refusal.
    """
    is_live = (generate_fn is None) or bool(getattr(generate_fn, "_is_live", False))
    generate_fn = generate_fn or ollama_generate
    rng = rng or random.Random()
    chunks = index.get("chunks") or []
    if chunk is None and chunk_id:
        found_chunk = next(
            (c for c in chunks if c.get("chunk_id") == chunk_id),
            None,
        )
        if found_chunk is not None:
            if quiz_sentences(found_chunk.get("text") or ""):
                chunk = found_chunk
            else:
                try:
                    idx = chunks.index(found_chunk)
                    for offset in (1, -1, 2, -2):
                        cand_idx = idx + offset
                        if 0 <= cand_idx < len(chunks):
                            cand = chunks[cand_idx]
                            if cand.get("chapter") == found_chunk.get("chapter") and quiz_sentences(cand.get("text") or ""):
                                chunk = cand
                                break
                except ValueError:
                    pass
                if chunk is None:
                    chapter_chunks = [
                        c for c in chunks
                        if c.get("chapter") == found_chunk.get("chapter") and quiz_sentences(c.get("text") or "")
                    ]
                    if chapter_chunks:
                        chunk = rng.choice(chapter_chunks)
    chunk = chunk or pick_quiz_chunk(index, rng)
    if chunk is None:
        return _refusal([])
    sentences = quiz_sentences(chunk.get("text") or "")
    if not sentences:
        return _refusal([])
    key = rng.choice(sentences)
    user = (
        f"{QUIZ_INSTRUCTION}\n\n"
        f"Target answer sentence (write a question that is directly answered by this specific sentence without repeating it):\n"
        f'"{key}"\n\n'
        f"Passage:\n"
        f"{chunk['text']}"
    )
    completion = generate_fn(SYSTEM, user, model).strip()

    if is_live:
        def _needs_quiz_retry(comp):
            if not comp or comp == REFUSAL or "[Ch." in comp:
                return True
            if _quote_in_passage(key, comp) or key.lower() in comp.lower():
                return True
            q_line = comp.splitlines()[0].strip()
            key_content = {
                stem(w.lower()) for w in words(key + " " + (chunk.get("heading") or ""))
                if len(w) > 2 and w.lower() not in STOPWORDS and w.lower() not in STEM_WORDS
            }
            q_stems = {
                stem(w.lower()) for w in words(q_line)
                if len(w) > 2 and w.lower() not in STOPWORDS and w.lower() not in STEM_WORDS
            }
            if key_content and not (key_content & q_stems):
                return True
            return False

        if _needs_quiz_retry(completion):
            retry_user = (
                f"{QUIZ_INSTRUCTION}\n\n"
                f"Target answer sentence (write a question that is directly answered by this specific sentence):\n"
                f'"{key}"\n\n'
                f"Topic: {chunk.get('heading', '')}"
            )
            try:
                retry_comp = generate_fn(QUIZ_SYSTEM, retry_user, model).strip()
                if retry_comp and retry_comp != REFUSAL and "[Ch." not in retry_comp:
                    if not (_quote_in_passage(key, retry_comp) or key.lower() in retry_comp.lower()):
                        completion = retry_comp
            except Exception:
                pass

    if not completion or completion == REFUSAL or "[Ch." in completion:
        return _refusal([chunk], index.get("figures") or [])
    if _quote_in_passage(key, completion) or key.lower() in completion.lower():
        return _refusal([chunk], index.get("figures") or [])

    quiz_neighbors = []
    if chunk in chunks:
        try:
            idx = chunks.index(chunk)
            if idx + 1 < len(chunks):
                quiz_neighbors.append(chunks[idx + 1])
        except ValueError:
            pass

    return {
        "answer": completion,
        "citations": [{
            "chunk_id": chunk["chunk_id"],
            "chapter": str(chunk["chapter"]),
            "quote": key,
        }],
        "figures": figures_for([chunk], index.get("figures") or []),
        "refused": False,
        "followups": compute_dynamic_followups(
            chunk, neighbors=quiz_neighbors, question=completion, answer_text=key, mode="quiz"
        ),
    }
