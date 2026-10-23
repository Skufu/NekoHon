import re


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
    "crud": "CRUD", "acid": "ACID", "base": None,
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
    if not text:
        return text

    def _sub(m):
        raw = m.group(0).lower()
        return _CANONICAL_ACRONYM_MAP.get(raw, m.group(0))

    return _ACRONYM_PATTERN.sub(_sub, text)


def clean_boilerplate_gloss(gloss, selection=""):
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
