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
