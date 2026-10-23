@echo off
set ANSWER_MODEL=qwen2.5:7b
cd /d C:\Users\ADRIAN\workspace\github.com\Skufu\ask-this-book
start "revert rehearsal engine" /min python server.py
