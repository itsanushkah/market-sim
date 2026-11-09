# Lessons log (append as you go; raw material for report section 4)

- 2026-11-05: Built the pipeline. Mock backend makes every ablation look the same (expected): only real runs count.
- 2026-11-05: No API budget, so switched to a free local model (Ollama, qwen2.5:3b, 8 GB MacBook Air).
  Warm call ~6 s; 8 parallel calls took 91 s (slower than sequential: RAM-bound) -> run calls sequentially.
- 2026-11-05: First probe: the 3B seller asked exactly its unit cost (cost 60, ask 60) even with a best bid of 95,
  and claimed this "maximizes profit". Small models don't reason about surplus well: candidate prompt fix.
- 2026-11-05: FIRST REAL RUN (llm_full, qwen2.5:3b, seed 0) saved as results/llm_full_qwen3b_v0.
  Efficiency 0.817, which is WORSE than random ZI-C traders (0.889). Price RMSD 24 vs P*=100; 4% of trades in the CE band.
  Took 2.7 h (274 calls, ~36 s each) instead of the ~30 min estimated from short probes: long outputs + 8 GB RAM.
  Failure modes:
  * Garbage beliefs: many traders posted belief = 0 (mean belief 49). The analyst averaged these in, so its early
    estimates (54, 69) pulled prices the wrong way.
  * False consensus / herding: by period 3 the analyst said 115 with spread 5, traders anchored on it, prices sat at
    110-120, and only 6 of 11 efficient trades happened (period efficiency 0.57). Coordination made things worse.
  * 20% of orders violated the budget constraint (would have traded at a loss) and were clipped.
  * 33 orders priced exactly at the trader's own value/cost (zero profit).
- 2026-11-05: v1 fixes (belief filter, profit preview in prompt, analyst-can-be-wrong caveat, short outputs).
  1-period test vs v0 period 1 (same seed): efficiency 0.917 -> 0.942, RMSD 29.2 -> 25.5, trades 9 -> 12 (CE 11),
  invalid beliefs 12 -> 0, mean belief 31 -> 99 (P*=100), budget violations 24% -> 19%, zero-profit orders 12 -> 8.
  Single seed/period: directionally good, not yet significant.
  New problem: a 150-token cap truncated 23% of answers (the model ignores "max 15 words"). Fix: cap 200 + lenient
  parser that closes a cut-off reasoning string if all required fields are present. Probe: 8/8 valid, ~11 s/call
  (v0 ~36 s/call).
- 2026-11-06: FULL v1 RUN (llm_full_qwen3b_v1, seed 0): efficiency 0.817 -> 0.986, higher than every one of the
  10 ZI-C seeds (0.858-0.939, mean 0.889). Period efficiencies 0.98 / 1.00 / 0.97 (v0: 0.92 / 0.96 / 0.57).
  Zero-profit orders 33 -> 15. Period-3 herding failure is gone.
  BUT prices settled at ~88-90, not P*=100 (only 3% of trades in the CE band); the analyst consensus sat at 90.
  Agents coordinate on *a* price, not the competitive one: high efficiency, biased split of surplus (buyers gain).
  Budget-violation rate unchanged (~22%). Wall time 236 min (~52 s/call) despite 11 s/call in probes; likely the
  laptop slept or throttled overnight. Timing on this laptop is unreliable.
