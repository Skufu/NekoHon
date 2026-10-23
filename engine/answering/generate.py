from engine import llm
from engine.answering.prompt import ANSWER_MODEL


OLLAMA_CHAT = llm.CHAT_URL


def ollama_generate(system, user, model=ANSWER_MODEL, url=OLLAMA_CHAT, timeout=120,
                    prefill=""):
    return llm.generate(system, user, model, url, timeout, prefill)


ollama_generate._is_live = True


def ollama_generate_stream(system, user, model=ANSWER_MODEL, url=OLLAMA_CHAT,
                           timeout=120, prefill="", on_token=None):
    return llm.generate_stream(system, user, model, url, timeout, prefill, on_token)


ollama_generate_stream._is_live = True
