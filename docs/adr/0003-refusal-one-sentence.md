# The refusal is one fixed sentence with one meaning

When the book does not cover something, the answer is exactly
`Not in this book.` — that sentence, period included, produced by one place in
the code and compared literally by the parser, the server and the tests. It
means the book does not cover the thing. It never means "I did not understand
you"; a fragment or a typo is repaired before answering rather than answered
with a refusal. The alternative — a friendlier, variable refusal — was rejected
because the sentence is a contract: the UI renders it as an honesty label, the
tests compare it byte for byte, and a user who sees it twice learns to trust it.

**Consequences.** Degenerate input cannot get a conversational reply without
introducing a second response type, which would need a new API field and a new
training shape. That is deliberately out of scope until it is designed; the
sentence keeps exactly one meaning in the meantime.
