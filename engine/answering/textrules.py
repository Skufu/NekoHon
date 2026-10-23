import re


NON_WORD_OR_UNDERSCORE_RE = re.compile(r"[^\w\s]|_")


REGARDING_PREFIX_RE = re.compile(r"^(?:In\s+.+?,\s+)?[Rr]egarding\s+['\"]?([^:'\"]+)['\"]?\s*:\s*(.+)$")


TYPE_2_RE = re.compile(r"\btype[- ]2\b")


S3_RE = re.compile(r"\bs3\b")


IOPS_RE = re.compile(r"\biops\b")


SLA_SLO_RE = re.compile(r"\b(sla|slas|slo|slos)\b")


WHO_CREATED_RE = re.compile(r"\bwho\s+(?:created|invented|designed|developed|authored|introduced|wrote|founded|proposed)\b")


AUTHOR_NAME_RE = re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b")


PRONOUNS_SET = frozenset({"this", "it", "that", "they", "these", "those"})


ATTRIBUTION_MARKERS = ("noted", "groundbreaking", "book", "article", "creator", "created", "proposed", "introduced", "author", "by ")


MISS_QUOTE_CHARS = 160


FIGURE_REFERENCE = re.compile(r"\((?:figure|fig\.)\s*[A-Za-z]?\d+-\d+\)", re.I)


SPAN_MIN_CHARS = 40


MIN_QUOTE_CHARS = 20


PARAGRAPH_CAP = 1200


TAG_AND_QUOTE_RE = re.compile(r"\[Ch\.\s*([^\]]+)\]\s*[\"“](.+?)[\"”]")


WHICH_CHAPTER_RE = re.compile(r"\b(which\s+chapter|where\s+in\s+the\s+book)\b", re.I)


CHAPTER_NUM_RE = re.compile(r"\bchapter\s+\d+\b", re.I)


CHAPTER_DIGITS_RE = re.compile(r"\bchapter\s+(\d+)\b", re.I)


IN_GREATER_DETAIL_RE = re.compile(r"\bin greater detail\b", re.I)


OVERHEAD_RE = re.compile(r"\b(overhead|trade-offs|tradeoffs)\b", re.I)


OVERHEAD_EXPANDED_RE = re.compile(r"\b(overhead|trade-offs|tradeoffs|latency|throughput)\b", re.I)


YEAR_QUERY_RE = re.compile(r"\b(what\s+year|when\s+did|in\s+what\s+year)\b", re.I)


YEAR_MATCH_RE = re.compile(r"\b(19|20)\d{2}\b")


TRAP_QUERY_RE = re.compile(r"\b(how\s+much|charge|price|cost\s+per\s+hour|what\s+year|when\s+did|in\s+what\s+year|terraform|script|code|install|download)\b", re.I)


PRICE_QUERY_RE = re.compile(r"\b(how\s+much|cost\s+per\s+hour|charge|price)\b", re.I)


PRICE_MATCH_RE = re.compile(r"(\$|\b(dollar|dollars|cents|cost|charge|price|per\s+hour)\b)", re.I)


CODE_QUERY_RE = re.compile(r"\b(terraform|script|code)\b", re.I)


CODE_MATCH_RE = re.compile(r"\b(terraform|resource|provider|hcl|script|def |class |function)\b", re.I)


TOPIC_SHIFT_CONCEPT_RE = re.compile(r"^(?:what\s+(?:is|are|was|were)\s+(?:a\s+|an\s+|the\s+)?(?!(?:role|main|key|specific|purpose|point|goal|problem|catch|drawback|advantage|disadvantage|trade-off|difference|reason|stage|step|type|example|takeaway)\b)|define\s+|tell\s+me\s+about\s+)(.+?)\??$", re.I)
