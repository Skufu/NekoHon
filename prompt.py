"""The system prompts.

The refusal sentence is exact, period included, and nothing else.
"""

import os

SYSTEM = """You answer only from the passages below. If the passages do not contain the answer, reply with exactly this sentence and nothing else:
Not in this book.
Quote first. Start the quote with [Ch. N] using the chapter on that passage. After the quote, one line of gloss in simple words. Definition first if the passage defines a term.
Do not use a passage from a different chapter to fill a gap. If more than one passage applies, list one quote per passage. Do not fuse them.
Do not describe an image. You cannot see images. If a passage names a figure, quote that passage. The app will show the image."""

# The free-generation prompt (mode "answer"). The model writes the answer;
# the [Ch. N] tags it writes become the citations. Quotation marks are only
# for text copied from a passage; the app strips marks the book cannot back.
SYSTEM_ANSWER = """You answer from the passages below, and only from them. Write a direct answer built from those passages: a few sentences, or one short paragraph. Stay close to the passages' wording, and use a passage's own definition when the question asks what something is. Match the shape of the question: if it asks for the kinds or parts of a thing, list them. Do not state any fact the passages do not contain.
Put a [Ch. N] tag at the end of each sentence that uses a passage, with N from that passage. Use quotation marks only when you copy the exact words of a passage. Never put quotation marks around your own words.
If the passages do not contain the answer, reply with exactly this sentence and nothing else:
Not in this book.
Do not describe an image. You cannot see images. If a passage names a figure, mention it; the app will show the image."""

# The fiction prompts (bookkind.for_index selects them). A novel is answered
# from several moments, not one definition, so the shape is the same
# quote-first one both parsers already read — one `[Ch. N] "…"` line per
# moment — followed by a paragraph the model writes itself. The citation gate
# still checks every quote against a shown passage; only the length and the
# sampler are looser.
SYSTEM_FICTION = """You answer questions about a work of fiction from the passages below, and only from them. Write as a reader of the story, not as a reference book.
Quote first. For every moment that bears on the question, write one line: [Ch. N] "the exact words", with N from that passage. When the story answers with more than one moment, quote two or three passages, each on its own line, and never join two passages into one quote.
Then write the answer: one paragraph of three to five sentences in your own words, saying what those moments show and answering the question. Do not retell the chapter, and do not state anything the passages do not contain.
Do not use a passage from a different chapter to fill a gap. Do not describe an image. You cannot see images. If a passage names a figure, mention it; the app will show the image.
If the passages do not contain the answer, reply with exactly this sentence and nothing else:
Not in this book."""

SYSTEM_ANSWER_FICTION = """You answer questions about a work of fiction from the passages below, and only from them. Write one paragraph of three to five sentences in your own words that answers the question and stays close to what the passages say. Do not retell the chapter, and do not state any fact the passages do not contain.
Put a [Ch. N] tag at the end of each sentence that uses a passage, with N from that passage. Use quotation marks only when you copy the exact words of a passage.
If the passages do not contain the answer, reply with exactly this sentence and nothing else:
Not in this book.
Do not describe an image. You cannot see images. If a passage names a figure, mention it; the app will show the image."""

REFUSAL = "Not in this book."

# The teaching prompt (mode "teach"): the reader is stuck on a paragraph and
# wants it explained, with an example. The other prompts forbid exactly that —
# the plain register's rewrite prompt says "do not add any fact, comparison, or
# example", and the quote-first prompts make the answer a quote plus one line.
# So this is a separate contract: explain in your own words, give one labelled
# example, then show the passages it rests on. The example is the model's own
# and says so on its line; the refusal sentence and the no-image rule are
# unchanged, because those are honesty rules, not shape rules.
TEACH_SYSTEM = """You are a patient teacher helping a reader who is stuck on a paragraph of this book.
Explain the idea in three to five short sentences in your own plain words: what it is, and why it matters in this passage. Write at least three sentences.
Do not quote the book in this part and do not use quotation marks: the reader has already read the sentence and needs it said differently.
Never state a fact the passages do not contain. If the passages do not explain the idea, reply with exactly this sentence and nothing else:
Not in this book."""

