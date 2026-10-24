"""Call a relay model with one line, the way the owner asked for it.

    python scripts/oc.py deepseek-v4.1-flash "summarise this"
    python scripts/oc.py deepseek-v4.1-flash --file prompt.md
    echo "..." | python scripts/oc.py deepseek-v4.1-flash

Why a wrapper: `opencode run` starts a full coding agent with repo tools, which
is the wrong tool for a judgement call and cannot take a 20 KB prompt on a
Windows command line. This calls the model directly, no tools.

Defaults are the ones that measured correct on 2026-10-24: responses wire,
temperature 0, 12k output (the model spends ~2-8k on reasoning before it
answers; 2k returns an empty completion).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from opencode_call import call_opencode  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="One-shot relay call.")
    parser.add_argument("model", help="model tag, e.g. deepseek-v4.1-flash")
    parser.add_argument("prompt", nargs="?", help="prompt text (or use --file / stdin)")
    parser.add_argument("--file", help="read the prompt from this path")
    parser.add_argument("--system", default="")
    parser.add_argument("--max-tokens", type=int, default=12000)
    parser.add_argument("--wire", default="responses", choices=["responses", "chat"])
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args()

    if args.file:
        prompt = Path(args.file).read_text(encoding="utf-8")
    elif args.prompt:
        prompt = args.prompt
    elif not sys.stdin.isatty():
        prompt = sys.stdin.read()
    else:
        parser.error("give a prompt, --file, or stdin")

    result = call_opencode(prompt=prompt, model=args.model, system=args.system,
                           wire=args.wire, max_tokens=args.max_tokens,
                           temperature=0.0, timeout=args.timeout)
    if args.as_json:
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "ok" else 1
    if result["status"] != "ok":
        print(f"Error: {result.get('error')}", file=sys.stderr)
        return 1
    print(result["content"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
