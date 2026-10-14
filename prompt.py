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

REFUSAL = "Not in this book."

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
# The default is qwen2.5:7b: the bake-off winner granite4.1:3b failed the
# "what is MAD data landscape" phrasing probe (mad-phrasing-probe.md) and was
# reverted the same day. The env seam exists so a bake-off can run the same
# battery per candidate without editing this file.
# reverted the same day. The env seam exists so a bake-off can run the same
# battery per candidate without editing this file.
# 2026-10-14: `smallbook_x2d` (1.9 GB q4) is the default — best small-model
# battery recorded (20/21 x3), both ETL pin targets fixed, 0 suite loops, and
# the pre-retry gate's suite gap (bare-topic/order-flip) is documented in
# artifacts/reports/retry-safety-net-2026-10-14.md (user decision: adopt
# anyway). `smallbook_x2` and the teacher stay on disk.
# Revert without editing: set ANSWER_MODEL=qwen2.5:7b (or =smallbook_x2).
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "smallbook_x2d")
