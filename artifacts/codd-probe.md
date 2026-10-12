# Codd coherence probe — 2026-10-13

Trigger: "next Codd introduced the idea of what" was answered with the
normalization-definition sentence. The reported answer matches granite4.1:3b's
output exactly (it was the live default when the ask was made).

Method: `artifacts/probe-codd.py`, in-process, no server.

Book text: ch08-051 holds both sentences — the definition ("Normalization is a
database data modeling practice...") and the Codd sentence ("Codd introduced
the idea of normal forms. The normal forms are sequential..."). ch08-052 holds
"Codd's first three normal forms". "codd" df=4.

Retrieval: ch08-051 is in the shown set (4th of five; dense rank 4). Not a
retrieval miss.

| model | "Codd introduced the idea of what" | "next Codd introduced..." |
|---|---|---|
| qwen2.5:7b (restored default) | ch08-051, quotes "Codd introduced the idea of normal forms..." | same + gloss |
| granite4.1:3b | ch08-051, quotes the definition sentence instead (wrong sentence, right chunk) | quotes the Codd sentence + gloss |

Conclusion: the same family as the "what is MAD data landscape" miss — the
model chooses which sentence of the right chunk to quote; granite picks the
definitional-looking first sentence, qwen2.5 picks the question-matching
sentence. On the restored default this case answers correctly.

Proposed next (not built): a coherence guard. When the question carries a word
rare in the book (df <= RARE_DF, the lexical channel's own threshold), require
the verified quote to hold that word; if the model's quote misses it while a
shown passage holds it, replace the quote with the sentence from that passage
containing the word — book text, so the quote check holds by construction —
and keep the model's gloss. The guard fires only when the quote is already
incoherent with the question. Both known misses (this one, "what is MAD data
landscape") would be caught by construction. Needs its own tests, a full
battery rerun, and rechecks of both MAD phrasings plus this ask.
