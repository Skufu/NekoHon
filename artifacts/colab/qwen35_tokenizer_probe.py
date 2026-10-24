"""Find the text-tokenization path for the Qwen3.5 processor wrapper."""
import sys

from unsloth import FastLanguageModel

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Qwen3.5-2B", max_seq_length=2048, load_in_4bit=True)

print("wrapper:", type(tokenizer).__name__)
inner = getattr(tokenizer, "tokenizer", None)
print("inner:", type(inner).__name__ if inner is not None else None)

for label, fn in [
    ("positional", lambda: tokenizer("hello")),
    ("keyword text", lambda: tokenizer(text="hello")),
    ("inner positional", lambda: inner("hello") if inner is not None else None),
]:
    try:
        out = fn()
        print(label, "->", type(out).__name__, len(out["input_ids"]), out["input_ids"][:6])
    except Exception as exc:
        print(label, "FAILED:", repr(exc)[:200])

try:
    text = tokenizer.apply_chat_template(
        [{"role": "user", "content": "What is a data pipeline?"}],
        tokenize=False, add_generation_prompt=False,
        chat_template_kwargs={"enable_thinking": False})
    print("render:", repr(text[:120]))
    print("inner render tokens:", len(inner(text)["input_ids"]))
    print("keyword render tokens:", len(tokenizer(text=text)["input_ids"]))
except Exception as exc:
    print("render path FAILED:", repr(exc)[:300])

print("image_token_id:", getattr(tokenizer, "image_token_id", None))
print("PROBE DONE")
sys.exit(0)
