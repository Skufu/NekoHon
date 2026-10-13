"""LLM judge for the eval harness. Artifact, not engine.

Two backends, one interface, the same one-word verdicts at temperature 0:

- `ollama` (default): `granite4.1:8b` — cross-family with the answerer
  (qwen2.5:7b), offline, no key, one model swap per eval run.
- `openai` (opt-in): any provider exposing an OpenAI-compatible
  `/chat/completions` — OpenAI, Anthropic's compat endpoint, Gemini's
  compat endpoint, OpenRouter, DeepSeek, Groq, Mistral. Configured with
  `JUDGE_BASE_URL` (default https://api.openai.com/v1), `JUDGE_MODEL`, and a
  key from `JUDGE_API_KEY` or `JUDGE_API_KEY_FILE` (a path; the file is
  gitignored as `.judge-key` when kept in the repo). A frontier judge is the
  stronger oracle for validating the local one; the default stays offline so
  routine runs need no key and no network. The engine, the server, and the
  batteries never use this path.

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
from pathlib import Path

import answer as A

JUDGE_BACKEND = os.environ.get("JUDGE_BACKEND", "ollama")
JUDGE_MODEL = os.environ.get(
    "JUDGE_MODEL", "granite4.1:8b" if JUDGE_BACKEND == "ollama" else ""
)
JUDGE_BASE_URL = os.environ.get("JUDGE_BASE_URL", "https://api.openai.com/v1")
PASSAGE_CHARS = 2000  # prompt-size guard, not a quality knob
ANSWER_CHARS = 2000
CLOUD_TIMEOUT = 60.0

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


def _cloud_complete(system, user, model, timeout):
    """One OpenAI-compatible chat call. One retry for transient failures."""
    if not model:
        raise RuntimeError("JUDGE_MODEL is required for JUDGE_BACKEND=openai")
    key = _api_key()
    if not key:
        raise RuntimeError(
            "set JUDGE_API_KEY or JUDGE_API_KEY_FILE for JUDGE_BACKEND=openai"
        )
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 16,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    url = JUDGE_BASE_URL.rstrip("/") + "/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = (body.get("choices") or [{}])[0].get("message", {}).get("content")
            if not isinstance(content, str) or not content.strip():
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


def _one_word(system, user, keys, model=None, timeout=None):
    text = _complete(
        system,
        user,
        model or JUDGE_MODEL,
        timeout or CLOUD_TIMEOUT,
    )
    normalized = re.sub(r"[^a-z]+", " ", text.strip().lower())
    for label, phrases in keys:
        for phrase in phrases:
            if re.search(rf"\b{re.escape(phrase)}\b", normalized):
                return label
    return "judge_error"


def judge_relevance(question, passage, model=None, timeout=None):
    user = f"Question: {question}\n\nPassage:\n{passage[:PASSAGE_CHARS]}"
    return _one_word(RELEVANCE_SYSTEM, user, RELEVANCE_KEYS, model, timeout)


def judge_key_fact(question, key_fact, answer, model=None, timeout=None):
    user = (
        f"Question: {question}\nKey fact: {key_fact}\n\n"
        f"System answer:\n{answer[:ANSWER_CHARS]}"
    )
    return _one_word(KEY_FACT_SYSTEM, user, KEY_FACT_KEYS, model, timeout)
