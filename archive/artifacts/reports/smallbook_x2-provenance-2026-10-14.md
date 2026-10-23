# smallbook_x2 — provenance chain (recorded 2026-10-14)

The dataset files are gitignored (`data/`), so this file is the
authoritative hash record for the finetuned model currently on trial as
the app default.

## Hashes (recorded 2026-10-14, from the working box)

| artifact | sha256 |
| --- | --- |
| `data/finetune/quote-refuse-2026-10-13.train-x2.jsonl` (= `train.jsonl`, 167 rows) | `653503ad257328a02f47ecaec0ab991eae2e952d6210b459e46a28f805cef92c` |
| `data/finetune/quote-refuse-2026-10-13.train-x1.jsonl` (140 rows) | `5c622c4a3539377bf29f54a2bbf061fa00b6a1df2c5316bf44de31bdaa414416` |
| `data/finetune/quote-refuse-2026-10-13.bench.jsonl` (45 rows) | `174afd18c4dff3ea6e7f95e53806101f35dc3c4d389d7d16f6d7e6a4305172ed` |
| `data/models/smallbook_x2_gguf.zip` | `2fe06467cbb55bdec93a65666d9316f5513ee1a12465dfd4f6b34528af205030` |
| `smallbook_x2` GGUF (extracted, 1929902592 bytes) | `391737a5ca1cfffff2e647b20a3eae364c7f368f9c60e726384c388070dae71a` |
| Ollama serve blob (`ollama show smallbook_x2` FROM) | `sha256-391737a5ca1cfffff2e647b20a3eae364c7f368f9c60e726384c388070dae71a` |
| `data/models/smallbook_x1_gguf.zip` | `ae0484c6f6b9dbe9c94f39b3206557803755769d2809f607aa2c0baeffe0dcc2` |
| `smallbook_x1` GGUF | `22aece2d84b2e6a99b28f19adadc1528434920a22955f3bb80e79ca1d794aa47` |
| x3-era `smallbook` GGUF (contrast) | `435ed1f8f967cfb5f8940aa34a5c707b406ea158534ba0ff2b90448216a3a98d` |
| pre-x2 `smallbook-old` blob (v2-era, contrast) | `3cc77773d61edeb201596acdbeb3bea7a460eb308e1f3f94b08e921f5c4b3ef8` |

Ollama: tag `smallbook_x2`, model digest `ba79d37a6067` (`ollama list`).

## Toolchain (the session that actually trained these)

From the Run A output, 2026-10-14: Unsloth 2026.10.5, Transformers
5.17.0, Torch 2.11.0+cu130, Triton 3.6.0, A100-40GB. The notebook
currently floats (`pip install -q unsloth`) — pin these before the next
session, and print the versions in the run output.

## Operational facts

- Revert: set `ANSWER_MODEL=qwen2.5:7b` in the environment and restart
  the server (see `prompt.py`); no code edit needed.
- Missing from the record: the Colab-side sha256 of the downloaded zip
  (add `sha256sum` to the export cell), and a sanitized committed copy of
  the `smallbook_x2` Modelfile (`FROM` was hand-patched to an absolute
  path; the served copy lives in `data/models/smallbook_x2_gguf/`).
- The trial observations and the pre-registered swap gate live in
  `x2-trial-2026-10-14.md`; the loop evidence in
  `finetune-loop-eval-2026-10-13.md`; the dataset record in
  `finetune-data-prep-2026-10-13.md`.
