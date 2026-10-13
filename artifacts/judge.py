"""LLM judge for the eval harness. Artifact, not engine.

Two backends, one interface, the same one-word verdicts at temperature 0:

- `ollama` (default): `granite4.1:8b` — cross-family with the answerer
  (qwen2.5:7b), offline, no key, one model swap per eval run.
- `openai` (opt-in): any provider exposing an OpenAI-compatible
  `/chat/completions` or `/responses` wire — OpenAI, Anthropic's compat
  endpoint, Gemini's compat endpoint, OpenRouter, DeepSeek, Groq, Mistral,
  and the OpenCode Zen/Go relay (which serves `muse-spark` on `/responses`
  only, and pins requests with `x-opencode-session`; a random stable session
  is generated per process unless `JUDGE_OPENCODE_SESSION` is set).
  Configured with `JUDGE_BASE_URL`, `JUDGE_MODEL`, `JUDGE_WIRE` (`chat`
  default, `responses`), and a key from `JUDGE_API_KEY` or
  `JUDGE_API_KEY_FILE` (a path; the file is gitignored as `.judge-key` when
  kept in the repo). A frontier judge is the stronger oracle for validating
  the local one; the default stays offline so routine runs need no key and
  no network. The engine, the server, and the batteries never use this path.

Model identity is recorded in every judged output (`judge_name()`): a judge
swap without a version pin would silently drift the metric series.

The verdicts are UNVALIDATED against human labels; a stronger judge is a
better prior, not ground truth.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import answer as A

JUDGE_BACKEND = os.environ.get("JUDGE_BACKEND", "ollama")
JUDGE_MODEL = os.environ.get(
    "JUDGE_MODEL", "granite4.1:8b" if JUDGE_BACKEND == "ollama" else ""
)
JUDGE_BASE_URL = os.environ.get("JUDGE_BASE_URL", "https://api.openai.com/v1")
JUDGE_WIRE = os.environ.get("JUDGE_WIRE", "chat")
JUDGE_REASONING = os.environ.get("JUDGE_REASONING", "minimal")
JUDGE_MAX_OUTPUT = int(os.environ.get("JUDGE_MAX_OUTPUT", "2048"))
PASSAGE_CHARS = 2000  # prompt-size guard, not a quality knob
ANSWER_CHARS = 2000
CLOUD_TIMEOUT = 60.0
CHAT_MAX_TOKENS = 16
_LAZY_SESSION = {"value": ""}

RELEVANCE_SYSTEM = (
    "You are a strict retrieval judge for a book question-answering system. "
    "You see one question and one passage from the book. Reply with exactly "
    "one word: relevant, if the passage contains information that helps "
    "answer the question; not_relevant, if it does not. No other words."
)
KEY_FACT_SYSTEM = (
    "You check a system answer against one key fact. Reply with exactly one "
    "word: states, if the answer states the key fact (paraphrase allowed); "
    "missing, if it does not. No other words."
)
FIDELITY_SYSTEM = (
    "You check whether an answer stays inside its source passages. You see a "
    "question, passages from a book, and a system answer. Reply with exactly "
    "one word: supported, if every claim in the answer comes from the "
    "passages; unsupported, if any claim adds facts the passages do not "
    "state. No other words."
)
EXAMPLE_SYSTEM = (
    "You check whether an answer uses a concrete example from its source "
    "passages. You see a question, passages from a book, and a system "
    "answer. Reply with exactly one word: example, if the answer includes a "
    "concrete example that appears in the passages; none, if it does not. "
    "No other words."
)

# Ordered: the negative phrasings are checked before the bare positive word,
# so "not relevant" cannot match "relevant".
RELEVANCE_KEYS = [
    ("not_relevant", ["not relevant", "irrelevant", "no", "false"]),
    ("relevant", ["relevant", "yes", "true"]),
]
KEY_FACT_KEYS = [
    ("missing", ["missing", "not stated", "not mentioned", "no", "false"]),
    ("states", ["states", "yes", "true"]),
]
FIDELITY_KEYS = [
    (
        "unsupported",
        [
            "unsupported",
            "not supported",
            "not in the passage",
            "not in the passages",
            "outside the passages",
            "adds facts",
            "adds information",
            "not stated",
            "no",
            "false",
        ],
    ),
    ("supported", ["supported", "yes", "true"]),
]
EXAMPLE_KEYS = [
    ("none", ["none", "no", "false", "not"]),
    ("example", ["example", "yes", "true"]),
]


def judge_name():
    return f"{JUDGE_BACKEND}:{JUDGE_MODEL or 'unset'}"


def _api_key():
    key = os.environ.get("JUDGE_API_KEY")
    if key:
        return key.strip()
    path = os.environ.get("JUDGE_API_KEY_FILE")
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    return ""


def _cloud_headers():
    key = _api_key()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "ask-this-book-eval/1.0",
    }
    session = os.environ.get("JUDGE_OPENCODE_SESSION", "") or _LAZY_SESSION["value"]
    if not session and "opencode.ai" in JUDGE_BASE_URL:
        session = str(uuid.uuid4())
        _LAZY_SESSION["value"] = session
    if session:
        headers["x-opencode-session"] = session
    return headers


def _cloud_payload(system, user, model):
    if JUDGE_WIRE == "responses":
        payload = {
            "model": model,
            "instructions": system,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user}],
                }
            ],
            "max_output_tokens": JUDGE_MAX_OUTPUT,
            "temperature": 0,
        }
        if JUDGE_REASONING:
            payload["reasoning"] = {"effort": JUDGE_REASONING}
        return payload
    return {
        "model": model,
        "temperature": 0,
        "max_tokens": CHAT_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }


def _cloud_url():
    suffix = "/responses" if JUDGE_WIRE == "responses" else "/chat/completions"
    return JUDGE_BASE_URL.rstrip("/") + suffix


def _cloud_text(body):
    choices = body.get("choices")
    if isinstance(choices, list):
        content = (choices or [{}])[0].get("message", {}).get("content")
        return content if isinstance(content, str) else None
    parts = []
    for item in body.get("output") or []:
        if item.get("type") != "message":
            continue
        for piece in item.get("content") or []:
            if piece.get("type") == "output_text" and isinstance(piece.get("text"), str):
                parts.append(piece["text"])
    return "\n".join(parts) if parts else None


def _cloud_complete(system, user, model, timeout):
    """One cloud judge call on the configured wire. One retry for transients."""
    if not model:
        raise RuntimeError("JUDGE_MODEL is required for JUDGE_BACKEND=openai")
    if not _api_key():
        raise RuntimeError(
            "set JUDGE_API_KEY or JUDGE_API_KEY_FILE for JUDGE_BACKEND=openai"
        )
    request = urllib.request.Request(
        _cloud_url(),
        data=json.dumps(_cloud_payload(system, user, model)).encode("utf-8"),
        headers=_cloud_headers(),
    )
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = _cloud_text(body)
            if not content or not content.strip():
                raise RuntimeError("empty judge completion")
            return content.strip()
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt == 1:
                time.sleep(2)
                continue
            raise RuntimeError(f"judge HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 1:
                time.sleep(2)
                continue
            raise RuntimeError(f"judge unreachable: {exc}") from exc
    raise RuntimeError("judge failed")  # unreachable; the loop returns or raises


def _complete(system, user, model, timeout):
    if JUDGE_BACKEND == "openai":
        return _cloud_complete(system, user, model, timeout)
    return A.ollama_generate(system, user, model, timeout=timeout)


LAST_REPLY = {"text": ""}  # the last raw judge reply, for harness debugging


def _match(text, keys):
    normalized = re.sub(r"[^a-z]+", " ", (text or "").strip().lower())
    for label, phrases in keys:
        for phrase in phrases:
            if re.search(rf"\b{re.escape(phrase)}\b", normalized):
                return label
    return None


def _one_word(system, user, keys, model=None, timeout=None):
    judge_model = model or JUDGE_MODEL
    judge_timeout = timeout or CLOUD_TIMEOUT
    reply = _complete(system, user, judge_model, judge_timeout)
    label = _match(reply, keys)
    if label is None:
        # One strict retry: cloud judges do not always echo one of our words
        # (measured 2026-10-13: 19 of 20 Muse fidelity replies paraphrased
        # past the key list). The retry fires only on a miss.
        strict = (
            system
            + " Reply with exactly one of: "
            + ", ".join(name for name, _ in keys)
            + "."
        )
        reply = _complete(strict, user, judge_model, judge_timeout)
        label = _match(reply, keys)
    LAST_REPLY["text"] = reply
    return label or "judge_error"


def judge_relevance(question, passage, model=None, timeout=None):
    user = f"Question: {question}\n\nPassage:\n{passage[:PASSAGE_CHARS]}"
    return _one_word(RELEVANCE_SYSTEM, user, RELEVANCE_KEYS, model, timeout)


def judge_key_fact(question, key_fact, answer, model=None, timeout=None):
    user = (
        f"Question: {question}\nKey fact: {key_fact}\n\n"
        f"System answer:\n{answer[:ANSWER_CHARS]}"
    )
    return _one_word(KEY_FACT_SYSTEM, user, KEY_FACT_KEYS, model, timeout)


def judge_book_fidelity(question, passages_text, answer, model=None, timeout=None):
    """supported / unsupported: the answer adds no fact outside the passages."""
    user = (
        f"Question: {question}\n\nPassages:\n{passages_text[:4000]}\n\n"
        f"System answer:\n{answer[:ANSWER_CHARS]}"
    )
    return _one_word(FIDELITY_SYSTEM, user, FIDELITY_KEYS, model, timeout)


def judge_plain_example(question, passages_text, answer, model=None, timeout=None):
    """example / none: the answer uses a concrete example from the passages."""
    user = (
        f"Question: {question}\n\nPassages:\n{passages_text[:4000]}\n\n"
        f"System answer:\n{answer[:ANSWER_CHARS]}"
    )
    return _one_word(EXAMPLE_SYSTEM, user, EXAMPLE_KEYS, model, timeout)
