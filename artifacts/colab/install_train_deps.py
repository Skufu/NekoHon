"""Install the finetune stack on a fresh Colab VM.

The training script imports trl/unsloth at module level, so this must run in the
same kernel first. Kept separate because pip output drowns the training log.
"""

import importlib
import subprocess
import sys

PACKAGES = ["unsloth", "trl", "peft", "accelerate", "bitsandbytes", "datasets"]

subprocess.run([sys.executable, "-m", "pip", "install", "-q", *PACKAGES], check=True)
for name in ("trl", "unsloth", "peft", "datasets", "bitsandbytes"):
    module = importlib.import_module(name)
    print(name, getattr(module, "__version__", "ok"))
print("DEPS READY")
