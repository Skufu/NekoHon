"""Design critic probe — send a screenshot to a vision model on OpenCode Go.

Usage:
    python artifacts/probes/design-critic-2026-10-21.py \
        --image artifacts/runs/design/menu-1440.png \
        --prompt-file artifacts/runs/design/critic-prompt.txt \
        --out artifacts/runs/design/critique-01.md

Pure stdlib (repo rule: the engine and its tooling stay stdlib). The image is
attached as an inline data URL, so the critic sees exactly the pixels that were
captured and nothing about the implementation.

Model default: minimax-m3.1-flash-free (OpenCode Go relay).
"""

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.opencode_call import (  # noqa: E402
    OPENCODE_BASE_URL,
    _parse_response_text,
    resolve_api_key,
)

DEFAULT_MODEL = "minimax-m3.1-flash-free"
DEFAULT_WIRE = "chat"  # chat/completions carries image_url parts most reliably


def image_data_url(path: Path) -> str:
    """Base64 data URL for an image file, with the mime type sniffed."""
    raw = path.read_bytes()
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif raw[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def build_payload(
    prompt: str,
    image_url: str,
    model: str,
    wire: str,
    max_tokens: int,
    reasoning_effort: str = "minimal",
):
    if wire == "responses":
        return {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": image_url},
                    ],
                }
            ],
            "max_output_tokens": max_tokens,
            "reasoning": {"effort": "minimal"},
        }
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        # minimax-m3.1-flash-free is a reasoning model: without a minimal
        # effort it spends the whole token budget on reasoning and returns
        # no answer (finish_reason "length", empty content). Other models
        # may reject the parameter, so it is only sent when asked for.
        **({"reasoning_effort": reasoning_effort} if reasoning_effort else {}),
    }


def extract_text(body: dict, wire: str) -> str:
    """Pull the reply text out of a relay response.

    The relay is not uniform: content may arrive as a string, as a list of
    parts, or under a reasoning-bearing message, so every known shape is
    tried before giving up.
    """
    if not isinstance(body, dict):
        return ""

    choices = body.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0] or {}
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts = [
                part.get("text")
                for part in content
                if isinstance(part, dict) and part.get("text")
            ]
            if parts:
                return "\n".join(parts)
        if isinstance(choice.get("text"), str) and choice["text"].strip():
            return choice["text"]

    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        for piece in item.get("content") or []:
            if isinstance(piece, dict) and isinstance(piece.get("text"), str):
                if piece["text"].strip():
                    return piece["text"]

    return _parse_response_text(body, wire)


def call_critic(
    prompt: str,
    image_path: Path,
    model: str = DEFAULT_MODEL,
    wire: str = DEFAULT_WIRE,
    max_tokens: int = 4000,
    reasoning_effort: str = "minimal",
    timeout: float = 240.0,
    max_retries: int = 3,
) -> dict:
    """Send the prompt + screenshot to the critic model. Returns a result dict."""
    key = resolve_api_key()
    if not key:
        return {
            "status": "error",
            "error": "Missing OpenCode API key (OPENCODE_API_KEY, JUDGE_API_KEY, ~/.judge-key)",
        }

    url = OPENCODE_BASE_URL.rstrip("/") + (
        "/responses" if wire == "responses" else "/chat/completions"
    )
    payload = build_payload(
        prompt,
        image_data_url(image_path),
        model,
        wire,
        max_tokens,
        reasoning_effort=reasoning_effort,
    )
    req_data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "ask-this-book-agent/1.0",
        "x-opencode-session": str(uuid.uuid4()),
    }

    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                text = extract_text(body, wire)
                if not text:
                    return {"status": "error", "error": "Empty completion text", "raw": body}
                return {
                    "status": "ok",
                    "model": model,
                    "wire": wire,
                    "content": text.strip(),
                }
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {err.code}: {err_body}"
            if err.code == 400 and reasoning_effort:
                # the model does not accept the reasoning parameter
                reasoning_effort = ""
                payload = build_payload(
                    prompt,
                    image_data_url(image_path),
                    model,
                    wire,
                    max_tokens,
                    reasoning_effort="",
                )
                req_data = json.dumps(payload).encode("utf-8")
                attempt -= 1
                continue
            if err.code in (429, 503) and attempt < max_retries:
                time.sleep(1.5 * attempt)
                continue
            return {"status": "error", "code": err.code, "error": last_error}
        except Exception as err:
            last_error = f"{type(err).__name__}: {err}"
            if attempt < max_retries:
                time.sleep(1.5 * attempt)
                continue
            return {"status": "error", "error": last_error}
    return {"status": "error", "error": last_error}


def main():
    parser = argparse.ArgumentParser(description="Send a screenshot to a design critic model.")
    parser.add_argument("--image", required=True, help="screenshot path")
    parser.add_argument("--prompt", default="", help="critic prompt (text)")
    parser.add_argument("--prompt-file", default="", help="critic prompt (file)")
    parser.add_argument("--out", default="", help="write the critique here")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--wire", default=DEFAULT_WIRE, choices=("chat", "responses"))
    parser.add_argument("--max-tokens", type=int, default=4000)
    parser.add_argument(
        "--reasoning-effort",
        default="minimal",
        help="reasoning effort hint; pass an empty string to omit it",
    )
    args = parser.parse_args()

    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip()
    else:
        prompt = args.prompt.strip()
    if not prompt:
        parser.error("a prompt is required (--prompt or --prompt-file)")

    image_path = Path(args.image)
    if not image_path.is_file():
        parser.error(f"image not found: {image_path}")

    result = call_critic(
        prompt,
        image_path,
        model=args.model,
        wire=args.wire,
        max_tokens=args.max_tokens,
        reasoning_effort=args.reasoning_effort,
    )
    if result["status"] != "ok":
        print("CRITIC CALL FAILED:", result.get("error"))
        sys.exit(1)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result["content"] + "\n", encoding="utf-8")
        print(f"critique written: {out_path}")
    try:
        print(result["content"])
    except UnicodeEncodeError:
        sys.stdout.buffer.write(result["content"].encode("utf-8", errors="replace") + b"\n")


if __name__ == "__main__":
    main()
