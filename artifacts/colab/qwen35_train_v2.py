"""Qwen3.5-2B LoRA on the x3 corpus (844 rows), with a held-out validation split.

Differences from qwen35_train.py (the 417-row x2f run):
- data: quote-refuse-2026-10-17.train-x3.jsonl (844 rows, fde + 5 other domains)
- 10% of rows held out **by question**, so paraphrases of the same question do
  not sit on both sides
- eval loss every epoch, printed as a table, so "overfit" is a number not a guess
- exports only the Q4_K_M GGUF (the merged zip was the slow part last time)

Everything else is the x2f recipe: r=16/alpha=32, 7 projections, lr 2e-4,
responses-only, seed 3407, epochs = max(3, round(1968 / len(train))).

Run on the VM: python qwen35_train_v2.py
"""

import gc
import hashlib
import json
import os
import random
import re
import sys

import torch

BASE = "unsloth/Qwen3.5-2B"
# Overridable so the same script can produce the 3-epoch and 2-epoch exports
# without a copy: FORCE_EPOCHS=2 EXPORT_NAME=... python qwen35_train_v2.py
FORCE_EPOCHS = int(os.environ.get("FORCE_EPOCHS", "0"))
EXPORT = "/content/" + os.environ.get("EXPORT_NAME", "nekohon_q35_2b_x3")
DATA = "/content/" + os.environ.get("DATA_NAME", "x3-train.jsonl")
EXPECTED = int(os.environ.get("EXPECTED_ROWS", "844"))
VAL_FILE = os.environ.get("VAL_QUESTIONS", "")
SEED = 3407
VAL_FRACTION = 0.10
REFUSAL = "Not in this book."
QUESTION_RE = re.compile(r"^Question:\s*(.+?)(?:\n\n|\Z)", re.S | re.M)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(msg):
    print("TRAIN FAIL:", msg)
    sys.exit(1)


def question_of(row):
    user = next((m["content"] for m in row["messages"] if m["role"] == "user"), "")
    match = QUESTION_RE.search(user)
    if match:
        return " ".join(match.group(1).lower().split())
    # No Question: line (highlight rows): group by the selection text so the
    # same highlight never appears on both sides.
    return " ".join(user[:300].lower().split())


def split_by_question(rows, fraction, seed):
    groups = {}
    for row in rows:
        groups.setdefault(question_of(row), []).append(row)
    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    target = round(len(rows) * fraction)
    valid, taken = [], 0
    for key in keys:
        if taken >= target:
            break
        valid.extend(groups[key])
        taken += len(groups[key])
    valid_ids = {id(row) for row in valid}
    train = [row for row in rows if id(row) not in valid_ids]
    return train, valid, len(groups), len(valid_ids)


gc.collect()
torch.cuda.empty_cache()

from datasets import Dataset  # noqa: E402
from peft import PeftModel  # noqa: F401,E402 - fail early on a broken install
from trl import SFTConfig, SFTTrainer  # noqa: E402
from unsloth import FastLanguageModel  # noqa: E402
from unsloth.chat_templates import train_on_responses_only  # noqa: E402

rows = []
with open(DATA, encoding="utf-8") as handle:
    for line in handle:
        if line.strip():
            rows.append(json.loads(line))
print(len(rows), "cards loaded from", DATA)
if len(rows) != EXPECTED:
    fail("row count mismatch: %d != %d" % (len(rows), EXPECTED))
print("data sha256:", sha256_file(DATA))
print("refusals:", sum(1 for r in rows if r["messages"][-1]["content"].strip() == REFUSAL),
      "of", len(rows))

train_rows, valid_rows, group_count, valid_count = split_by_question(
    rows, VAL_FRACTION, SEED)
if VAL_FILE and os.path.exists(VAL_FILE):
    # Round 3: reuse round 2's held-out questions so validation loss stays
    # comparable across corpora.
    with open(VAL_FILE, encoding="utf-8") as handle:
        val_keys = {" ".join(line.lower().split()) for line in handle if line.strip()}
    valid_rows = [r for r in rows if question_of(r) in val_keys]
    train_rows = [r for r in rows if question_of(r) not in val_keys]
    valid_count = len(valid_rows)
    group_count = len({question_of(r) for r in rows})
    print("split by fixed validation question list:", VAL_FILE)
print("questions:", group_count)
print("split by question: train %d rows / valid %d rows (%.1f%%)"
      % (len(train_rows), valid_count, 100.0 * valid_count / len(rows)))
print("refusals in valid:", sum(1 for r in valid_rows
                                if r["messages"][-1]["content"].strip() == REFUSAL))
if valid_count < 60:
    fail("validation split too small: %d rows" % valid_count)

max_seq_length = 4096
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=BASE, max_seq_length=max_seq_length, load_in_4bit=True)
# Qwen3.5 is a VL model: `tokenizer` is a Qwen3VLProcessor whose positional
# __call__ treats a string as an image source. The text tokenizer is inner.
text_tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
print("loaded:", type(model).__name__)
print("processor:", type(tokenizer).__name__, "text tokenizer:", type(text_tokenizer).__name__)

