import re

from engine.answering.intent import (
    INTENT_AUTHOR_QUESTION,
    INTENT_CONCEPT_TERM,
    INTENT_MULTI_SENTENCE,
    INTENT_VAGUE_FRAGMENT,
    analyze_intent,
    classify_intent,
    extract_core_concept,
    extract_enclosing_subject,
)
from engine.answering.sanitize import sanitize_history
from engine.answering.listshape import _list_ask


FORMAT_REMINDER = (
    "Copy one sentence from a passage. Do not reword it.\n"
    "Format example, not an answer:\n"
    "[Ch. 2] \"exact sentence copied from a passage\"\n"
    "One short line in simple words."
)


ANSWER_REMINDER = (
    "Answer the question directly, in your own words. Cite each claim with "
    "[Ch. N] using the chapter of the passage it came from."
)


def passages_block(passages):
    blocks = []
    for hit in passages:
        blocks.append(
            f"[Ch. {hit['chapter']}] chunk_id={hit['chunk_id']}\n{hit['text']}"
        )
    return "\n\n".join(blocks)


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
