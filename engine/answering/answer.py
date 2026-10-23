"""Answers from retrieved passages: the ask and answer modes.

ask: the model quotes, the quote is checked; a failed check is a refusal.
answer: the model answers from the passages in the same quote-first shape
(SYSTEM + user_message — the exact prompts the student is trained on); its
[Ch. n] tags become citations, quotation marks the passages cannot back are
stripped, and the quote check demotes from gate to meter
(artifacts/harnesses/groundedness.py). An uncited answer gets one `[Ch. `
prefill retry, kept only when a citation validates (`_retry_uncited`).

Prompt alignment (2026-10-15): answer mode used to send SYSTEM_ANSWER ("a few
sentences ... in your own words"). The training data has always been
ask-shaped (quote-first); x2d masked the mismatch by over-memorizing
(loss 0.006), while x2e followed the served prompt, paraphrased, and failed
the verbatim check (40/160 vs 111/160, probe-fragment evidence). The default
path now serves what the model was trained on.
"""


from engine.answering.comparison import _comparison_sides
from engine.answering.context import _pin_chunk, _should_include_chunk_figures, retrieval_context
from engine.answering.conversation import (
    _advance_followup_quote,
    _extract_subject_from_history,
    _resolve_contextual_query,
)
from engine.answering.explain import explain, highlight_query
from engine.answering.freeanswer import (
    PARAPHRASE_LIMIT,
    QUOTE_PATTERN,
    SIMPLE_CUES,
    TAG_PATTERN,
    _best_passage,
    _clean_rewrite,
    _evidence_quote,
    _plain_body,
    _sentence_claims,
    parse_answered,
    respond,
    simple_words,
)
from engine.answering.generate import ollama_generate, ollama_generate_stream
from engine.answering.gloss import _ensure_answer_gloss, _has_content_word_overlap, _is_coherent_gloss
from engine.answering.listshape import _after_lead_in, _plural, _synthesize_list_answer
from engine.answering.messages import answer_user_message, passages_block, user_message
from engine.answering.prompt import ANSWER_MODEL, PARAPHRASE_SYSTEM, REFUSAL
from engine.answering.quiz import quiz, quiz_sentences
from engine.answering.quoteask import ask
from engine.answering.quotecheck import (
    _complete_truncated_quote,
    _punctuation_plain,
    _quote_in_passage,
    parse_completion,
)
from engine.retrieval.keywords import anchor_words
from engine.answering.sanitize import is_prompt_injection, sanitize_history, sanitize_query
from engine.answering.shared import (
    _candidate_sentences,
    _clean_boilerplate_gloss,
    _clean_selection_text,
    _extract_query_entities,
    fix_acronym_casing,
)
