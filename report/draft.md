# Report draft: design and evaluation sections

> Working draft. All numbers come from `results/summary.csv` after the overnight runs
> (`experiments/run_laptop_plan.sh`, finished 2026-11-10). Rewrite in your own voice; sections 1 (problem) and 4 (lessons) are not drafted here.

---

## 2. System design and implementation

### 2.1 Overview

The system is a simulated market for a single good in which ten LLM-driven trader agents (five buyers, five
sellers) trade through a continuous double auction (CDA). Each trader knows only its own private unit values
(buyers) or unit costs (sellers). No agent can see the supply and demand curves, so the competitive
equilibrium can only be discovered through interaction. A separate analyst agent never trades. It collects the
traders' (often conflicting) estimates of the equilibrium price and broadcasts a single consensus estimate,
which is the main coordination mechanism we study.

Figure 1 (`report/figures/architecture.png`) shows the components and the information flow between them.

### 2.2 Agents and roles

| Agent | Count | Sees | Produces |
|---|---|---|---|
| LLM trader | 10 (5 buyers, 5 sellers) | own remaining unit values/costs; best bid/ask; last 10 trade prices; analyst broadcasts; optional chat; its own notes from previous periods | `action` (bid / ask / pass), `price`, `belief` (estimate of the equilibrium price), optional public `message`, short `reasoning` |
| Analyst | 1 | all trade prices; all traders' posted beliefs for the round | consensus price estimate and belief spread, broadcast to all traders |
| Zero-intelligence trader (baseline) | 10 | own unit value/cost only | uniformly random price; ZI-C respects the budget constraint, ZI-U does not (Gode & Sunder, 1993) |
| Centralized planner (baseline) | 1 | every trader's private values and costs | a single market-clearing price |

**Trader prompt.** The system prompt states the market rules and a persona (rational, cautious, aggressive or
trend-following; the main condition uses "rational"). Each round the user prompt lists the trader's next
unit value or cost, the order book, recent prices, messages and, when memory is on, up to three notes
summarizing earlier periods (average price, units traded, cumulative profit). Agents return JSON constrained
by a schema, so every response either parses into a valid action or is counted as an error, and the agent
passes for that round.

**Memory.** At the end of each period every LLM trader appends a one-line note with the period's trade count,
average and range of prices, the units it traded and its cumulative profit. Notes are written by code, not by
the model, so memory adds no extra LLM calls.

### 2.3 Market mechanism

- **Order book.** Each trader holds at most one standing order; a new order replaces the old one. A bid at or
  above the best ask (or an ask at or below the best bid) trades immediately at the *standing* order's price.
  Ties use price-time priority. As in Gode & Sunder, the book is cleared after every trade.
- **Rounds.** In each round every trader that still has units observes the *same* snapshot and decides in
  parallel. Orders then enter the book in a random order. This makes the outcome independent of how fast each
  LLM call returns.
- **Budget constraint.** A buyer's bid above its value (or a seller's ask below its cost) is clipped to the
  value or cost and logged as a violation. This prevents losses and lets us measure how often agents *try* to
  trade irrationally.
- **Periods.** A session has 3 periods. Unit endowments reset each period while agent memory persists, so
  agents can learn across periods. The shock condition shifts every value and cost by +30 at the start of
  period 3.

### 2.4 Collaboration protocol and disagreement resolution

Agents communicate through a message bus with three channels (`comms/bus.py`). All messages are logged.

1. **beliefs** (trader to analyst): every trader posts its estimate of the equilibrium price each round.
   Beliefs outside the allowed price range (for example 0) are discarded before the analyst sees them.
2. **analyst** (analyst to traders): after each round the analyst resolves the disagreement between beliefs
   into one estimate. The rule-based analyst takes 0.6 × median of the last five trade prices + 0.4 × median
   belief (only the belief median before any trade has happened) and reports the spread (IQR) of beliefs, so
   traders can see how strongly the market agrees. An LLM analyst variant writes the estimate and a summary
   from the same inputs.
3. **chat** (trader to trader, optional): public, non-binding messages. This channel is off in the main
   condition and on in the `chat` ablation.

