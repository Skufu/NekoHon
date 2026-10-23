import functools
import re

from engine.retrieval.preprocess import stem as _pre_stem, tokens as _pre_tokens, words as _pre_words
from engine.answering.intent import META_TRANSITION_RE, extract_core_concept, select_substantive_anchor_sentence
from engine.retrieval.preprocess import STOPWORDS


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

stem = _pre_stem

_WHITESPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")


_TERMINAL_PUNCT_RE = re.compile(r'[.!?]["\'”’]?$')
_CHAPTER_PREFIX_RE = re.compile(r"^Chapter\s+\d+\b", re.I)


_NON_WORD_OR_UNDERSCORE_RE = re.compile(r"[^\w\s]|_")
_REGARDING_PREFIX_RE = re.compile(r"^(?:In\s+.+?,\s+)?[Rr]egarding\s+['\"]?([^:'\"]+)['\"]?\s*:\s*(.+)$")

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


_TYPE_2_RE = re.compile(r"\btype[- ]2\b")
_S3_RE = re.compile(r"\bs3\b")
_IOPS_RE = re.compile(r"\biops\b")
_SLA_SLO_RE = re.compile(r"\b(sla|slas|slo|slos)\b")
_WHO_CREATED_RE = re.compile(r"\bwho\s+(?:created|invented|designed|developed|authored|introduced|wrote|founded|proposed)\b")
_AUTHOR_NAME_RE = re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b")


_PRONOUNS_SET = frozenset({"this", "it", "that", "they", "these", "those"})


_ATTRIBUTION_MARKERS = ("noted", "groundbreaking", "book", "article", "creator", "created", "proposed", "introduced", "author", "by ")

@functools.lru_cache(maxsize=1024)
def _token_word_pattern(token):
    return re.compile(rf"\b{re.escape(token)}\b")


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


MISS_QUOTE_CHARS = 160
FIGURE_REFERENCE = re.compile(r"\((?:figure|fig\.)\s*[A-Za-z]?\d+-\d+\)", re.I)


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


@functools.lru_cache(maxsize=2048)
def _fold(text):
    return _WHITESPACE_RE.sub(" ", text or "").lower()


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


_TAG_AND_QUOTE_RE = re.compile(r"\[Ch\.\s*([^\]]+)\]\s*[\"“](.+?)[\"”]")


_INDEX_MAPS = {}


def _index_maps(index):
    chunks = index.get("chunks") or []
    entry = _INDEX_MAPS.get(id(index))
    if entry is not None and entry[0] is index and entry[1] is chunks and entry[2] == len(chunks):
        return entry[3], entry[4], entry[5]
    by_id = {}
    pos = {}
    by_chapter = {}
    for i, c in enumerate(chunks):
        cid = c.get("chunk_id")
        by_id.setdefault(cid, c)
        pos.setdefault(cid, i)
        by_chapter.setdefault(str(c.get("chapter")), []).append(c)
    if len(_INDEX_MAPS) >= 8:
        _INDEX_MAPS.clear()
    _INDEX_MAPS[id(index)] = (index, chunks, len(chunks), by_id, pos, by_chapter)
    return by_id, pos, by_chapter


def chunk_by_id(index, chunk_id, default=None):
    try:
        return _index_maps(index)[0].get(chunk_id, default)
    except TypeError:
        return default


def chunk_position(index, chunk_id):
    try:
        return _index_maps(index)[1].get(chunk_id)
    except TypeError:
        return None


def chapter_neighbors(index, chapter, lead_chunk_id, limit=4):
    pool = _index_maps(index)[2].get(chapter, ())
    return [c for c in pool if c.get("chunk_id") != lead_chunk_id][:limit]


_WHICH_CHAPTER_RE = re.compile(r"\b(which\s+chapter|where\s+in\s+the\s+book)\b", re.I)


_CHAPTER_NUM_RE = re.compile(r"\bchapter\s+\d+\b", re.I)


_CHAPTER_DIGITS_RE = re.compile(r"\bchapter\s+(\d+)\b", re.I)


_IN_GREATER_DETAIL_RE = re.compile(r"\bin greater detail\b", re.I)


_OVERHEAD_RE = re.compile(r"\b(overhead|trade-offs|tradeoffs)\b", re.I)


_OVERHEAD_EXPANDED_RE = re.compile(r"\b(overhead|trade-offs|tradeoffs|latency|throughput)\b", re.I)


_YEAR_QUERY_RE = re.compile(r"\b(what\s+year|when\s+did|in\s+what\s+year)\b", re.I)


_YEAR_MATCH_RE = re.compile(r"\b(19|20)\d{2}\b")


_TRAP_QUERY_RE = re.compile(r"\b(how\s+much|charge|price|cost\s+per\s+hour|what\s+year|when\s+did|in\s+what\s+year|terraform|script|code|install|download)\b", re.I)


_PRICE_QUERY_RE = re.compile(r"\b(how\s+much|cost\s+per\s+hour|charge|price)\b", re.I)


_PRICE_MATCH_RE = re.compile(r"(\$|\b(dollar|dollars|cents|cost|charge|price|per\s+hour)\b)", re.I)


_CODE_QUERY_RE = re.compile(r"\b(terraform|script|code)\b", re.I)


_CODE_MATCH_RE = re.compile(r"\b(terraform|resource|provider|hcl|script|def |class |function)\b", re.I)


_WORD_RE = re.compile(r"\w+")


_TOPIC_SHIFT_CONCEPT_RE = re.compile(r"^(?:what\s+(?:is|are|was|were)\s+(?:a\s+|an\s+|the\s+)?(?!(?:role|main|key|specific|purpose|point|goal|problem|catch|drawback|advantage|disadvantage|trade-off|difference|reason|stage|step|type|example|takeaway)\b)|define\s+|tell\s+me\s+about\s+)(.+?)\??$", re.I)


_ENTITY_PHRASE_RE = re.compile(r"\b([A-Z][a-zA-Z0-9]*(?:[- ](?:[A-Z0-9][a-zA-Z0-9]*|\d+(?:\.\d+)*))+)\b")


_ACRONYM_MATCH_RE = re.compile(r"\b([A-Z]{2,10}s?)\b")


_STRIP_PUNCT_RE = re.compile(r"^[^\w]+|[^\w]+$")


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


@functools.lru_cache(maxsize=512)
def _selection_word_pattern(sel):
    return re.compile(rf"\b{re.escape(sel)}\b", re.IGNORECASE)


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


def _clean_selection_text(sel: str) -> str:
    raw = (sel or "").strip()
    if not raw:
        return ""
    if "\n" in raw:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(lines) >= 2 and len(lines[0]) <= 40 and lines[0].endswith(":"):
            raw = " ".join(lines[1:])
    return re.sub(r"\s+", " ", raw).strip()


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
