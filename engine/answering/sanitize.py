import re



HISTORY_TURNS = 2
HISTORY_QUESTION_CHARS = 200
HISTORY_ANSWER_CHARS = 400


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
