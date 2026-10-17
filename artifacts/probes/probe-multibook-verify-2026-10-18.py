"""Probe to verify multi-book server endpoints."""
import gzip
import json
import urllib.request

req = urllib.request.Request("http://127.0.0.1:8000/health")
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode("utf-8"))
    print("Health status:", resp.status)
    print("Health data:", data)
    assert resp.status == 200
    assert data.get("book_id") == "fde"
    books = [b.get("book_id") if isinstance(b, dict) else b for b in data.get("books", [])]
    print("Books list:", books)
    for b in ["fde", "quantization", "ddia"]:
        assert b in books, f"Missing {b} in books"

req = urllib.request.Request("http://127.0.0.1:8000/chunks?book_id=fde", headers={"Accept-Encoding": "gzip"})
with urllib.request.urlopen(req) as resp:
    print("fde chunks status:", resp.status, "Encoding:", resp.headers.get("Content-Encoding"))
    assert resp.headers.get("Content-Encoding") == "gzip"
    raw = resp.read()
    raw = gzip.decompress(raw)
    chunks_fde = json.loads(raw.decode("utf-8"))
    print("fde chunks count:", len(chunks_fde.get("chunks", [])))
    assert len(chunks_fde.get("chunks", [])) == 1042

req = urllib.request.Request("http://127.0.0.1:8000/chunks?book_id=quantization")
with urllib.request.urlopen(req) as resp:
    raw = resp.read()
    chunks_q = json.loads(raw.decode("utf-8"))
    c_count = len(chunks_q.get("chunks", []))
    f_count = len(chunks_q.get("figures", []))
    print(f"quantization: {c_count} chunks, {f_count} figures")
    assert c_count == 473
    assert f_count == 76

req = urllib.request.Request("http://127.0.0.1:8000/chunks?book_id=ddia")
with urllib.request.urlopen(req) as resp:
    raw = resp.read()
    chunks_ddia = json.loads(raw.decode("utf-8"))
    c_count = len(chunks_ddia.get("chunks", []))
    f_count = len(chunks_ddia.get("figures", []))
    print(f"ddia: {c_count} chunks, {f_count} figures")
    assert c_count == 1307
    assert f_count == 90

for b in ["fde", "quantization", "ddia"]:
    req = urllib.request.Request(f"http://127.0.0.1:8000/figures/cover?book_id={b}")
    with urllib.request.urlopen(req) as resp:
        img_bytes = resp.read()
        ctype = resp.headers.get("Content-Type")
        print(f"{b} cover status: {resp.status}, bytes: {len(img_bytes)}, type: {ctype}")
        assert resp.status == 200
        assert len(img_bytes) > 0

print("ALL TASK 1 CHECKS PASSED!")