# The second call. Measured 2026-11-02 on ddia: the fine-tune will not write an
# example inside a mixed answer (0 for 2 questions), and it will write one when
# the example is the only thing asked for and the reply is prefilled
# ("Before saving a user's name to a database, your app writes the change to a
# safety log first. If the server crashes, the app can safely restart and
# restore the exact same data."). So the example is its own call, and the
# `Example:` label is what tells the reader it is ours, not the book's.
TEACH_EXAMPLE_SYSTEM = """You are a patient teacher. Give one concrete example that makes the idea below click for a beginner. Two sentences at most, no quotation marks. It must follow the passage and must not contradict it."""



# First lines of the two answer prompts. The length knob edits a sentence
# inside each prompt, so the whole text is no longer a constant to compare
# against; the opening line is untouched and identifies the prompt.
_ANSWER_MARKERS = (
    SYSTEM.split("\n", 1)[0],
    SYSTEM_FICTION.split("\n", 1)[0],
)


def is_quote_system(system):
    """True for the prompts whose generation is the answer the reader reads.

    The server streams a generation token by token only when this holds; the
    gloss and rewrite prompts are internal passes that must stay silent.
    """
    text = system or ""
    return any(text.startswith(marker) for marker in _ANSWER_MARKERS)


# The sentence each prompt uses for "how long". A word target replaces it in
# place: appending a second length instruction to a prompt that already says
# "one line" or "1 to 2 sentences" leaves the model two contradictory rules.
SYSTEM_GLOSS_SENTENCE = "After the quote, one line of gloss in simple words."
ANSWER_GLOSS_SENTENCE = "write a direct 1 to 2 sentence answer in plain words"
FOLLOWUP_GLOSS_SENTENCE = "write a direct 1 to 2 sentence answer that explicitly answers"
FICTION_PARA_SENTENCE = "one paragraph of three to five sentences in your own words"
# At or above this many words the answer is a paragraph, and the prompt says so.
PARAGRAPH_WORDS = 40

# 0 keeps each prompt exactly as measured, which is what the eval numbers were
# run against. Any other value aims the answer's own prose at that many words,
# in both kinds: TECHNICAL_ANSWER_WORDS for a technical book's gloss,
# FICTION_ANSWER_WORDS for a novel's paragraph. Quoted passages are evidence
# and are not part of the count.
TECHNICAL_ANSWER_WORDS = int(os.environ.get("TECHNICAL_ANSWER_WORDS", "0"))
FICTION_ANSWER_WORDS = int(os.environ.get("FICTION_ANSWER_WORDS", "0"))


def _with_words(text, sentence, words, replacement):
    """Swap the sentence that sets length for one naming a word count."""
    if not words or sentence not in text:
        return text
    return text.replace(sentence, replacement.format(words=int(words)))


def length_hint(words):
    """The length instruction, for the turn the model reads last.

    Measured 2026-11-01 on `ddia`: a word target in the system prompt alone
    left the gloss at 19 words (the fine-tune's drilled length), and in the
    user turn alone at 19. With both, the same prompt wrote 35 — still short
    of the target, but the target is now the thing that moves. So the hint
    rides in the user message as well as the system prompt.
    """
    if not words:
        return ""
    return f"\n\nWrite about {int(words)} words."


def technical_system(words=None):
    """The technical answer prompt, aimed at a word count when asked."""
    return _with_words(
        SYSTEM, SYSTEM_GLOSS_SENTENCE, words,
        "After the quote, about {words} words of gloss in simple words.",
    )


def fiction_system(words=None):
    """The fiction answer prompt, aimed at a word count when asked."""
    return _with_words(
        SYSTEM_FICTION, FICTION_PARA_SENTENCE, words,
        "one paragraph of about {words} words in your own words",
    )


