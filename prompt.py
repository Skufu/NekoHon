"""The only system prompt. Phase 4.

The refusal sentence is exact, period included, and nothing else.
"""

import os

SYSTEM = """You answer only from the passages below. If the passages do not contain the answer, reply with exactly this sentence and nothing else:
Not in this book.
Quote first. Start the quote with [Ch. N] using the chapter on that passage. After the quote, one line of gloss in simple words. Definition first if the passage defines a term.
Do not use a passage from a different chapter to fill a gap. If more than one passage applies, list one quote per passage. Do not fuse them.
Do not describe an image. You cannot see images. If a passage names a figure, quote that passage. The app will show the image."""

REFUSAL = "Not in this book."
# The default is the bake-off winner (granite4.1:3b, swapped 2026-10-13). The
# env seam exists so a bake-off can run the same battery per candidate without
# editing this file.
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "granite4.1:3b")
