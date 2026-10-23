import json
import os
import urllib.request

ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "nekohon_x3")
BASE = "http://127.0.0.1:11434"
CHAT_URL = BASE + "/api/chat"
EMBED_URL = BASE + "/api/embed"
PS_URL = BASE + "/api/ps"


def keep_alive():
    return os.environ.get("OLLAMA_KEEP_ALIVE", "24h")


def _request(url, payload):
    return urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def post_json(url, payload, timeout):
    with urllib.request.urlopen(_request(url, payload), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def chat_payload(model, messages, stream, num_predict=512):
    return {
        "model": model,
        "stream": stream,
        "think": False,
        "keep_alive": keep_alive(),
        "options": {"temperature": 0, "num_predict": num_predict},
        "messages": messages,
    }


def _messages(system, user, prefill):
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    if prefill:
        messages.append({"role": "assistant", "content": prefill})
    return messages


def generate(system, user, model, url=CHAT_URL, timeout=120, prefill=""):
    payload = chat_payload(model, _messages(system, user, prefill), False)
    content = (post_json(url, payload, timeout).get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("empty completion")
    return content.strip()


def generate_stream(system, user, model, url=CHAT_URL, timeout=120, prefill="",
                    on_token=None):
    payload = chat_payload(model, _messages(system, user, prefill), True)
    pieces = []
    with urllib.request.urlopen(_request(url, payload), timeout=timeout) as response:
        if prefill and on_token is not None:
            on_token(prefill)
        for line in response:
            line = line.strip()
            if not line:
                continue
            try:
                frame = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            piece = ((frame.get("message") or {}).get("content")) or ""
            if piece:
                pieces.append(piece)
                if on_token is not None:
                    on_token(piece)
    content = "".join(pieces)
    if not content.strip():
        raise RuntimeError("empty completion")
    return content.strip()


def embed(texts, model, url=EMBED_URL, timeout=120):
    payload = {"model": model, "input": texts, "keep_alive": keep_alive()}
    vectors = post_json(url, payload, timeout).get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise RuntimeError(f"bad embed response for {model}")
    return vectors


def loaded_models(timeout=5):
    return [m.get("name", "") for m in get_json(PS_URL, timeout).get("models", [])]
