# Test Gaps and Dead Code Sweep

246 tests collected (system Python; no .venv found).

## Modules with no direct test
- prompt.py (only REFUSAL, SYSTEM, SYSTEM_ANSWER strings asserted in test_contract.py)
- server.py (exercised only via RouteShapeTest + ReaderRouteTest with heavy patching of ask/respond/ollama_generate_stream; no Handler unit tests)

## Tests that mock so heavily they would pass if the real function were deleted
- tests/test_canonical.py: patches A.fuse, A.caption_seed, A.second_reading, A.llm_second_reading, and injects search_recorder.
  ```python
  A.fuse = fuse
  A.caption_seed = caption_seed
  ...
  body = A.ask(self.index, "CDC", generate_fn=generate, search_fn=self.search_recorder(), model="m")
  self.assertEqual(self.calls["search"], "What is CDC?")
  ```
- tests/test_answer.py: every AnswerTests method supplies generate_fn + search_fn (or fake_search/fake_generate) that only record or return scripted strings; real quote/anchor/fuse paths never run.
  ```python
  def generate(system, user, model):
      self.calls["user"] = user
      return f'[Ch. 1] "{CDC_QUOTE}"\nA change feed.'
  body = A.ask(self.index, "CDC", generate_fn=generate, search_fn=..., model="m")
  ```
- tests/test_reader_routes.py: patches server.respond, server.ollama_generate_stream, and server.ask with fakes that never call the real implementations.
  ```python
  with mock.patch.object(server, "respond", fake_respond), \
          mock.patch.object(server, "ollama_generate_stream", fake_stream):
      frames = self.stream_frames({"mode": "answer", ...})
  ```
- tests/test_agentic.py: gen_from supplies scripted model replies; tools use fake_embed; no live retrieval loop.
  ```python
  gen, calls = gen_from(["semantic\nalpha beta codd", "stop"])
  result = agentic_search(index, "alpha", generate_fn=gen, tools=build_tools(fake_embed, k=2))
  ```

## Likely dead functions
- `agentic_search`, `build_tools`, `pick_next_tool`, `parse_decision`, `fallback_decision`, `decide_user_message` (agentic.py)
  Evidence: module docstring states "Not wired into the server"; no imports or calls from server.py, answer.py, retrieve.py, or any top-level module outside tests/test_agentic.py and self. Confidence: high.
- `main` (preflight.py)
  Evidence: only executed under `if __name__ == "__main__"`; no other module imports or calls preflight.main. Helper functions are tested, entrypoint is not. Confidence: medium.
- `ollama_models` (preflight.py)
  Evidence: called only inside preflight.main and its own test stubs. Confidence: medium.

## Fragile or order-dependent tests
- test_contract.py + test_reader_routes.py: ThreadingHTTPServer started in setUpClass with daemon thread; shutdown + join(timeout=5). Port allocation and timing affect CORS, route, and stream tests.
- test_answer.py + test_canonical.py + test_reader_routes.py: rely on exact mock call sequences and first-return values from injected generate_fn.
- test_text_stages.py: stemmer tests pin exact outputs from vendored Snowball (stage9-preprocessing.md records the contract); any stemmer change fails them.
- tests that compare passage order after fusion/captions assume prior deterministic sort; a single reordering change flips multiple assertions.

## 8 highest-value missing tests (ranked)
1. test_server_ask_live - POST /ask (mode=ask and mode=answer) against a real seeded index with no patches on respond/ask/search.
2. test_prompt_full_construction - verifies exact SYSTEM vs SYSTEM_ANSWER vs answer_user_message vs user_message strings for every mode and cue.
3. test_ollama_generate_failure_paths - network error, bad JSON, timeout, and empty-reply cases in ollama_generate / ollama_generate_stream return clean refusals or raise documented errors.
4. test_preflight_partial_state - next_steps and exit code when book present + index absent + ollama up but models missing.
5. test_answer_mode_retry - the uncited prefill retry path in respond (including spell probe) exercised without any generate_fn injection.
6. test_quiz_end_to_end - quiz mode round-trip from server route through parse_completion, key hiding, and exact refusal on leak.
7. test_readings_from_ask - second_reading and llm_second_reading actually triggered and kept (or dropped) inside an ask/respond flow on a minimal index with a deliberate typo.
8. test_figure_attach_mid_passage - a passage that names a figure in the second sentence (not the first 5) still attaches the figure card in ask and answer modes.