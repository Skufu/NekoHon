
from engine.answering.canonical import canonical_query
from engine.answering.comparison import half_covered
from engine.answering.context import retrieval_context
from engine.answering.conversation import resolve_contextual_query
from engine.answering.answermode import has_passage_evidence, retry_uncited, simple_words
from engine.answering.messages import user_message
from engine.answering.pipeline import begin_turn, finalize, simplify_shortcut
from engine.answering.prompt import ANSWER_MODEL, SYSTEM
from engine.answering.quotecheck import (
    align_citation_to_query_concepts,
    refusal_response,
    parse_completion,
)
from engine.answering.textrules import TRAP_QUERY_RE
from engine.retrieval.keywords import anchor_words


def ask(index, question, generate_fn=None, search_fn=None, model=ANSWER_MODEL,
        canonical=True, history=None, pin_chunk=None, selection="", heading="",
        end_chunk_id=None, embed_fn=None):
    t = begin_turn(index, question, generate_fn, history, pin_chunk, selection, heading, model, "ask")
    if t is None:
        return refusal_response([])
    shortcut = simplify_shortcut(t)
    if shortcut is not None:
        return shortcut
    question, history, clean_history = t.question, t.history, t.clean_history
    generate_fn, effective_pin = t.generate_fn, t.effective_pin
    resolved_question = resolve_contextual_query(
        index, question, pin_chunk=effective_pin, selection=selection,
        heading=heading, history=history,
    )
    asked_form = canonical_query(resolved_question) if canonical else resolved_question
    context = retrieval_context(
        index, asked_form, search_fn, generate_fn, pin_chunk=effective_pin,
        end_chunk_id=end_chunk_id, history=history, selection=selection,
        embed_fn=embed_fn,
    )
    passages = context["passages"]
    t.set_retrieval(resolved_question, asked_form, context)
    if not passages:
        return refusal_response([])
    completion = generate_fn(
        SYSTEM, user_message(context["asked"], passages, history=history), model
    )
    anchors = anchor_words(asked_form, context["word_map"])
    figures = index.get("figures") or []
    body = parse_completion(completion, passages, figures, anchors, question=resolved_question)
    body = half_covered(body, resolved_question, asked_form, passages, figures)
    body = align_citation_to_query_concepts(body, resolved_question, passages)
    if body.get("refused") and has_passage_evidence(asked_form, passages, context["word_map"]):
        retry = retry_uncited(
            context["asked"], passages, figures, generate_fn, model,
            history=history, anchors=anchors, word_map=context["word_map"],
        )
        if retry is not None and not retry.get("refused"):
            body = retry
            body = align_citation_to_query_concepts(body, resolved_question, passages)
    elif body.get("refused") and clean_history and (resolved_question != question):
        is_trap = bool(TRAP_QUERY_RE.search(question))
        if not is_trap and passages:
            retry = retry_uncited(
                context["asked"], passages, figures, generate_fn, model,
                history=history, anchors=anchors, word_map=context["word_map"],
            )
            if retry is not None and not retry.get("refused"):
                body = retry
                body = align_citation_to_query_concepts(body, resolved_question, passages)
    return finalize(t, body, simple_words(asked_form))