#### The analyst's role in detail

*What it can access.* Only public or volunteered information: (a) the prices of completed trades, which every
trader also sees, and (b) the price estimate ("belief") that each trader posts on the `beliefs` channel each
round. It cannot see any trader's private values or costs, the reasoning text, or unfilled orders. It never
trades and has no stake in the price. This matters for the comparison in 3.6: the centralized planner sees all
30 private numbers, while the analyst sees none of them.

*What it does with them.* The two sources answer the same question (what is the market price?) in different
ways. Trade prices are hard evidence, but there are few of them early in a period and early trades are often far
from equilibrium. Beliefs are available from round 1 but are guesses from a small model. The rule-based analyst
used in all main results combines them as

    estimate = 0.6 × median(last 5 trade prices) + 0.4 × median(valid beliefs this round)

and uses the belief median alone before the first trade. If no source is available it repeats its last estimate.

*When sources agree or conflict.*

| Situation | What the analyst does |
|---|---|
| Traders' beliefs agree with each other | Small spread (IQR) is broadcast, signalling a firm consensus |
| Traders' beliefs conflict | The median is used, so a minority of extreme beliefs cannot move the estimate; the IQR is broadcast so traders can see the disagreement and discount the estimate |
| Invalid beliefs (0, negative, above the price cap) | Removed by the auctioneer before the analyst reads them |
| Beliefs conflict with trade prices | Trades get the larger weight (0.6), because they are commitments rather than opinions; the estimate moves toward beliefs only partly |
| A few outlier trades (e.g. an opening trade at 41 or 160) | Median of the last five trades, so one or two outliers are ignored |

The broadcast is one line, e.g. "Consensus equilibrium estimate: 104.2; traders disagree by about 12.0 (IQR).
Recent trades: [...]". Traders read it the next round and are told it "is a summary of other traders' guesses
and may be wrong". Every estimate, spread and number of beliefs used is logged in `analyst.json`.

*Known weakness.* The analyst can only be as good as its inputs. If most traders share the same wrong belief,
the median is wrong too, and broadcasting it reinforces the error (the herding episode in 2.5). An LLM analyst
variant (`analyst_llm`) receives the same inputs and writes the estimate itself; it is implemented but not
included in the reported runs.

### 2.5 Optimization of the collaboration

We changed the system in response to measured failures (full log in `report/lessons_log.md`):

| Problem observed in run v0 | Change in v1 |
|---|---|
| Many traders posted belief = 0; the analyst averaged these in and broadcast estimates of 54–69 (P\* = 100) | Out-of-range beliefs are filtered before aggregation; the prompt requires a realistic belief |
| Agents traded at exactly their own value or cost, earning nothing | The prompt states the profit arithmetic for accepting the current quote (e.g. "95 − 60 = 35, a profit") |
| Herding: in period 3 all agents anchored on the analyst's 115 and only 6 of 11 efficient trades happened | The prompt notes that the analyst's estimate is a summary of other traders' guesses and may be wrong |
| ~36 s per call on the laptop | Shorter reasoning field, 200-token output cap, model kept loaded between calls, calls run sequentially (8 parallel calls were slower on 8 GB of RAM) |
| The output cap truncated 23% of answers | A lenient parser closes a cut-off trailing `reasoning` string when every required field is present |

Other engineering choices that reduce cost and make runs reproducible: an on-disk cache keyed on the full
request (re-running a seed costs nothing), JSON-schema-constrained output, seeded randomness for markets and
agent order, and a free mock backend used only for tests.

### 2.6 Implementation details

- Python 3.11, about 2,000 lines across `market/`, `agents/`, `comms/`, `llm/`, `experiments/`, `analysis/`,
  `dashboard/` and `tests/`. 24 unit and end-to-end tests (market, agents, runner, analysis pipeline) run without a model.
- LLM backends: local open-weight model through Ollama (qwen2.5:3b, used for all reported results because of
  budget), the Claude API (implemented, not used for results) and the mock backend.
