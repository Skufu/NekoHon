"""The system prompts. Phase 4 (ask) and the answer mode.

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
# The default is qwen2.5:7b: the bake-off winner granite4.1:3b failed the
# "what is MAD data landscape" phrasing probe (mad-phrasing-probe.md) and was
# reverted the same day. The env seam exists so a bake-off can run the same
# battery per candidate without editing this file.
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "qwen2.5:7b")
