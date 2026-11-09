# market-sim: multi-agent LLM traders in a double auction

CMPSC 448 final project. LLM trader agents with private information trade in a continuous double auction.
An analyst agent coordinates them by aggregating their (disagreeing) price beliefs into a consensus signal.
We measure whether this decentralized multi-agent system reaches the competitive equilibrium, and compare it
against non-LLM traders and against a single centralized LLM that sees everything.

## Why multi-agent?
Markets are multi-agent by nature: information (each trader's values/costs) is **private and distributed**.
A single model can only solve the problem if someone hands it all the private information (the centralized
baseline). The interesting question is whether specialized agents that each see only their own slice can
coordinate, through prices and messages, to an outcome that is nearly as good, and at what cost.

## Layout
```
market/        order_book.py (CDA), auctioneer.py (round loop), config.py, equilibrium.py, configs/*.yaml
agents/        base.py (shared interface), llm_trader.py, zi_trader.py, analyst.py, centralized.py, personas.py
comms/         bus.py: message bus with channels analyst / beliefs / chat, all messages logged
llm/           client.py: Claude API wrapper, structured JSON output, disk cache, token + $ accounting, mock backend
experiments/   runner.py, configs/{baselines,main,ablations,robustness}/*.yaml
analysis/      metrics.py (efficiency, price RMSD, Smith's alpha, ...), plots.py (report figures)
dashboard/     app.py: Streamlit replay of logged runs (demo never makes live API calls)
tests/         order book, equilibrium, end-to-end runs, cache
results/       <experiment>/seed_<k>/{config.yaml, market.json, trades.jsonl, orders.jsonl, messages.jsonl,
               analyst.json, metrics.json, llm_usage.json}
report/        outline.md, figures/ (generated)
```

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest
```
LLM backends (pick one with `--backend`):
- `ollama` (free, local): install Ollama, then `ollama pull qwen2.5:3b`. Calls run one at a time by default
  (parallel calls are slower on an 8 GB laptop). A full run takes roughly 20–30 minutes.
- `anthropic` (Claude API, paid): `export ANTHROPIC_API_KEY=...`.
- `mock` (free, instant, not an LLM): for tests and pipeline checks only.

## Running
```bash
# Free dry run of every experiment (mock LLM policy). Use this to check the pipeline.
python -m experiments.runner --all experiments/configs --backend mock

# Real run of one condition on a free local model
python -m experiments.runner --config experiments/configs/main/llm_full.yaml --backend ollama --model qwen2.5:3b --seeds 0

# Same with the Claude API (paid)
python -m experiments.runner --config experiments/configs/main/llm_full.yaml --backend anthropic --model claude-haiku-5-5 --seeds 0

# Tables + figures
python -m analysis.metrics results          # prints mean ± 95% CI table, writes results/summary.csv
python -m analysis.plots                    # writes report/figures/*.png

# Demo
streamlit run dashboard/app.py
```
LLM responses are cached in `.llm_cache/`, so re-running a seed is free and reproducible.

> **Mock results are not findings.** The mock backend is a simple heuristic so tests and dry runs cost
> nothing. It ignores memory, chat and personas' prompts, so ablations look identical under mock.
> Every number in the report must come from `--backend anthropic` runs.

## Experimental conditions
| Group | Config | What it tests |
|---|---|---|
| Baselines | `zi_c`, `zi_u` | Zero-intelligence traders (Gode & Sunder 1993), with/without budget constraint |
| | `centralized_oracle` | Exact equilibrium; upper bound |
| | `centralized_llm` | One LLM sees all private info and sets a single clearing price |
| Main | `llm_full` | LLM traders + analyst + memory |
| Ablations | `no_analyst`, `no_memory`, `no_comms` | Value of each coordination mechanism |
| | `analyst_llm` | Rule-based vs LLM analyst for resolving disagreement |
| | `chat` | Public cheap talk between traders (look for collusion/signalling) |
| | `personas_mixed` | Heterogeneous trader styles |
| | `mixed_population` | Half LLM, half ZI-C: who captures surplus? |
| Robustness | `shock`, `asymmetric`, `random_markets` | Regime change, lopsided surplus, unseen markets |

## Metrics
Allocative efficiency, price RMSD from P*, Smith's alpha (final period), share of trades inside the
equilibrium price band, quantity ratio, extramarginal trades, budget-violation (clip) rate, LLM error rate,
LLM calls / tokens / USD per run. See `analysis/metrics.py`.

## Budget
With defaults (10 traders, 3 periods × 10 rounds, Opus 5.5 at low effort) a run makes up to ~300 trader calls
(+30 if the analyst is an LLM). Check `results/<exp>/seed_<k>/llm_usage.json` after the first real run and
scale seeds accordingly; try `--model claude-haiku-5-5` while iterating on prompts.
