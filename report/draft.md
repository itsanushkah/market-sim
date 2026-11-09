# Report draft: design and evaluation sections

> Working draft. Numbers marked **[TBD]** come from the overnight runs (`experiments/run_laptop_plan.sh`) and
> must be filled in from `results/summary.csv` before submission. Everything else reflects the code as of
> commit `adf2c70`. Rewrite in your own voice; sections 1 (problem) and 4 (lessons) are not drafted here.

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
  `dashboard/` and `tests/`. 19 unit and end-to-end tests run on the mock backend.
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
| LLM full (analyst + memory) | 3 | **[TBD]** | **[TBD]** | **[TBD]** |
| LLM, no analyst | 3 | **[TBD]** | **[TBD]** | **[TBD]** |
| LLM, no communication | 3 | **[TBD]** | **[TBD]** | **[TBD]** |

± is a 95% confidence interval over seeds. Shock market: ZI-C 0.748 ± 0.032, LLM full **[TBD]**.

Figures: `efficiency_by_condition.png`, `efficiency_by_period.png`, `rmsd_by_condition.png`,
`surplus_split.png`, `price_paths_*.png`.

**[TBD: 3–4 sentences interpreting the table once filled: does the analyst help compared with no_analyst and
no_comms? Do LLM agents beat ZI-C at equal session length?]**

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
not depend on session length, while the v1 comparison is one seed at 10 rounds; **[TBD: compare with LLM full at
6 rounds once available]**.

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