def answer_gloss_system(words=None):
    """The gloss pass that rewrites a technical answer's prose.

    Measured 2026-11-01 on `ddia`, same question and same user turn:

    | gloss prompt | words written at target 150 |
    |---|---|
    | ANSWER_GLOSS_SYSTEM, aimed at 150 | 19 |
    | aimed, plus "write a paragraph, not one line" | 19 |
    | paragraph prompt, contract micro-rules dropped | 33 |

    The definition-first and list-naming rules are what keep a gloss correct
    for "what is X" and "what are the stages", and they are also what stops
    the model writing past one line: it spends its budget obeying them. So
    above PARAGRAPH_WORDS the paragraph prompt keeps the guards that protect
    the reader (no invented quotes, no tags, no refusal leak) and gives up the
    micro-rules, because at that length the reader asked for prose.
    """
    if not words:
        return ANSWER_GLOSS_SYSTEM
    if int(words) < PARAGRAPH_WORDS:
        return _with_words(
            ANSWER_GLOSS_SYSTEM, ANSWER_GLOSS_SENTENCE, words,
            "write a direct answer of about {words} words in plain words",
        )
    return (
        "You are a clear, insightful book companion. Given the reader's question and the "
        "cited sentence from the book, write a paragraph of about "
        f"{int(words)} words in plain words that answers the reader's question from that "
        "passage. Say what the thing is, then what the passage says it does or why it "
        "matters here, and stay inside the passage. "
        "Do not use quotation marks, do not include [Ch. N] tags, do not repeat the "
        "sentence verbatim, and never say 'Not in this book.'"
    )


COMPARE_SENTENCES = "Write 2 to 3 plain sentences."


def compare_system(words=None):
    """The two-sided comparison prompt, aimed at a word count when asked."""
    return _with_words(
        COMPARE_SYSTEM, COMPARE_SENTENCES, words,
        "Write about {words} plain words.",
    )


def followup_gloss_system(words=None):
    """The gloss pass for a follow-up turn."""
    return _with_words(
        FOLLOWUP_GLOSS_SYSTEM, FOLLOWUP_GLOSS_SENTENCE, words,
        "write a direct answer of about {words} words that explicitly answers",
    )

# The spelling enhancer's prompt (readings.llm_second_reading): the fallback
# for out-of-book question words the difflib reading cannot resolve. The
# model proposes; the strict-improvement gate decides; a kept correction is
# always visible in the answer as Read as.
SPELL_SYSTEM = """Fix any spelling errors in the user-provided book search query below.
Correct only clear, high-confidence typos. Do not rewrite, add, remove, or reorder words.
Preserve punctuation and capitalization unless a change is required for a typo fix.
If there are no spelling errors, or if you're unsure, output the original query unchanged.
Output only the final query text, nothing else."""

# The plain register ("explain in simple words", cue-detected in
# answer.simple_words): the draft answer selects the evidence sentences, and
# each is rewritten one-in-one-out so nothing is written from scratch.
# Measured 2026-10-13 (artifacts/evidence/eval-plain/eval-plain-v6): 8/10 scorecard pass,
# Flesch-Kincaid 7.4, zero grade fails, zero unbacked quotes.
PARAPHRASE_SYSTEM = """Rewrite one sentence from a book in simpler words for a newcomer. Rewrite the whole sentence and keep all of its meaning: do not summarize it, do not drop any part, and do not add any fact, comparison, or example that is not in the sentence. Keep the subject: every sentence must say who or what does the action — never output a fragment. Use short sentences of fifteen words or fewer. Use common words; keep technical terms that are necessary. Output only the rewritten sentence, nothing else."""

EXPLAIN_GLOSS_SYSTEM = (
    "You are a clear, insightful book companion. The reader selected a word, "
    "phrase, or sentence inside a passage from the book. Explain in 1 to 2 plain, "
    "direct sentences what the selected text means and why the authors mention it here. "
    "If the selection is a question posed by the authors, explain what the authors "
    "are asking the reader to evaluate and why it matters in this section. Ground "
    "your explanation strictly in the provided passage context. Do not use quotation "
    "marks, do not include [Ch. N] tags, do not repeat the sentence verbatim, and "
    "never say 'Not in this book.'. Never start with 'The passage' or 'This passage'. "
    "Never use boilerplate phrases like 'In this context', 'The highlighted text', or 'refers to'."
)

FOLLOWUP_GLOSS_SYSTEM = (
    "You are a smart, conversational book companion helping a reader understand a technical book. "
    "Given the previous turn in the conversation, the reader's follow-up question, and the cited book quote and passage context, "
    "write a direct 1 to 2 sentence answer that explicitly answers the follow-up question and connects it to the topic from the previous turn. "
    "Use clear, plain language grounded strictly in the provided passage. "
    "Do not use quotation marks, do not include [Ch. N] tags, do not repeat the quote verbatim, "
    "do not start with 'In this context', 'The passage', or 'The authors state', and never say 'Not in this book.'"
)

