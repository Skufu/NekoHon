#!/usr/bin/env bash
# Phase 7 wifi-off gate. Run as: bash artifacts/probes/phase7-offline.sh
# Wi-Fi must be OFF. Ollama (11434) and server.py (8000) must already be up.
set -u
cd "$(dirname "$0")/../.."
LOG=artifacts/evidence/phase7-offline/phase7-offline.log
{ echo "== phase 7 offline run =="; date "+%Y-%m-%d %H:%M:%S"; } >> "$LOG"

code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" https://example.com)
echo "offline check: https://example.com -> $code" | tee -a "$LOG"
if [ "$code" != "000" ]; then
  echo "ABORT: still online (expected 000). Turn Wi-Fi off first. Nothing else was run." | tee -a "$LOG"
  exit 1
fi

echo "--- health ---" | tee -a "$LOG"
curl -s -m 5 http://127.0.0.1:8000/health | tee -a "$LOG"; echo | tee -a "$LOG"

echo "--- ask (same command as online) ---" | tee -a "$LOG"
curl -s -m 120 -X POST http://127.0.0.1:8000/ask -H 'Content-Type: application/json' \
  -d '{"book_id": "fde", "question": "What is a watermark?", "selection": null, "mode": "ask"}' \
  | tee artifacts/evidence/phase7-offline/phase7-offline-ask.json | tee -a "$LOG"; echo | tee -a "$LOG"

echo "--- netstat :8000 ---" | tee -a "$LOG"
netstat -ano | findstr :8000 | tee -a "$LOG"
pid=$(netstat -ano | awk '/127.0.0.1:8000/ && /LISTENING/ {print $NF; exit}')
echo "--- netstat pid $pid ---" | tee -a "$LOG"
netstat -ano | awk -v p="$pid" '$NF==p' | tee -a "$LOG"
echo "--- netstat :11434 ---" | tee -a "$LOG"
netstat -ano | findstr :11434 | tee -a "$LOG"

echo "== done. Wi-Fi can go back on. Hand the log to the agent. ==" | tee -a "$LOG"
