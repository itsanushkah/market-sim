"""Pull representative agent reasoning out of a run's logs, grouped by behaviour, for the report.

    python -m analysis.excerpts results/llm_full_qwen3b_v1/seed_0      # writes report/excerpts/<exp>_seed<k>.md

Categories
- loss_attempt:  order would have traded at a loss (clipped by the budget constraint)
- zero_profit:   priced exactly at own value/cost
- analyst_anchor: reasoning cites the analyst/consensus and the price sits within 3 of the analyst estimate
- good_accept:   accepted the opposite quote at a profit (the textbook move)
- invalid:       LLM error, invalid action or a filtered belief
Plus the analyst's broadcast at the end of each period.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

N_PER_CATEGORY = 4


def classify(o: dict, est: float | None) -> list[str]:
    cats = []
    if o.get("error") or o.get("invalid_action") or "invalid_belief" in o:
        cats.append("invalid")
    if o["action"] == "pass" or o.get("raw_price") is None or o.get("unit") is None:
        return cats
    p, u, why = o["raw_price"], o["unit"], (o.get("reasoning") or "").lower()
    if o.get("clipped"):
        cats.append("loss_attempt")
    elif abs(p - u) < 0.01:
        cats.append("zero_profit")
    if est is not None and abs(p - est) <= 3 and ("analyst" in why or "consensus" in why):
        cats.append("analyst_anchor")
    if o.get("traded") and not o.get("clipped") and ((o["role"] == "buyer" and p < u) or (o["role"] == "seller" and p > u)):
        cats.append("good_accept")
    return cats


def main(run: Path, out_dir: Path = Path("report/excerpts"), seed: int = 0) -> Path:
    orders = [json.loads(l) for l in open(run / "orders.jsonl")]
    analyst = json.loads((run / "analyst.json").read_text())
    msgs = [json.loads(l) for l in open(run / "messages.jsonl")]
    est_at = {(a["period"], a["round"]): a.get("estimate") for a in analyst}

    buckets: dict[str, list[dict]] = {}
    for o in orders:
        prev = est_at.get((o["period"], o["round"] - 1)) if o["round"] > 0 else est_at.get((o["period"] - 1, 9))
        for c in classify(o, prev):
            buckets.setdefault(c, []).append(dict(o, analyst_estimate=prev))

    rng = random.Random(seed)
    m = json.loads((run / "metrics.json").read_text())
    lines = [f"# Reasoning excerpts: {m['experiment']} (seed {m['seed']}, backend {m.get('backend')})", "",
             f"Efficiency {m['efficiency']:.3f}, price RMSD {m['price_rmsd']:.1f}, {len(orders)} decisions.", "",
             "| category | count | share of decisions |", "|---|---|---|"]
    for c in ("loss_attempt", "zero_profit", "analyst_anchor", "good_accept", "invalid"):
        n = len(buckets.get(c, []))
        lines.append(f"| {c} | {n} | {n / len(orders):.1%} |")
    for c, items in buckets.items():
        lines += ["", f"## {c}", ""]
        for o in rng.sample(items, min(N_PER_CATEGORY, len(items))):
            what = "value" if o["role"] == "buyer" else "cost"
            lines.append(f"- P{o['period'] + 1} R{o['round'] + 1} {o['agent_id']} ({o['role']}, {what} {o['unit']}): "
                         f"{o['action']} {o['raw_price']}, belief {o['belief']}, analyst said {o['analyst_estimate']}"
                         f"{', TRADED' if o.get('traded') else ''}  \n  > {o.get('reasoning', '').strip()}")
    lines += ["", "## Analyst broadcast at the end of each period", ""]
    for p in sorted({x["period"] for x in msgs}):
        last = [x for x in msgs if x["channel"] == "analyst" and x["period"] == p]
        if last:
            lines.append(f"- Period {p + 1}: {last[-1]['content']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{m['experiment']}_seed{m['seed']}.md"
    out.write_text("\n".join(lines) + "\n")
    return out


if __name__ == "__main__":
    for arg in sys.argv[1:] or ["results/llm_full_qwen3b_v1/seed_0"]:
        print("wrote", main(Path(arg)))
