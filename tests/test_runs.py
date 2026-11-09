"""End-to-end runs with the free mock backend: checks wiring, logging and metric sanity."""
import json

import pytest

from experiments.runner import load_experiment, run_one


def _run(path, tmp_path, seed=0, **over):
    exp = load_experiment(path)
    exp.setdefault("llm", {})["backend"] = "mock"
    exp.update(over)
    return run_one(exp, seed, tmp_path), tmp_path / exp["name"] / f"seed_{seed}"


def test_zi_c_never_trades_at_a_loss_and_is_efficient(tmp_path):
    effs = []
    for seed in range(5):
        m, d = _run("experiments/configs/baselines/zi_c.yaml", tmp_path, seed)
        trades = [json.loads(l) for l in open(d / "trades.jsonl")]
        assert all(t["buyer_value"] >= t["price"] >= t["seller_cost"] for t in trades)
        effs.append(m["efficiency"])
    assert sum(effs) / len(effs) > 0.75   # Gode & Sunder: ZI-C markets are highly efficient


def test_oracle_is_fully_efficient(tmp_path):
    m, _ = _run("experiments/configs/baselines/centralized_oracle.yaml", tmp_path)
    assert m["efficiency"] == pytest.approx(1.0)
    assert m["price_rmsd"] == pytest.approx(0.0)


def test_llm_full_mock_writes_all_logs(tmp_path):
    m, d = _run("experiments/configs/main/llm_full.yaml", tmp_path)
    for f in ("config.yaml", "trades.jsonl", "orders.jsonl", "messages.jsonl", "analyst.json",
              "metrics.json", "llm_usage.json", "market.json"):
        assert (d / f).exists(), f
    msgs = [json.loads(l) for l in open(d / "messages.jsonl")]
    assert {"analyst", "beliefs"} <= {x["channel"] for x in msgs}
    assert m["llm_calls"] > 0 and 0 < m["efficiency"] <= 1.0


def test_no_analyst_ablation_has_no_analyst_messages(tmp_path):
    _, d = _run("experiments/configs/ablations/no_analyst.yaml", tmp_path)
    msgs = [json.loads(l) for l in open(d / "messages.jsonl")]
    assert all(x["channel"] != "analyst" for x in msgs)


def test_mixed_population_has_both_kinds(tmp_path):
    _, d = _run("experiments/configs/ablations/mixed_population.yaml", tmp_path)
    kinds = {json.loads(l)["kind"] for l in open(d / "orders.jsonl")}
    assert {"llm", "zi_c"} <= kinds


def test_runs_are_reproducible(tmp_path):
    a, _ = _run("experiments/configs/main/llm_full.yaml", tmp_path / "a", seed=3)
    b, _ = _run("experiments/configs/main/llm_full.yaml", tmp_path / "b", seed=3)
    assert a["efficiency"] == b["efficiency"] and a["n_trades"] == b["n_trades"]
