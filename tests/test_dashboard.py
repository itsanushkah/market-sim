"""Smoke test of the dashboard, including a live run with the mock backend (no model needed)."""
from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def test_live_tab_runs_end_to_end(monkeypatch):
    monkeypatch.setenv("MARKET_SIM_LIVE_BACKEND", "mock")
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py"), default_timeout=60).run()
    assert not at.exception
    rounds = next(n for n in at.number_input if n.label == "Rounds per period")
    rounds.set_value(2)
    next(b for b in at.button if b.label == "Start live run").click().run()
    assert not at.exception and not at.error
    assert any(s.value.startswith("Finished") for s in at.success)
    labels = {m.label for m in at.metric}
    assert {"Trades so far", "Gains captured", "AI decisions made"} <= labels
    assert any("secret" in m.value for m in at.markdown)  # the decision feed showed agent decisions