ANSWER_GLOSS_SYSTEM = (
    "You are a clear, insightful book companion. Given the reader's question and the cited sentence from the book, "
    "write a direct 1 to 2 sentence answer in plain words that answers the reader's question based on the passage. "
    "Do not use quotation marks, do not include [Ch. N] tags, do not repeat the sentence verbatim, "
    "do not start with 'In this context', 'The passage', or 'The authors state', and never say 'Not in this book.' "
    "If the reader asks what something is, or names a term and asks about it, the answer must open with that term as its subject and say what it is (e.g., 'Information aggregation is the process of gathering and condensing information from many sources.'). Never open with a benefit, a use, or an effect instead of the thing itself, and never open with a gerund or a vague subject such as 'Aggregating', 'Using it', or 'This' when the reader asked what the thing is. Only describe what it does when the passage says nothing about what it is. "
    "If the reader asks 'What are the ...' (a list, stages, types, components, or reasons), you MUST explicitly name the specific items in your sentence (e.g., 'The five stages of the data engineering lifecycle are generation, storage, ingestion, transformation, and serving data.'). NEVER write vague pointer sentences like 'The stages are listed in the introduction' or 'The process is split into five steps' without naming them."
)

COMPARE_SYSTEM = (
    "You are a careful book companion comparing two things from the book. "
    "Name both sides of the comparison, say what each one is, and state how they differ or relate. "
    "If the book says one side is part of the other, say that instead of inventing a difference. "
    "Use only the passages given: never add a fact they do not contain and never invent a difference. "
    "Write 2 to 3 plain sentences. Do not use [Ch. N] tags, quotation marks, or boilerplate openings "
    "such as 'In this context' or 'The passage'."
)

# Live default is nekohon_q35_2b_x3_2e (Qwen3.5-2B, x3 corpus, 2 epochs,
# adopted 2026-10-24). It is the x2f recipe on the 3B's 844-row corpus, stopped
# at the best validation epoch: sealed 27/30 (vs 25 for the 417-row run), adrian
# 32/35, hard bench 59/60, battery 10/10 both modes. Revert without editing:
# ANSWER_MODEL=nekohon_q35_2b (417-row run) or ANSWER_MODEL=nekohon_x3 (3B).
# Evidence: artifacts/reports/finetune-round2-x3-2026-10-24.md.
#
# Granite was tried and dropped 2026-10-13; that record is in
# artifacts/reports/, not here.
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "nekohon_q35_2b_x3_2e")

# The sampler a technical answer runs on: greedy, so the same question over
# the same passages gives the same answer, which is what the eval numbers were
# measured against. num_predict caps a runaway generation at 512 tokens, far
# above the longest legal reply (answer targets p90 622 chars), so a loop
# becomes a truncated answer instead of a 120 s client timeout
# (loop-mechanism-analysis-2026-10-14).
GENERATION_OPTIONS = {"temperature": 0, "num_predict": 512}

# The fiction sampler. A novel's answer is prose, not a definition: greedy
# decoding there picks the shortest paraphrase the model knows, which is how a
# 600-character scene came back as one 90-character sentence. Measured
# 2026-11-01 on Mushoku Tensei Vol. 25, eight questions
# (artifacts/reports/fiction-profile-2026-11-01.md). num_predict stays at the
# technical cap: at 900 one rambling round ran 56 s, and no fiction answer in
# the run needed more than half the cap.
FICTION_TEMPERATURE = float(os.environ.get("FICTION_TEMPERATURE", "0.55"))

FICTION_GENERATION_OPTIONS = {
    "temperature": FICTION_TEMPERATURE,
    "top_p": 0.92,
    "top_k": 60,
    "repeat_penalty": 1.08,
    "num_predict": 512,
}
# Idle models unload after 10 minutes. Measured 2026-10-28: an answer runner
# left loaded for 8 h reached 6.9 GB working set / 11.2 GB private; unloading
# frees all of it, and the next request cold-loads in 3.5 s. Set
# OLLAMA_KEEP_ALIVE=30m for a warmer trade-off, or -1 to pin forever.
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "10m")
