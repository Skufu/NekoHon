# The citation gate: an answer names a passage or it is the refusal

An answer body that cites nothing cannot be checked, so it is treated as a
failure of grounding, not as prose to be tolerated. After the model answers,
the body is scanned for a passage reference: if it names none, the engine tries
to recover one verbatim sentence from the shown passages, and if that fails the
whole answer becomes `Not in this book.` The alternative — shipping uncited
prose and measuring how often it is right — was rejected because a single
unverifiable sentence costs more trust than a refusal does.

**Consequences.** A model that forgets its citation loses the answer even when
the prose was correct; that is why one prefill retry exists before the gate
runs. Two trace transforms mark the outcomes (`citation_recovered`,
`uncited_refused`), so the failure rate is visible instead of silent.