- Each run writes its config, market, every order (with the agent's reasoning), trades, bus messages, analyst
  history, LLM usage and metrics to `results/<experiment>/seed_<k>/`.
- A Streamlit dashboard replays any logged run step by step (prices, each round's decisions, messages) without
  calling a model, so the demo cannot fail on the network.

---

## 3. Evaluation

### 3.1 Markets ("dataset")

| Market | Traders | Competitive equilibrium | Purpose |
|---|---|---|---|
| Symmetric (hand-built) | 5 buyers × 3 units, 5 sellers × 3 units | Q\* = 11, P\* = 100, max surplus 600 | main condition |
| Shock | same as symmetric, all values/costs +30 from period 3 | P\* = 100, then 130 | adaptation to a regime change |
| Asymmetric | flat demand, steep supply | Q\* = 10, P\* = 145, max surplus 887 | bias toward a "fair" midpoint price |
| Random | values U[60,160], costs U[40,140], new market per seed | varies | generalization |

Because the competitive equilibrium is computed exactly (`market/equilibrium.py`), every run has ground
truth.

### 3.2 Metrics

- **Allocative efficiency**: realized surplus divided by maximum possible surplus (1.0 = every efficient unit
  traded and no inefficient one did).
- **Price RMSD**: root-mean-square deviation of trade prices from P\*; **Smith's α** = 100 × RMSD / P\* in the
  final period (convergence).
- **Convergence speed**: for each period, the first round from which every later trade is within ±10% of P\*
  (`converge_round`; a period that never settles counts as rounds + 1), the share of trades made after that
  point (`settled_share`), and the mean |price − P\*| in each round (`convergence_by_round.png`).
- **Share of trades inside the equilibrium price band**, **quantity ratio** (units traded / Q\*) and
  **extramarginal trades** (units that should not trade at P\*).
- **Buyers' share of surplus**, compared with the share they would get at P\*.
- **Agent rationality**: budget-violation (clip) rate, zero-profit orders and invalid/error rate, with
  per-category reasoning excerpts (`analysis/excerpts.py`).
- **Cost**: LLM calls, tokens and wall-clock time per run.

### 3.3 Baselines and conditions

- **ZI-C / ZI-U**: random traders with and without the budget constraint.
- **Oracle**: the exact equilibrium price (upper bound).
- **Centralized LLM**: the same model (qwen2.5:3b) sees every trader's private values and costs and sets one
  clearing price per period; all units that want to trade at that price trade. 5 seeds, response cache off, so
  each seed is an independent sample.
- **Ablations** of the coordination mechanisms: `no_analyst` (no consensus broadcast), `no_comms` (no analyst,
  no memory, no chat; agents interact only through the order book).

**Protocol.** Model qwen2.5:3b through Ollama on an 8 GB MacBook Air. Main comparison: 3 periods × 6 rounds,
seeds 0–2 for LLM conditions, seeds 0–9 for baselines (they are free). Earlier prompt-development runs used
10 rounds per period and are reported separately in 3.5 because session length changes efficiency (ZI-C: 0.889
at 10 rounds vs 0.773 at 6).

### 3.4 Main results (6 rounds per period, symmetric market)

| Condition | Seeds | Efficiency | Price RMSD | Buyers' share (P\* share 0.483) |
|---|---|---|---|---|
| Oracle | 1 | 1.000 | 0.0 | 0.483 |
| Centralized LLM (full information) | 5 | 0.926 ± 0.016 | 15.3 | 0.282 |
| ZI-C | 10 | 0.773 ± 0.027 | 22.3 ± 2.5 | 0.502 ± 0.043 |
| ZI-U | 10 | 0.850 ± 0.022 | 56.7 ± 2.5 | 0.470 ± 0.145 |
| LLM full (analyst + memory) | 3 | **0.945 ± 0.029** | 29.4 ± 1.3 | 0.430 ± 0.063 |
| LLM, no analyst | 3 | 0.888 ± 0.062 | 30.1 ± 2.2 | 0.597 ± 0.025 |
| LLM, no communication | 3 | 0.865 ± 0.067 | 33.1 ± 4.3 | 0.637 ± 0.059 |

± is a 95% confidence interval over seeds (normal approximation; with only 3 seeds a t-based interval would be
about twice as wide for the LLM rows). Per-seed efficiency: LLM full 0.922 / 0.942 / 0.972; no analyst
0.917 / 0.825 / 0.922; no communication 0.931 / 0.847 / 0.817. Shock market: ZI-C 0.748 ± 0.032, LLM full
0.934 ± 0.053 (0.981 / 0.936 / 0.886).

| Behaviour (share of decisions, 3 seeds pooled) | LLM full | No analyst | No comms |
|---|---|---|---|
| Would have traded at a loss (clipped) | 13.8% | 5.3% | 5.0% |
| Priced at exactly own value/cost | 10.3% | 12.0% | 14.9% |
| Anchored on the analyst's estimate | 17.0% | n/a | n/a |
| Accepted the opposite quote at a profit | 12.4% | 10.7% | 10.1% |

Figures: `efficiency_by_condition.png`, `efficiency_by_period.png`, `rmsd_by_condition.png`,
`surplus_split.png`, `price_paths_*.png`.

Every LLM condition beats ZI-C at the same session length (0.865–0.945 vs 0.773), and every LLM seed beats
every ZI-C seed. Adding coordination raises efficiency step by step: no communication 0.865, belief sharing
without an analyst 0.888, full system 0.945. The full system is also the most stable: its lowest seed (0.922)
is above the mean of both ablations, and no period drops below 0.88, while both ablations have periods at
0.70–0.78. With 3 seeds the intervals still overlap, so the ordering is consistent but not statistically
established. The analyst also changes *who* gains: without it, buyers take about 60% of the surplus; with it,
the split (0.43) is closer to the competitive 0.48. One caveat cuts the other way: agents with the analyst
attempt nearly three times as many loss-making orders (13.8% vs about 5%), because they price toward the
consensus even when it lies beyond their own value or cost. The budget constraint clips these orders, so part of
the analyst's benefit depends on that safety net. Price RMSD is higher for all LLM conditions than for ZI-C
(about 30 vs 22), because LLM agents open each period with extreme quotes (41, 160) that sometimes trade.

**Convergence speed.** Efficiency and price convergence turn out to be different things here.

| Condition | Round at which prices settle (of 6; 7 = never) | Trades made after settling | Mean \|price − P\*\| in rounds 1–2 → 5–6 |
|---|---|---|---|
| ZI-C | 6.0 ± 0.6 | 10% | 20 → 12 |
| LLM, no communication | 6.2 ± 0.8 | 5% | 42 → 18 |
| LLM, no analyst | 6.3 ± 0.4 | 5% | 35 → 17 |
| LLM full (analyst + memory) | **5.6 ± 0.2** | **15%** | 34 → 14 |

No condition reliably converges within 6 rounds: most periods end before all trades are within 10% of P\*. LLM
traders start each period much further from equilibrium than random traders (opening quotes near 41 and 160),
then close most of the gap by round 3. The full system settles slightly earlier and three times as many of its
trades happen at near-equilibrium prices compared with the ablations, but 15% is still low. So the LLM market's
advantage over ZI-C is in *who trades* (efficiency), not in *price accuracy*. Longer sessions did not fix this: with 10 rounds per
period (3.5) prices clustered tightly, but around 88–90 rather than P\* = 100, so only 9% of trades counted as
settled. More rounds produced agreement, not accuracy.

**Small-market pilot** (TA recommendation). Same protocol on a much smaller market: one good, 3 buyers and
3 sellers with 2 units each (`market/configs/pilot.yaml`; Q\* = 4, P\* = 95–105, maximum surplus 255 per
period). Experiments: `experiments/run_pilot.sh`.

| Condition (6 traders, 6 rounds per period) | Seeds | Efficiency | Price RMSD | Buyers' share (P\* share 0.49) | Round at which prices settle |
|---|---|---|---|---|---|
| ZI-C | 10 | 0.824 ± 0.031 | 21.3 | 0.49 | 5.4 |
| LLM, no analyst | 1 (2 more running) | 0.961 | 24.6 | 0.46 | 2.7 |
| LLM full (analyst + memory) | 1 (2 more running) | 0.987 | 31.5 | 0.64 | 5.0 |

*Preliminary: one LLM seed per condition so far.* The pilot agrees with the 10-trader market on the main point:
LLM traders capture more of the gains than random traders (0.96–0.99 vs 0.82), with or without the analyst.
With one seed nothing can be said about the analyst's effect. On this seed the market without the analyst
settled on the fair price sooner, which is a reminder that the analyst's benefit is not guaranteed and has to be
checked across seeds. **[Update this paragraph when seeds 1–2 finish.]**

### 3.5 Effect of the prompt and protocol fixes (10 rounds per period, seed 0)

| | v0 | v1 | ZI-C (10 seeds) |
|---|---|---|---|
| Efficiency | 0.817 | **0.986** | 0.889 ± 0.014 |
| Efficiency by period | 0.92 / 0.96 / 0.57 | 0.98 / 1.00 / 0.97 | |
| Price RMSD | 24.1 | 22.8 | 21.0 |
| Trades (Q\* = 11 per period) | 26 | 32 | |
| Buyers' share of surplus (P\* share 0.483) | 0.520 | 0.621 | 0.481 ± 0.037 |
| Orders that would have lost money | 17.5% | 11.7% | n/a |
| Orders at exactly own value/cost | 12.0% | 5.5% | |
| Orders anchored on the analyst's estimate | 17.9% | 23.7% | |
| Wall time | 2.7 h | 3.9 h | seconds |

(Figure: `prompt_fix_before_after.png`.)

The fixes removed the period-3 collapse and raised efficiency above every ZI-C seed. They also made agents rely
more on the analyst: prices converged tightly, but to about 88–90 rather than P\* = 100, and buyers captured
62% of the surplus instead of 48%. The analyst's consensus became self-fulfilling, so the market coordinated on
*a* price rather than on *the* competitive price. This is a single seed, so the comparison is suggestive, not
statistically established.

### 3.6 Centralized vs decentralized

The centralized planner sees everything the market as a whole knows, so it could in principle compute P\* = 100
exactly. Instead it chose 115 in 13 of 15 periods (100 once, 120 twice), reaching 0.926 ± 0.016 efficiency and
handing most of the surplus to sellers (buyers' share 0.28 against 0.48 at P\*). Its explanations state that 115
"maximizes total surplus" while the sums it writes out are wrong. The decentralized market, in which no agent
sees more than its own units, did better (0.986 in v1). The task the single model fails at, aggregating 30
private numbers into one price, is done implicitly by the trading process and the analyst. This is the clearest
evidence in the project that splitting the problem across agents helps. Caveat: the planner's efficiency does
not depend on session length, while the v1 comparison is one seed at 10 rounds; at 6 rounds per period the decentralized
market (0.945 ± 0.029, 3 seeds) still beats the planner (0.926 ± 0.016), but the intervals overlap, so the
claim is "at least as good, with no agent seeing the whole market", not "clearly better".

### 3.7 Qualitative observations

From `report/excerpts/`:

- Agents often cite the analyst's estimate and price within a few units of it, even when their own value
  implies a very different price.
- Reasoning text is frequently inconsistent with the numbers in the prompt (it quotes an analyst estimate of
  88.08 when the broadcast was 88.02, or calls a zero-profit order "maximizing profit").
- Some apparently irrational bids (bid = own value) still earned a profit, because the CDA fills at the
  standing ask. Rules that protect agents can hide poor reasoning.

### 3.8 Threats to validity

- Small model (3B parameters); results may not transfer to stronger models.
- Few seeds for LLM conditions (3) because each run takes 1–4 hours on the available hardware.
- Shorter sessions (6 rounds) disadvantage every condition; all comparisons in 3.4 use the same length.
- The rule-based budget constraint prevents losses, so efficiency partly reflects the mechanism, not the
  agents. The clip rate reports how often it intervened.
