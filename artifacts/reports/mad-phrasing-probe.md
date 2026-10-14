# MAD phrasing probe — 2026-10-13

Trigger: the live default (`granite4.1:3b`) answered "what is MAD data
landscape" with the data-mesh passage (ch03-099) in the HTML app.

Method: `artifacts/probe-mad-phrasing.py`, in-process, both phrasings, three
models; every retrieval step printed. No server involved.

Retrieval is identical and correct for both phrasings: the caption seed fires
(figure-4-1 caption 0.751 / 0.728 vs best chunk 0.671 / 0.676) and ch04-020 —
the chunk holding the (MAD) landscape sentence — leads the passage set either
way. The failure is passage choice, not retrieval.

| model | "MAD data landscape" | "what is MAD data landscape" |
|---|---|---|
| granite4.1:3b (live default) | ch04-020, with the acronym gloss | ch03-099 (data mesh), 3/3 deterministic |
| granite4.1:8b | ch04-020 | refused ("Not in this book.") |
| qwen2.5:7b (old default) | ch04-020 | ch04-020 |

Conclusion: a phrasing sensitivity in the granite family on this ask — the
data-mesh paragraph reads as more "definitional" for a "what is" question.
qwen2.5:7b is the only one of the three that answers both phrasings. The
failure family (wrong-passage choice with the right passage present) is the
finetune's quote-selection target. A possible future engine guard (require the
cited passage to hold the question's rarest word, one guided re-ask if not) is
untested and not part of this probe. The "what is MAD data landscape" phrasing
joins the eval list for the next bake-off.
