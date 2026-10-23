> Received from the user's research bot, 2026-10-12. Pasted verbatim.

# X research: small local LLMs for strict-format RAG answers (searched 2026-10-12)

Method: X API full-archive search (`search_posts_all`), about 14 queries. Everything below is what turned up. **Almost nothing is a controlled test of exact quoting, the gloss line or the refusal string**, so nearly all of it is anecdote. Dates are post dates.

## qwen3:4b-instruct-2507
- Anecdote with a named tag: `qwen3:4b-instruct-2507-q4_K_M`, "2.5GB, ~11s, clean output. Beat qwen3.5 and Ministral-3 (repetition loops)". This was for script generation on an M1 16GB. @rtmalikian, 2026-09-30, https://x.com/rtmalikian/status/2105269431731626444
- Anecdote: "Always seems to perform better than Qwen3.5 4B and 9B" on small local agent tasks. @rjcrabbe, 2026-09-16, https://x.com/rjcrabbe/status/2100330946910187944
- Third-party leaderboard (JevBench v1.4.2 decision benchmark, not about format): raw Qwen3 4B Instruct 2507 ranks #20 of 89 with 40.95. #1 is a fine-tuned Qwen3.5-4B. @benchmarkheaven, 2026-09-26, https://x.com/benchmarkheaven/status/2103699163548426597
- RAG use (anecdotes, no numbers): local QQ RAG bot that answers with sources, @dahaidahai2002, 2026-10-11, https://x.com/dahaidahai2002/status/2109294164542103902. Doc-QA verdict "Qwen3-4B is GOAT" (doesn't say which variant), @CLYP_XXX, 2025-10-10, https://x.com/CLYP_XXX/status/1976468508293910666. Citation-first assistant baseline, not fine-tuned yet, @run4ourfun, 2026-10-09, https://x.com/run4ourfun/status/2108591584732393550
- Serving path matters (no model named): "Same 4B weights, same 65-case suite: 0% through one serving stack, 100% through another". That was for tool calling. @imdasein, 2026-09-21, https://x.com/imdasein/status/2101918248753070444. Takeaway: test through Ollama, not through a different runtime.
- Format compliance, refusals, repetition at temp 0: **no evidence found.**

## granite4:micro / micro-h (Granite 4.0)
- Official: @ollama said "IBM Granite 4 has improved instruction following and tool-calling capabilities" and listed `granite4:micro` and `granite4:micro-h` (both 3B). 2025-10-02, https://x.com/ollama/status/1973782095811219574
- Reproducible-ish test (transcript cleanup, 13 local LLMs, same prompt, 5 seeds each): "Granite 4.0 Micro left 0 filler words", against 30 left by Gemma 3 1B. It became that app's default. @cleanunicorn, 2026-09-22, https://x.com/cleanunicorn/status/2102192387225534829
- Anecdote: `granite4:micro` is a daily driver next to `qwen3.5:4b`. @EpistoAI, 2026-09-30, https://x.com/EpistoAI/status/2105286046292611290
- Grounding, refusals, template issues: **no evidence found.** No posts from @IBM or @IBMResearch about 4.0 Micro turned up.

### New lead: Granite 4.1 (not in the current shortlist)
- Released 2026-04-29: dense 3B, 8B and 30B, Apache-2.0. People describe it as multi-stage RL for instruction following. @ArtificialAnlys, 2026-04-29, https://x.com/ArtificialAnlys/status/2049505499377193156. @newnodeai, 2026-05-04, https://x.com/newnodeai/status/2051361316183687202
- Granite 4.1 8B numbers as posted: IFEval 87.06, ArenaHard 68.98, BFCL v3 68.27. @0xCVYH, 2026-04-25, https://x.com/0xCVYH/status/2048026186035462405. A comparison against Qwen3.5 9B: IFEval 91.5 vs 87.06. @irotem98, 2026-05-04, https://x.com/irotem98/status/2051333149343334778
- Token efficiency: about 20x fewer output tokens than Qwen3.5 9B on the AA index (4M vs 78M), which suggests less padding. @wandb, 2026-04-29, https://x.com/wandb/status/2049551411277595124
- Independent probe: Granite-4.1-8B at temp 0, seed 1337, ctx 8192 passed 5 of 9 probes (55.6%). Code repair was among the failures. @NeoAIForecast, 2026-06-17, https://x.com/NeoAIForecast/status/2067161072117613023
- A community 4-bit AWQ of the 8B is about 5 GB, but that's for vLLM, not GGUF. @drawais_ai, 2026-05-04, https://x.com/drawais_ai/status/2051447913235005891
- 3B IFEval, Ollama tag: **no evidence found on X.** Check HF and the Ollama library before testing.

