#!/usr/bin/env python3
"""
One-command model setup, verification, and release packaging utility for ask-this-book.
Python standard library only. No external pip dependencies.

Usage:
    python scripts/setup_models.py --status
    python scripts/setup_models.py --install
    python scripts/setup_models.py --package-release
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODELS = {
    "nekohon_x3": {
        "name": "nekohon_x3",
        "tag": "nekohon_x3",
        "tag_full": "nekohon_x3:latest",
        "role": "Previous Desktop Answerer (3B Q4_K_M); the revert",
        "base_model": "Qwen/Qwen2.5-3B-Instruct",
        "gguf_filename": "nekohon_x3.Q4_K_M.gguf",
        "dir": os.path.join(REPO_ROOT, "data", "models", "nekohon_x3"),
        "committed_modelfile": os.path.join(REPO_ROOT, "models", "nekohon_x3", "Modelfile"),
        "expected_sha256": "92fb94df741b2117b20b8ba8347c4143eb70cfa4ac9237741f6e1527149fd17f",
        "expected_bytes": 1929902656,
        "size_display": "1.93 GB (1,840.5 MiB; 1,929,902,656 bytes)",
        "ollama_digest": "5a9525f8d0ac",
        "hf_url": "https://huggingface.co/Skufu1/nekohon-x3/resolve/main/nekohon_x3.Q4_K_M.gguf",
        "env_var_url": "NEKOHON_X3_URL",
        "recommended_for": "Desktop (8GB+ RAM / 4GB+ VRAM) — previous default, one flag away",
    },
    "nekohon_x3_mobile": {
        "name": "nekohon_x3_mobile",
        "tag": "nekohon_x3_mobile",
        "tag_full": "nekohon_x3_mobile:latest",
        "role": "Mobile / Edge Resource-Constrained Answerer (1.5B Q4_K_M)",
        "base_model": "Qwen/Qwen2.5-1.5B-Instruct",
        "gguf_filename": "nekohon_x3_mobile.Q4_K_M.gguf",
        "dir": os.path.join(REPO_ROOT, "data", "models", "nekohon_x3_mobile"),
        "committed_modelfile": os.path.join(REPO_ROOT, "models", "nekohon_x3_mobile", "Modelfile"),
        "expected_sha256": "c3d8492fe73114a0c3e7249da6a1646acfafc47bf1b2d2742480874af923dd93",
        "expected_bytes": 986048192,
        "size_display": "986 MB (940.4 MiB; 986,048,192 bytes)",
        "ollama_digest": "89e6798ed288",
        "hf_url": "https://huggingface.co/Skufu1/nekohon-x3/resolve/main/nekohon_x3_mobile.Q4_K_M.gguf",
        "env_var_url": "NEKOHON_X3_MOBILE_URL",
        "recommended_for": "Mobile / Laptop (4GB RAM / 2GB VRAM)",
    },
    "nekohon_q35_2b": {
        "name": "nekohon_q35_2b",
        "tag": "nekohon_q35_2b",
        "tag_full": "nekohon_q35_2b:latest",
        "role": "Candidate Desktop Answerer (Qwen3.5-2B, 417-row run)",
        "base_model": "Qwen/Qwen3.5-2B",
        "gguf_filename": "nekohon_q35_2b.Q4_K_M.gguf",
        "dir": os.path.join(REPO_ROOT, "data", "models", "nekohon_q35_2b"),
        "committed_modelfile": os.path.join(REPO_ROOT, "models", "nekohon_q35_2b", "Modelfile"),
        "expected_sha256": "5b2b573a921a0dac3d564393911dc3f0da5c12179394ac922167187cd0ed5309",
        "expected_bytes": 1312164768,
        "size_display": "1.31 GB (1,251.3 MiB; 1,312,164,768 bytes)",
        "ollama_digest": "f17a0478a7d1",
        "hf_url": "https://huggingface.co/Skufu1/nekohon-q35-2b/resolve/main/nekohon_q35_2b.Q4_K_M.gguf",
        "env_var_url": "NEKOHON_Q35_2B_URL",
        "recommended_for": "Candidate: 417-row x2f corpus, sealed 25/30",
    },
    "nekohon_q35_2b_x3_2e": {
        "name": "nekohon_q35_2b_x3_2e",
        "tag": "nekohon_q35_2b_x3_2e",
        "tag_full": "nekohon_q35_2b_x3_2e:latest",
        "role": "Primary Desktop Answerer (Qwen3.5-2B, 844-row corpus, 2 epochs)",
        "base_model": "Qwen/Qwen3.5-2B",
        "gguf_filename": "nekohon_q35_2b_x3_2e.Q4_K_M.gguf",
        "dir": os.path.join(REPO_ROOT, "data", "models", "nekohon_q35_2b_x3_2e"),
        "committed_modelfile": os.path.join(REPO_ROOT, "models", "nekohon_q35_2b_x3_2e", "Modelfile"),
        "expected_sha256": "1621bcb3911489bf8296bae7703f1ca4c0678444c8497128393dcf151717526e",
        "expected_bytes": 1312164768,
        "size_display": "1.31 GB (1,251.3 MiB; 1,312,164,768 bytes)",
        "ollama_digest": "cba00d4abf1f",
        "hf_url": "https://huggingface.co/Skufu1/nekohon-q35-2b/resolve/main/nekohon_q35_2b_x3_2e.Q4_K_M.gguf",
        "env_var_url": "NEKOHON_Q35_2B_X3_2E_URL",
        "recommended_for": "Desktop (8GB+ RAM / 3GB+ VRAM), default since 2026-10-24",
    },
}

OLLAMA_API_BASE = "http://127.0.0.1:11434"


def compute_sha256(filepath, chunk_size=1024 * 1024):
    """Compute SHA-256 digest of a local file in 1MB chunks."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def get_ollama_tags():
    """Query local Ollama instance for registered models."""
    url = f"{OLLAMA_API_BASE}/api/tags"
    req = urllib.request.Request(url, headers={"User-Agent": "ask-this-book-setup/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("models", [])
            tag_map = {}
            for m in models:
                name = m.get("name", "")
                tag_map[name] = m
                if ":" in name:
                    tag_map[name.split(":")[0]] = m
            return tag_map
    except Exception:
        return None


def probe_ollama_generate(model_tag, prompt="Hello"):
    """Quick generation probe to verify loaded model execution."""
    url = f"{OLLAMA_API_BASE}/api/generate"
    payload = json.dumps({"model": model_tag, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "ask-this-book-setup/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return True, res.get("response", "").strip()
    except Exception as e:
        return False, str(e)


def download_file(url, target_path, expected_bytes=None):
    """Download a remote file with explicit MB progress tracking."""
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    tmp_path = target_path + ".tmp"

    print(f"Connecting to: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "ask-this-book-setup/1.0"})
    with urllib.request.urlopen(req, timeout=30.0) as resp:
        total = resp.headers.get("Content-Length")
        total_bytes = int(total) if total else expected_bytes
        total_mb = (total_bytes / (1024 * 1024)) if total_bytes else 0.0

        print(f"Download size: {total_mb:.1f} MB -> {target_path}")
        downloaded = 0
        start_time = time.time()
        last_print = 0

        with open(tmp_path, "wb") as f:
            while chunk := resp.read(1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if now - last_print > 0.5:
                    pct = (downloaded / total_bytes * 100) if total_bytes else 0
                    mb = downloaded / (1024 * 1024)
                    sys.stdout.write(f"\r  [{pct:5.1f}%] {mb:7.1f} / {total_mb:7.1f} MB downloaded...")
                    sys.stdout.flush()
                    last_print = now

        sys.stdout.write("\n")
        sys.stdout.flush()

    if os.path.exists(target_path):
        os.remove(target_path)
    os.rename(tmp_path, target_path)
    elapsed = max(0.1, time.time() - start_time)
    print(f"Download complete in {elapsed:.1f}s ({(downloaded / (1024 * 1024)) / elapsed:.2f} MB/s).")


def ensure_local_modelfile(model_cfg):
    """Ensure data/models/<model>/Modelfile exists pointing to the GGUF."""
    model_dir = model_cfg["dir"]
    os.makedirs(model_dir, exist_ok=True)
    local_mf = os.path.join(model_dir, "Modelfile")
    gguf_name = model_cfg["gguf_filename"]

    # Read committed Modelfile template if available
    committed_mf = model_cfg["committed_modelfile"]
    if os.path.exists(committed_mf):
        with open(committed_mf, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = (
            f"FROM ./{gguf_name}\n"
            'TEMPLATE """{{- if .Messages }}{{- if or .System .Tools }}<|im_start|>system\n'
            "{{- if .System }}{{ .System }}{{- end }}<|im_end|>{{ end }}\n"
            '{{- range .Messages }}<|im_start|>{{ .Role }}\n{{ .Content }}<|im_end|>\n{{- end }}'
            '{{- else }}{{ .Prompt }}{{ end }}<|im_start|>assistant\n"""\n'
            'SYSTEM """You are Qwen, created by Alibaba Cloud. You are a helpful assistant."""\n'
            'PARAMETER stop "<|im_start|>"\n'
            'PARAMETER stop "<|im_end|>"\n'
            'PARAMETER stop "<|endoftext|>"\n'
            "PARAMETER temperature 0\n"
            "PARAMETER num_predict 200\n"
            "PARAMETER num_ctx 4096\n"
        )

    # Use forward-slashed relative or absolute path
    lines = content.splitlines()
    if lines and lines[0].startswith("FROM"):
        lines[0] = f"FROM ./{gguf_name}"
    content = "\n".join(lines) + "\n"

    with open(local_mf, "w", encoding="utf-8") as f:
        f.write(content)
    return local_mf


def import_into_ollama(model_cfg):
    """Import local GGUF into Ollama via ollama create."""
    model_name = model_cfg["name"]
    model_dir = model_cfg["dir"]
    local_mf = ensure_local_modelfile(model_cfg)

    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        # Check standard Windows location
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        win_ollama = os.path.join(local_app_data, "Programs", "Ollama", "ollama.exe")
        if os.path.exists(win_ollama):
            ollama_bin = win_ollama

    if not ollama_bin:
        raise RuntimeError("Ollama binary not found on PATH or LOCALAPPDATA. Please ensure Ollama is installed.")

    print(f"Importing {model_name} into Ollama via '{ollama_bin} create {model_name} -f Modelfile'...")
    proc = subprocess.run([ollama_bin, "create", model_name, "-f", "Modelfile"], cwd=model_dir, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ollama create failed (exit {proc.returncode}):\n{proc.stderr}\n{proc.stdout}")

    print(f"Successfully created Ollama model tag: {model_name}")


def run_status():
    """Print comprehensive status of local GGUFs, SHA256 checksums, and Ollama tags."""
    print("=" * 76)
    print(" ask-this-book | Model & Runtime Status Check")
    print("=" * 76)

    # 1. Ollama daemon check
    ollama_tags = get_ollama_tags()
    if ollama_tags is not None:
        print(f"Ollama Service  : ONLINE ({OLLAMA_API_BASE})")
        print(f"Registered Tags : {len(ollama_tags)} tags found in local daemon")
    else:
        print(f"Ollama Service  : OFFLINE or unreachable at {OLLAMA_API_BASE}")
        print("                  (Start Ollama before running engine or imports)")
    print("-" * 76)

    # 2. Check each model
    all_ok = True
    for key, cfg in MODELS.items():
        name = cfg["name"]
        role = cfg["role"]
        gguf_path = os.path.join(cfg["dir"], cfg["gguf_filename"])
        committed_mf = cfg["committed_modelfile"]

        print(f"\n[{name.upper()}] - {role}")
        print(f"  Target File   : {os.path.relpath(gguf_path, REPO_ROOT)}")

        # Check committed Modelfile
        if os.path.exists(committed_mf):
            print(f"  Modelfile     : PRESENT ({os.path.relpath(committed_mf, REPO_ROOT)})")
        else:
            print(f"  Modelfile     : MISSING ({os.path.relpath(committed_mf, REPO_ROOT)})")
            all_ok = False

        # Check GGUF on disk
        if os.path.exists(gguf_path):
            size_bytes = os.path.getsize(gguf_path)
            size_mb = size_bytes / (1024 * 1024)
            size_status = "MATCH" if size_bytes == cfg["expected_bytes"] else "MISMATCH"
            print(f"  Disk Size     : {size_mb:.1f} MB ({size_bytes:,} bytes) [{size_status}]")

            sha = compute_sha256(gguf_path)
            if sha == cfg["expected_sha256"]:
                print(f"  SHA-256 Check : VALID ({sha[:16]}...)")
            else:
                print(f"  SHA-256 Check : MISMATCH!\n    Actual   : {sha}\n    Expected : {cfg['expected_sha256']}")
                all_ok = False
        else:
            print(f"  Disk Status   : NOT DOWNLOADED ({cfg['size_display']} needed)")
            all_ok = False

        # Check Ollama registration
        if ollama_tags is not None:
            if name in ollama_tags or cfg["tag_full"] in ollama_tags:
                tag_info = ollama_tags.get(name) or ollama_tags.get(cfg["tag_full"])
                digest = tag_info.get("digest", "")[:12]
                print(f"  Ollama Tag    : REGISTERED ({cfg['tag_full']}, digest: {digest})")
            else:
                print(f"  Ollama Tag    : NOT REGISTERED (run 'python scripts/setup_models.py --install')")
                all_ok = False
        else:
            print(f"  Ollama Tag    : UNKNOWN (Ollama offline)")

    # 3. Check nomic-embed-text
    print("\n[NOMIC-EMBED-TEXT] - Embedding Model")
    if ollama_tags is not None:
        if "nomic-embed-text" in ollama_tags or "nomic-embed-text:latest" in ollama_tags:
            print("  Ollama Tag    : REGISTERED (nomic-embed-text:latest)")
        else:
            print("  Ollama Tag    : NOT FOUND (Run 'ollama pull nomic-embed-text')")
            all_ok = False
    else:
        print("  Ollama Tag    : UNKNOWN (Ollama offline)")

    print("\n" + "=" * 76)
    if all_ok:
        print(" Verdict: All model artifacts & Ollama tags are fully ready to serve.")
    else:
        print(" Verdict: Incomplete components detected.")
        print(" Run: python scripts/setup_models.py --install")
    print("=" * 76)


def run_install(target="all"):
    """Download missing models and import into Ollama."""
    print("=" * 76)
    print(" ask-this-book | Model Installation & Ollama Registration")
    print("=" * 76)

    targets = [target] if target in MODELS else list(MODELS.keys())

    for key in targets:
        cfg = MODELS[key]
        name = cfg["name"]
        gguf_path = os.path.join(cfg["dir"], cfg["gguf_filename"])

        print(f"\nProcessing {name} ({cfg['role']})...")

        # 1. Download if missing
        if not os.path.exists(gguf_path) or os.path.getsize(gguf_path) != cfg["expected_bytes"]:
            download_url = os.environ.get(cfg["env_var_url"]) or os.environ.get("NEKOHON_MODEL_URL") or os.environ.get("SMALLBOOK_MODEL_URL") or cfg["hf_url"]
            print(f"GGUF artifact not found locally. Initiating download for {name} ({cfg['size_display']})...")
            download_file(download_url, gguf_path, expected_bytes=cfg["expected_bytes"])

        # 2. Verify checksum
        print("Verifying SHA-256 digest...")
        sha = compute_sha256(gguf_path)
        if sha != cfg["expected_sha256"]:
            raise ValueError(
                f"SHA-256 checksum mismatch for {gguf_path}!\nActual: {sha}\nExpected: {cfg['expected_sha256']}"
            )
        print(f"SHA-256 verified: {sha[:16]}... (MATCH)")

        # 3. Import into Ollama
        import_into_ollama(cfg)

        # 4. Probe inference
        print("Probing model generation over HTTP...")
        ok, res = probe_ollama_generate(name, "What is data engineering?")
        if ok:
            print(f"Probe succeeded! Response snippet: {res[:70]}...")
        else:
            print(f"Warning: probe generation returned error: {res}")

    warmup_models(target_answer_model=target if target in MODELS else "nekohon_x3")

    print("\n" + "=" * 76)
    print(" Installation finished. To check status: python scripts/setup_models.py --status")
    print("=" * 76)


DEFAULT_EMBEDDER = "nomic-embed-text"


def warmup_models(target_answer_model="nekohon_x3", embed_model=DEFAULT_EMBEDDER):
    """Preload models into Ollama VRAM/memory with exact option parity."""
    print("\n" + "=" * 76)
    print(" Warming Ollama models into memory (zero cold-load latency)...")
    print("=" * 76)
    keep_alive = os.environ.get("OLLAMA_KEEP_ALIVE", "24h")

    # 1. Warm embedder
    embed_url = f"{OLLAMA_API_BASE}/api/embed"
    embed_payload = {
        "model": embed_model,
        "input": ["search_query: warmup"],
        "keep_alive": keep_alive,
    }
    req = urllib.request.Request(
        embed_url,
        data=json.dumps(embed_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            resp.read()
        print(f"  [Embedder] {embed_model} warmed into memory ({time.time() - t0:.2f}s)")
    except Exception as e:
        print(f"  [Embedder] Warning: failed to warm {embed_model}: {e}")

    # 2. Warm answer model(s)
    models_to_warm = [target_answer_model] if target_answer_model != "all" else ["nekohon_x3"]
    chat_url = f"{OLLAMA_API_BASE}/api/chat"
    for m in models_to_warm:
        chat_payload = {
            "model": m,
            "stream": False,
            "think": False,
            "keep_alive": keep_alive,
            "options": {"temperature": 0, "num_predict": 1},
            "messages": [{"role": "user", "content": "1"}],
        }
        req = urllib.request.Request(
            chat_url,
            data=json.dumps(chat_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        t1 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=60.0) as resp:
                resp.read()
            print(f"  [Answerer] {m} warmed into memory ({time.time() - t1:.2f}s)")
        except Exception as e:
            print(f"  [Answerer] Warning: failed to warm {m}: {e}")

    # 3. Verify /api/ps
    ps_url = f"{OLLAMA_API_BASE}/api/ps"
    try:
        with urllib.request.urlopen(ps_url, timeout=5.0) as resp:
            ps_data = json.loads(resp.read().decode("utf-8"))
            resident = [mod.get("name", "") for mod in ps_data.get("models", [])]
            print("\nCurrently resident in Ollama memory:")
            for r in resident:
                print(f"  - {r}")
    except Exception as e:
        print(f"Warning: could not query /api/ps: {e}")
    print("=" * 76)


def run_package_release():
    """Package release manifest with exact sizes, checksums, and distribution instructions."""
    print("=" * 76)
    print(" ask-this-book | Generating Model Release Manifest")
    print("=" * 76)

    manifest_path = os.path.join(REPO_ROOT, "data", "models", "release-manifest.json")
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)

    ollama_tags = get_ollama_tags() or {}

    manifest_data = {
        "manifest_version": "1.0.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo": "https://github.com/Skufu/ask-this-book",
        "huggingface_repo": "https://huggingface.co/Skufu1/nekohon-x3",
        "huggingface_repo_q35": "https://huggingface.co/Skufu1/nekohon-q35-2b",
        "models": {},
        "lora_archives": {},
        "instructions": {
            "huggingface_upload": [
                "# 1. Install Hugging Face Hub CLI",
                "pip install huggingface_hub",
                "# 2. Log in with your write token",
                "hf auth login",
                "# 3. Upload model artifacts to repository",
                "hf upload Skufu1/nekohon-q35-2b data/models/nekohon_q35_2b_x3_2e/nekohon_q35_2b_x3_2e.Q4_K_M.gguf nekohon_q35_2b_x3_2e.Q4_K_M.gguf",
                "hf upload Skufu1/nekohon-q35-2b models/nekohon_q35_2b_x3_2e/Modelfile Modelfile",
                "hf upload Skufu1/nekohon-q35-2b data/models/nekohon_q35_2b/nekohon_q35_2b.Q4_K_M.gguf nekohon_q35_2b.Q4_K_M.gguf",
                "hf upload Skufu1/nekohon-q35-2b models/nekohon_q35_2b/Modelfile Modelfile.417",
                "hf upload Skufu1/nekohon-x3 data/models/nekohon_x3/nekohon_x3.Q4_K_M.gguf nekohon_x3.Q4_K_M.gguf",
                "hf upload Skufu1/nekohon-x3 data/models/nekohon_x3_mobile/nekohon_x3_mobile.Q4_K_M.gguf nekohon_x3_mobile.Q4_K_M.gguf",
            ],
            "github_release_upload": [
                "# 1. Create a GitHub release tag",
                "gh release create nekohon-x3-v1 --title 'nekohon_x3 & nekohon_x3_mobile Models' --notes 'Official weights for ask-this-book (nekohon_x3)'",
                "# 2. Upload GGUF assets",
                "gh release upload nekohon-x3-v1 data/models/nekohon_x3/nekohon_x3.Q4_K_M.gguf",
                "gh release upload nekohon-x3-v1 data/models/nekohon_x3_mobile/nekohon_x3_mobile.Q4_K_M.gguf",
            ],
            "end_user_install": "python scripts/setup_models.py --install",
        },
    }

    for key, cfg in MODELS.items():
        gguf_path = os.path.join(cfg["dir"], cfg["gguf_filename"])
        exists = os.path.exists(gguf_path)
        actual_bytes = os.path.getsize(gguf_path) if exists else cfg["expected_bytes"]
        actual_sha = compute_sha256(gguf_path) if exists else cfg["expected_sha256"]

        tag_info = ollama_tags.get(cfg["name"]) or ollama_tags.get(cfg["tag_full"]) or {}
        tag_digest = tag_info.get("digest", "") or cfg["ollama_digest"]

        manifest_data["models"][key] = {
            "name": cfg["name"],
            "role": cfg["role"],
            "base_model": cfg["base_model"],
            "quantization": "Q4_K_M",
            "gguf_filename": cfg["gguf_filename"],
            "file_size_bytes": actual_bytes,
            "file_size_mb": round(actual_bytes / (1024 * 1024), 2),
            "sha256": actual_sha,
            "ollama_tag": cfg["tag_full"],
            "ollama_digest": tag_digest,
            "recommended_for": cfg["recommended_for"],
        }

        # Check for LoRA zip
        lora_zip = os.path.join(cfg["dir"], f"{key}_lora.zip")
        if os.path.exists(lora_zip):
            manifest_data["lora_archives"][key] = {
                "filename": os.path.basename(lora_zip),
                "file_size_bytes": os.path.getsize(lora_zip),
                "sha256": compute_sha256(lora_zip),
            }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    print(f"Wrote release manifest to:\n  {os.path.relpath(manifest_path, REPO_ROOT)}")
    print(f"\nManifest summary:")
    for k, m in manifest_data["models"].items():
        print(f"  - {m['name']} ({m['quantization']}): {m['file_size_mb']} MB, SHA256: {m['sha256'][:16]}...")
    print("\nManifest includes automated upload commands for Hugging Face Hub and GitHub Releases.")
    print("=" * 76)


def main():
    parser = argparse.ArgumentParser(description="ask-this-book model setup and release management")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="Check local GGUF artifacts, SHA256 hashes, and Ollama status")
    group.add_argument("--install", action="store_true", help="Download missing models and import into local Ollama")
    group.add_argument("--package-release", action="store_true", help="Generate release manifest (data/models/release-manifest.json)")
    group.add_argument("--warmup", action="store_true", help="Warm models into Ollama memory without reinstalling")
    parser.add_argument("--model", choices=["all"] + list(MODELS), default="all", help="Target model")

    args = parser.parse_args()

    if args.install:
        run_install(args.model)
    elif args.package_release:
        run_package_release()
    elif args.warmup:
        warmup_models(target_answer_model=args.model if args.model in MODELS else "nekohon_x3")
    else:
        run_status()


if __name__ == "__main__":
    main()