wanted = ["q_proj", "k_proj", "v_proj", "o_proj",
          "gate_proj", "up_proj", "down_proj"]
present = {n.split(".")[-1] for n, _ in model.named_modules()}
targets = [t for t in wanted if t in present]
if not targets:
    fail("none of the x2f projections exist on this architecture")
print("lora targets:", targets)

model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=32, lora_dropout=0.0, target_modules=targets,
    use_gradient_checkpointing="unsloth", random_state=SEED)


def render(messages):
    for extra in ({"chat_template_kwargs": {"enable_thinking": False}}, {}):
        try:
            return tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=False, **extra)
        except Exception:
            pass
    return tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False)


def to_dataset(items):
    return Dataset.from_list([{"text": render(item["messages"])} for item in items])


train_dataset = to_dataset(train_rows)
eval_dataset = to_dataset(valid_rows)

lens = sorted(len(text_tokenizer(t["text"])["input_ids"]) for t in train_dataset)
print("token lens p50/p90/max:", lens[len(lens) // 2], lens[int(.9 * len(lens)) - 1], lens[-1])
if lens[-1] > max_seq_length:
    fail("truncation would cut the tail: max len %d" % lens[-1])
epochs = FORCE_EPOCHS or max(3, round(1968 / len(train_dataset)))
print("epochs:", epochs, "for", len(train_dataset), "train rows (~%d presentations)"
      % (epochs * len(train_dataset)))

trainer = SFTTrainer(
    model=model,
    train_dataset=train_dataset,
    eval_dataset=eval_dataset,
    processing_class=text_tokenizer,
    args=SFTConfig(
        dataset_text_field="text",
        per_device_train_batch_size=2,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=4,
        warmup_steps=5,
        num_train_epochs=epochs,
        max_length=max_seq_length,
        learning_rate=2e-4,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=5,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=SEED,
        output_dir="/content/outputs",
        save_strategy="no",
        eval_strategy="epoch",
        report_to="none",
    ),
)
trainer = train_on_responses_only(
    trainer,
    instruction_part="<|im_start|>user\n",
    response_part="<|im_start|>assistant\n",
)
print("rows after responses-only prep:", len(trainer.train_dataset), "of", len(train_dataset))
if len(trainer.train_dataset) != len(train_dataset):
    fail("truncation canary dropped rows")

batch = trainer.data_collator([trainer.train_dataset[0]])
keep = [t.item() for t, l in zip(batch["input_ids"][0], batch["labels"][0]) if l != -100]
sup = text_tokenizer.decode(keep)
print("supervised tokens:", len(keep), "of", batch["labels"].shape[1])
print("supervised tail:", repr(sup[-120:]))
if "<|im_end|>" not in sup:
    fail("end token not supervised")

print("config:", trainer.args.max_length, trainer.args.max_steps,
      trainer.args.seed, trainer.args.lr_scheduler_type, trainer.args.learning_rate)
trainer.train()

# Per-epoch table: mean of the logged train losses inside each epoch, and the
# eval loss transformers records at the epoch boundary.
history = trainer.state.log_history
table = []
current = {"epoch": 0, "train": []}
for entry in history:
    if "loss" in entry and "epoch" in entry:
        current["train"].append(entry["loss"])
    if "eval_loss" in entry:
        epoch = int(round(entry["epoch"]))
        table.append({
            "epoch": epoch,
            "train_loss": round(sum(current["train"]) / len(current["train"]), 4)
            if current["train"] else None,
            "eval_loss": round(entry["eval_loss"], 4),
        })
        current = {"epoch": epoch, "train": []}
print("EPOCH TABLE")
for row in table:
    print("  epoch %d  train %.4f  eval %.4f" % (row["epoch"], row["train_loss"], row["eval_loss"]))
if len(table) >= 2:
    first, last = table[0]["eval_loss"], table[-1]["eval_loss"]
    print("VAL TREND: %.4f -> %.4f (%s)" % (
        first, last, "rising - overfit risk" if last > first else "falling - no overfit signal"))
json.dump(table, open("/content/epoch-table.json", "w"), indent=1)

model.eval()
probe_messages = train_rows[0]["messages"][:2]
probe = render(probe_messages)
inputs = text_tokenizer(probe, return_tensors="pt").to(model.device)
with torch.no_grad():
    out = model.generate(**inputs, max_new_tokens=160, do_sample=False)
reply = text_tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=False)
print("STOP-CHECK reply:", reply[:600])
print("STOP-CHECK:", "SANE" if "<|im_end|>" in reply else "LONG OUTPUT")

model.save_pretrained(EXPORT + "_lora")
text_tokenizer.save_pretrained(EXPORT + "_lora")

out_dir = EXPORT + "_q4_k_m"
try:
    model.save_pretrained_gguf(out_dir, text_tokenizer, quantization_method="q4_k_m")
    print("GGUF dir:", out_dir)
except Exception as exc:
    print("q4_k_m export failed:", repr(exc))
    fail("no GGUF")

print("TRAIN DONE")