## qwen3.5:4b / qwen3.5:9b
- Official launch of the small series (0.8B, 2B, 4B, 9B): @Alibaba_Qwen, 2026-03-02, https://x.com/Alibaba_Qwen/status/2028460046510965160
- **Thinking and template problems at launch:** qwen3.5:9b gave gibberish in Ollama because of "wrong renderer mapping, broken /no_think, and presence_penalty 1.5" (Ollama GitHub issues #14493, #14418, #12575). @cryptonick1986, 2026-03-02, https://x.com/cryptonick1986/status/2028618880323826057. qwen3.5 4b in Ollama thinks by default. @cook_grandpa, 2026-03-03, https://x.com/cook_grandpa/status/2028828304544055313. The fix is `"think": false` on /api/chat. @SibaKotaro, 2026-03-04, https://x.com/SibaKotaro/status/2028988996496548091
- **Loops and repetition:** Qwen3.5-4B MLX 4-bit had an "endless thinking loop - seems unusable". @taussoe, 2026-03-03, https://x.com/taussoe/status/2028703558208483734. Qwen3.5 4B with thinking off gave answers that tended to loop. @yono_f4ll, 2026-03-15, https://x.com/yono_f4ll/status/2033139355225923661. In thinking mode, qwen3.5:9b produced "6,000 tokens of reasoning, 76 s" and never reached an answer, so that user defaults to think=False. @bozuemkas, 2026-09-17, https://x.com/bozuemkas/status/2100626093669540083. Qwen3.5 9B was named the "overthinking king". @stevibe, 2026-04-25, https://x.com/stevibe/status/2048043930655277446. The repetition loops in the @rtmalikian post above also count against it.
- Counterpoint: one user says 4B and 9B "both need thinking to be effective". @looking5452, 2026-03-12, https://x.com/looking5452/status/2032073476232671562
- Non-thinking decisions (game benchmark): 9B 82.7% vs 4B 24.9%. @abxda, 2026-09-23, https://x.com/abxda/status/2102588150266663138
- Memory on 8 GB: 9B Q4 about 6.6 GB plus about 1 GB KV at 32K; 4B about 3.4 GB. @pinggyio, 2026-09-20, https://x.com/pinggyio/status/2101718278444036315

## qwen3:8b
- Anecdote (one run, the author says it's not a benchmark): when result IDs were deliberately swapped, Qwen3 8B in Ollama "ignored the IDs and matched by position", while Claude followed them. That's relevant to quoting from the right passage. @AbhisekMis73551, 2026-10-11, https://x.com/AbhisekMis73551/status/2109141588068995448
- Template warning (aimed at tool calls): use the Ollama build or `--jinja`, not a random GGUF. @sunsetsyntax, 2026-10-07, https://x.com/sunsetsyntax/status/2107709021277114554
- Format compliance, refusals: **no evidence found.**

## olmo-3 7b instruct
- Official: Olmo 3-Instruct (7B) "ties or bests Qwen 2.5, Gemma 3 & Llama 3.1 on tough benchmarks". @allen_ai, 2025-11-20, https://x.com/allen_ai/status/1991507993775558997. Described as "tuned for chat & tool use". @allen_ai, 2025-11-28, https://x.com/allen_ai/status/1994448425190826160
- Firsthand format or refusal reports for the 7B Instruct: **no evidence found.**

## Other models mentioned
- Granite 4.1 3B/8B: see above. It's the strongest new lead.
- LFM2.5 (Liquid): in Mark Veerman's test of 21 small LLMs on tool-calling judgement, lfm2.5:1.2b tied for #1 at 0.880. @ramin_m_h, 2026-02-15, https://x.com/ramin_m_h/status/2022896926371311836. That's tool use, not format.
- A Qwen3.5-4B fine-tune ("decider-4b v2") is #1 on JevBench. @benchmarkheaven (link above).
- Explicit claims that a 3–8B model beats qwen2.5:7b on instruction following: **no evidence found** apart from @allen_ai's Olmo 3 claim.

## Training recipes or datasets on X
- Full-parameter fine-tune of Qwen3.5-4B and 9B Base with LLaMA-Factory: 3 epochs, LR 5e-6, BF16, ZeRO-3. @PKU_DCAI, 2026-09-23, https://x.com/PKU_DCAI/status/2102684255080133006
- Beginner Unsloth LoRA walkthrough on Qwen3-4B-Instruct-2507. @jvr0x, 2026-09-22, https://x.com/jvr0x/status/2102364361998188575
- A failure report worth knowing: a fine-tuned Qwen 4B learned the reasoning style "but it never learned the correct output format" with `<Think>`/`<guess>` tags. @goyalayus, 2026-01-04, https://x.com/goyalayus/status/2007790043168141731
- 4-bit local fine-tune on a 4 GB laptop RTX with Soup (soup-cli). @Bruno_FIBRE, 2026-08-30, https://x.com/Bruno_FIBRE/status/2094133670604886422
- A dataset built specifically for strict output format or refusals: **no evidence found.**
