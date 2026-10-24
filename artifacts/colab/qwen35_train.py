"""Qwen3.5-2B LoRA on the x2f recipe. Colab VM side.

Same hyperparameters as artifacts/reports/finetune-colab-2026-10-13.ipynb:
417 rows, r=16/alpha=32, 7 projections, lr 2e-4, responses-only, seed 3407,
epochs derived to hold ~1968 presentations.

Writes zips under /content for `colab download`.
"""
import gc
import hashlib
import json
import os
import shutil
import sys

import torch

BASE = "unsloth/Qwen3.5-2B"
EXPORT = "/content/nekohon_q35_2b"
DATA = "/content/quote-refuse-2026-10-16.train-x2f.jsonl"
EXPECTED = 417
SEED = 3407
REFUSAL = "Not in this book."


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(msg):
    print("TRAIN FAIL:", msg)
    sys.exit(1)


gc.collect()
torch.cuda.empty_cache()

from datasets import load_dataset
from peft import PeftModel  # noqa: F401 - imported so a broken install fails early
from transformers import TrainingArguments  # noqa: F401
from trl import SFTConfig, SFTTrainer
from unsloth import FastLanguageModel
from unsloth.chat_templates import train_on_responses_only

raw = load_dataset("json", data_files=DATA, split="train")
print(len(raw), "cards loaded from", DATA)
if len(raw) != EXPECTED:
    fail("row count mismatch: %d != %d" % (len(raw), EXPECTED))
print("data sha256:", sha256_file(DATA))
print("refusals:", sum(1 for i in range(len(raw))
                       if raw[i]["messages"][-1]["content"].strip() == REFUSAL), "of", len(raw))

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


def render(messages, gen=False):
    for extra in ({"chat_template_kwargs": {"enable_thinking": False}}, {}):
        try:
            return tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=gen, **extra)
        except Exception:
            pass
    return tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=gen)


dataset = raw.map(lambda row: {"text": render(row["messages"])},
                  remove_columns=list(raw.column_names))

lens = sorted(len(text_tokenizer(d["text"])["input_ids"]) for d in dataset)
print("token lens p50/p90/max:", lens[len(lens) // 2], lens[int(.9 * len(lens)) - 1], lens[-1])
if lens[-1] > max_seq_length:
    fail("truncation would cut the tail: max len %d" % lens[-1])
epochs = max(3, round(1968 / len(raw)))
print("epochs:", epochs, "for", len(raw), "rows (~%d presentations)" % (epochs * len(raw)))

trainer = SFTTrainer(
    model=model,
    tokenizer=text_tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=max_seq_length,
    args=SFTConfig(
        per_device_train_batch_size=2,
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
        save_strategy="epoch",
        save_total_limit=2,
        report_to="none",
    ),
)
trainer = train_on_responses_only(
    trainer,
    instruction_part="<|im_start|>user\n",
    response_part="<|im_start|>assistant\n",
)
print("rows after responses-only prep:", len(trainer.train_dataset), "of", EXPECTED)
if len(trainer.train_dataset) != EXPECTED:
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

model.eval()
probe = render(raw[0]["messages"][:2], gen=True)
inputs = text_tokenizer(probe, return_tensors="pt").to(model.device)
with torch.no_grad():
    out = model.generate(**inputs, max_new_tokens=160, do_sample=False)
reply = text_tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=False)
print("STOP-CHECK reply:", reply[:600])
print("STOP-CHECK:", "SANE" if "<|im_end|>" in reply else "LONG OUTPUT")

model.save_pretrained(EXPORT + "_lora")
text_tokenizer.save_pretrained(EXPORT + "_lora")

for quant in ("q4_k_m", "q8_0"):
    out_dir = EXPORT + "_" + quant
    try:
        model.save_pretrained_gguf(out_dir, text_tokenizer, quantization_method=quant)
        shutil.make_archive(out_dir, "zip", out_dir)
        print("made", out_dir + ".zip", os.path.getsize(out_dir + ".zip"), "bytes")
    except Exception as exc:
        print(quant, "export failed:", repr(exc))

merged = EXPORT + "_merged"
try:
    model.save_pretrained_merged(merged, text_tokenizer, save_method="merged_16bit")
    shutil.make_archive(merged, "zip", merged)
    print("made", merged + ".zip", os.path.getsize(merged + ".zip"), "bytes")
except Exception as exc:
    print("merged export failed:", repr(exc))

print("TRAIN DONE")
