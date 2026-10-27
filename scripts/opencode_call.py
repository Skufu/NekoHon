"""OpenCode Go API client for Antigravity and Gemini sub-agents.

Pure Python standard library (zero pip dependencies).
Connects to OpenCode Zen/Go relay (https://opencode.ai/zen/go/v1).

Key resolution:
    1. --api-key argument
    2. OPENCODE_API_KEY or JUDGE_API_KEY environment variable
    3. .judge-key in repo root
    4. ~/.config/opencode/opencode.json or ~/.local/share/opencode/auth.json

CLI Usage:
    python scripts/opencode_call.py --prompt "Explain data engineering in simple words"
    python scripts/opencode_call.py --model muse-spark-1.3-contributor --prompt-file query.txt --json
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

OPENCODE_BASE_URL = os.environ.get(
    "OPENCODE_BASE_URL",
    os.environ.get("JUDGE_BASE_URL", "https://opencode.ai/zen/go/v1"),
)
DEFAULT_MODEL = os.environ.get(
    "JUDGE_MODEL",
    "muse-spark-1.3-contributor",
)
DEFAULT_WIRE = os.environ.get("OPENCODE_WIRE", os.environ.get("JUDGE_WIRE", "responses"))
DEFAULT_REASONING = os.environ.get("OPENCODE_REASONING", os.environ.get("JUDGE_REASONING", "minimal"))
DEFAULT_MAX_TOKENS = int(os.environ.get("OPENCODE_MAX_TOKENS", os.environ.get("JUDGE_MAX_OUTPUT", "2048")))


def resolve_api_key(explicit_key: str = None) -> str:
    """Resolve OpenCode API key from arguments, environment, or key files."""
    if explicit_key:
        return explicit_key.strip()

    for env_var in ("OPENCODE_API_KEY", "JUDGE_API_KEY"):
        val = os.environ.get(env_var)
        if val and val.strip():
            return val.strip()

    # Repo root .judge-key
    repo_root = Path(__file__).resolve().parent.parent
    repo_key = repo_root / ".judge-key"
    if repo_key.is_file():
        k = repo_key.read_text(encoding="utf-8").strip()
        if k:
            return k

    # Standard OpenCode config paths in home directory
    try:
        home = Path.home()
        for candidate in (
            home / ".judge-key",
            home / ".config" / "opencode" / "opencode.json",
            home / ".local" / "share" / "opencode" / "auth.json",
        ):
            if candidate.is_file():
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    token = data.get("token") or data.get("api_key") or data.get("key")
                    if token and isinstance(token, str):
                        return token.strip()
                except Exception:
                    pass
    except Exception:
        pass

    return ""


def _parse_response_text(body: dict, wire: str) -> str:
    """Extract completion text from /responses or /chat/completions body."""
    if not isinstance(body, dict):
        return ""

    if wire == "responses":
        parts = []
        for item in body.get("output") or []:
            if item.get("type") != "message":
                continue
            for piece in item.get("content") or []:
                if piece.get("type") == "output_text" and isinstance(piece.get("text"), str):
                    parts.append(piece["text"])
        if parts:
            return "\n".join(parts)

    # Fallback to OpenAI chat completions choices structure
    choices = body.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content

    return ""


def call_opencode(
    prompt: str,
    model: str = DEFAULT_MODEL,
    system: str = "",
    api_key: str = None,
    base_url: str = OPENCODE_BASE_URL,
    wire: str = DEFAULT_WIRE,
    reasoning: str = DEFAULT_REASONING,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = 0.0,
    timeout: float = 60.0,
    max_retries: int = 3,
) -> dict:
    """Send a completion request to OpenCode Go relay using pure stdlib."""
    key = resolve_api_key(api_key)
    if not key:
        return {
            "status": "error",
            "error": "Missing OpenCode API key. Set OPENCODE_API_KEY, JUDGE_API_KEY, or create .judge-key",
        }

    url = base_url.rstrip("/") + ("/responses" if wire == "responses" else "/chat/completions")
    session_id = str(uuid.uuid4())

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "ask-this-book-agent/1.0",
        "x-opencode-session": session_id,
    }

    if wire == "responses":
        payload = {
            "model": model,
            "instructions": system,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                }
            ],
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }
        if reasoning:
            payload["reasoning"] = {"effort": reasoning}
    else:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

    req_data = json.dumps(payload).encode("utf-8")

    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                text = _parse_response_text(body, wire)
                if not text:
                    return {
                        "status": "error",
                        "error": "Empty completion text in OpenCode Go response",
                        "raw": body,
                    }
                return {
                    "status": "ok",
                    "model": model,
                    "content": text.strip(),
                    "session_id": session_id,
                }
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {err.code}: {err_body}"
            # 503 or 429 are transient relay rate limits; retry
            if err.code in (429, 503) and attempt < max_retries:
                time.sleep(1.0 * attempt)
                continue
            return {
                "status": "error",
                "code": err.code,
                "error": last_error,
            }
        except urllib.error.URLError as err:
            last_error = f"Network error: {err.reason}"
            if attempt < max_retries:
                time.sleep(1.0 * attempt)
                continue
            return {
                "status": "error",
                "error": last_error,
            }
        except Exception as err:
            return {
                "status": "error",
                "error": str(err),
            }

    return {
        "status": "error",
        "error": f"Failed after {max_retries} attempts: {last_error}",
    }


def main():
    parser = argparse.ArgumentParser(description="Call OpenCode Go models via pure Python stdlib.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model tag (default: {DEFAULT_MODEL})")
    parser.add_argument("--prompt", help="Prompt text")
    parser.add_argument("--prompt-file", help="Path to file containing prompt text")
    parser.add_argument("--system", default="", help="Optional system prompt")
    parser.add_argument("--api-key", help="Explicit API key (defaults to .judge-key or environment)")
    parser.add_argument("--wire", default=DEFAULT_WIRE, choices=["responses", "chat"], help="Wire format")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help="Max tokens to generate")
    parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature")
    parser.add_argument("--timeout", type=float, default=60.0, help="Timeout in seconds")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Output full JSON response")

    args = parser.parse_args()

    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    elif args.prompt:
        prompt = args.prompt
    else:
        if not sys.stdin.isatty():
            prompt = sys.stdin.read()
        else:
            parser.error("Either --prompt, --prompt-file, or piped stdin is required.")

    result = call_opencode(
        prompt=prompt,
        model=args.model,
        system=args.system,
        api_key=args.api_key,
        wire=args.wire,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        timeout=args.timeout,
    )

    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        if result["status"] == "ok":
            print(result["content"])
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
