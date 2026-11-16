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
- 2026-11-09: New metric buyer_share (share of realized surplus going to buyers) vs buyer_share_ce (share at P*).
  CE share 0.483. ZI-C r6 0.508, v0 0.520, v1 0.621: the coordinated v1 market settles below P* and shifts ~14 points
  of surplus to buyers. Efficiency went up, but the split became less competitive.
- 2026-11-09: Summaries/plots now exclude mock runs by default (--include-mock to show them).
- 2026-11-09: Behaviour categories (analysis/excerpts.py), v0 -> v1: loss attempts 17.5% -> 11.7%, zero-profit
  orders 12.0% -> 5.5%, analyst-anchored orders 17.9% -> 23.7%, profitable accepts 6.9% -> 9.9%.
  The fixes made agents more rational AND more reliant on the analyst, which explains both the efficiency gain
  and the price settling at the analyst's ~88-90 instead of 100.
  Nuance: some "zero-profit" bids (bid = value) still earned profit, because the CDA fills at the standing ask.
  Reasoning text is often inconsistent with the numbers it cites (quotes 88.08 when the analyst said 88.02).
- 2026-11-09: CENTRALIZED BASELINE (one qwen2.5:3b planner sees every value and cost, sets one clearing price;
  5 seeds, cache off). It chose 115 in 13 of 15 periods (P* = 100; once 100, twice 120). Efficiency 0.926 ± 0.016,
  price RMSD 15.3, buyers' share 0.28 (vs 0.48 at P*): the price was too high, so sellers gained.
  Its reasoning says "115 maximizes total surplus" while its own surplus sums are wrong.
  => With full information, a single small LLM still can't compute the equilibrium; the decentralized market
  (v1, 0.986 at 10 rounds) did better without anyone seeing the whole picture. Strong point for "why multi-agent".

## 2026-11-10: three-seed results (6 rounds per period)

- The overnight plan finished at 05:14. Runs took 10 min to 6.5 h each; the slow ones coincided with the laptop being busy or throttled.
- With seed 0 alone the analyst looked useless (0.922 vs 0.917 without it). With 3 seeds the ordering is clear: no comms 0.865, no analyst 0.888, full 0.945. Lesson: don't revise a story on one seed in either direction.
- The analyst pulls the surplus split toward competitive (0.43 vs 0.60 without), but agents with an analyst attempt ~3× more loss-making orders. The budget constraint absorbs those, so the analyst's gain partly relies on it.
- Bug found while regenerating excerpts: `analysis/excerpts.py` assumed 10 rounds when looking up the previous period's analyst estimate. Fixed to use the last logged round.

## 2026-11-15: TA feedback, pilot market, convergence, demo

- TA approved the topic and asked for: a clearer analyst role, with/without-analyst tests, metrics beyond price accuracy, and a small pilot.
- Pilot (6 traders): AI traders beat ZI-C (0.96 vs 0.82), but the analyst makes no difference (0.959 vs 0.965). The analyst's benefit showed only in the 10-trader market.
- New convergence metric: no condition reliably settles within 10% of P* in 6 rounds. Efficiency and price accuracy are different things.
- Laptop lesson: with swap full and on battery, one model call took minutes instead of ~10 s (two pilot runs took 4.5 and 6.5 h; the same runs took ~20 min after memory freed up). Restart and plug in before any demo.

## 2026-11-15 (evening): seeds 3 and 4 for full system and no analyst

- Four more runs (25 to 40 min each, plugged in). Full system 0.946 ± 0.028 (5 seeds), no analyst 0.861 ± 0.047.
  The normal-approximation intervals no longer overlap; Welch t ≈ 3.0, p ≈ 0.02 (computed by hand from per-seed values).
- Two 3-seed stories did not survive. "Each layer adds efficiency" is wrong: belief sharing alone (0.861) is no
  better than no communication (0.865, still 3 seeds); the gain comes from the analyst. And "the analyst makes the
  split fairer" weakened: buyers' share is 0.49 ± 0.09 with it vs 0.56 ± 0.05 without, overlapping.
- Loss attempts held up: 13.1% with the analyst vs 5.5% without.
