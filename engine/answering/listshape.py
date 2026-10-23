import re

from engine.answering.shared import (
    PARAGRAPH_CAP,
    SPAN_MIN_CHARS,
    _fold,
    _heading_prefix_pattern,
    _token_word_pattern,
    _words_pattern,
)


def _paragraph_around(quote, passage_text):
    folded = _fold(quote)
    if not folded:
        return ""
    for paragraph in re.split(r"\n\s*\n", passage_text or ""):
        if folded in _fold(paragraph):
            return re.sub(r"\s+", " ", paragraph).strip()
    return ""


def _plural(word):
    if len(word) < 4 or word.endswith(("ss", "us", "is", "ous")):
        return False
    if word.endswith("ies"):
        return True
    if word.endswith(("ches", "shes", "xes", "zes", "ses")):
        return True
    return word.endswith("s")


def _whole_paragraph(anchors, paragraph, quote):
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


LIST_ASK = re.compile(
    r"\b(?:what are|which are|what were|list the)\b"
    r"|\b(?:factors|parts|kinds|types|steps|stages)\b"
    r"(?:\W+\w+){0,6}\W+(?:of|to)\b",
    re.I,
)


def _list_ask(question, asked_form):
    for text in (question, asked_form):
        if text and LIST_ASK.search(text):
            return True
    return False


def _is_lead_in(quote):
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
    if not lead or lead not in answer:
        return answer
    return answer.replace(lead, continuation, 1)


def _expand_list(body, question, asked_form, passages):
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


def _without_heading(quote, passage):
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


def _synthesize_list_answer(question: str, quote: str, chunk_obj: dict) -> str:
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
