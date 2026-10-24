"""Preflight for Qwen3.5-2B on Colab: load, inspect targets, render one row.

Stops before training. Non-zero exit on the first hard incompatibility.
"""
import json
import sys

import torch
from unsloth import FastLanguageModel

BASE = "unsloth/Qwen3.5-2B"
DATA = "/content/quote-refuse-2026-10-16.train-x2f.jsonl"


def fail(msg):
    print("PREFLIGHT FAIL:", msg)
    sys.exit(1)


try:
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE, max_seq_length=4096, load_in_4bit=True)
except Exception as exc:
    fail("FastLanguageModel.from_pretrained raised %r" % (exc,))

print("loaded:", type(model).__name__)
print("params:", sum(p.numel() for p in model.parameters()))

wanted = ["q_proj", "k_proj", "v_proj", "o_proj",
          "gate_proj", "up_proj", "down_proj"]
present = {n.split(".")[-1] for n, _ in model.named_modules()}
targets = [t for t in wanted if t in present]
print("lora targets:", targets)
if not targets:
    fail("none of the x2f projections exist on this architecture")

rows = [json.loads(line) for line in open(DATA, encoding="utf-8")]
print("rows:", len(rows))
if len(rows) != 417:
    fail("expected 417 rows")

messages = rows[0]["messages"]
print("roles:", [m["role"] for m in messages])

try:
    text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False,
        chat_template_kwargs={"enable_thinking": False})
except Exception as exc:
    print("enable_thinking kwarg rejected:", repr(exc))
    text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False)

print("render tail:", repr(text[-260:]))
if "<|im_start|>assistant" not in text:
    fail("assistant marker missing from render")

ids = tokenizer(text)["input_ids"]
print("first row tokens:", len(ids))
print("cuda:", torch.cuda.get_device_name(0), "bf16:", torch.cuda.is_bf16_supported())
print("PREFLIGHT OK")
