"""Smoke tests for the report pipeline: metrics, mock filtering, recompute, excerpts, plots, diagram."""
import json

import pytest

from analysis import excerpts, plots, recompute
from analysis.diagram import main as draw_diagram
from analysis.metrics import compute_run_metrics, load_all, summarize
from experiments.runner import load_experiment, run_one
from market.config import load_market


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    """Two tiny real-looking runs (ZI-C, backend 'none') and one mock LLM run."""
    root = tmp_path_factory.mktemp("results")
    for seed in (0, 1):
        run_one(load_experiment("experiments/configs/baselines/zi_c.yaml"), seed, root)
    exp = load_experiment("experiments/configs/main/llm_full.yaml")
    exp["llm"]["backend"] = "mock"
    run_one(exp, 0, root)
    return root


def test_surplus_split_at_equilibrium_price():
    cfg = load_market("market/configs/symmetric.yaml")
    # Every efficient unit trades at P* = 100: buyer share must equal the CE share.
    from market.equilibrium import demand_supply
    d, s = demand_supply(cfg)
    trades = [{"price": 100.0, "period": 0, "buyer_value": d[i], "seller_cost": s[i], "surplus": d[i] - s[i]}
              for i in range(11)]
    m = compute_run_metrics(cfg, 1, trades, [], {})
    assert m["efficiency"] == pytest.approx(1.0)
    assert m["buyer_share"] == pytest.approx(m["buyer_share_ce"])
    assert m["price_in_band"] == 1.0


def test_mock_runs_excluded_by_default(results):
    assert "llm_full" not in load_all(results)
    assert "llm_full" in load_all(results, include_mock=True)
    names = {r["experiment"] for r in summarize(results)}
    assert names == {"baseline_zi_c"}


def test_recompute_preserves_identity_fields(results):
    run = results / "baseline_zi_c" / "seed_0"
    before = json.loads((run / "metrics.json").read_text())
    recompute.recompute(run)
    after = json.loads((run / "metrics.json").read_text())
    for k in ("experiment", "seed", "backend", "efficiency", "n_trades"):
        assert after[k] == before[k]


def test_excerpts_written(results, tmp_path):
    out = excerpts.main(results / "llm_full" / "seed_0", out_dir=tmp_path)
    text = out.read_text()
    assert "| category | count |" in text and "Analyst broadcast" in text


def test_plots_and_diagram_render(results, tmp_path):
    rows = summarize(results)
    plots.plot_bars(rows, "efficiency", "efficiency", tmp_path / "eff.png", ref=1.0)
    plots.plot_surplus_split(rows, tmp_path / "split.png")
    plots.plot_price_path(results / "baseline_zi_c" / "seed_0", tmp_path / "path.png")
    draw_diagram(tmp_path / "arch.png")
    for f in ("eff.png", "split.png", "path.png", "arch.png"):
        assert (tmp_path / f).stat().st_size > 1000
