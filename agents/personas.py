"""Trader personas: heterogeneous behavioural styles injected into the LLM system prompt.

`margin` is only used by the mock policy, to give personas distinct behaviour in offline runs.
"""

PERSONAS = {
    "neutral": {
        "prompt": "You are a rational, profit-maximising trader.",
        "margin": 0.10,
    },
    "cautious": {
        "prompt": "You are a cautious trader. You prefer a smaller sure profit over waiting for a better price, "
                  "and you dislike ending a period with untraded units.",
        "margin": 0.05,
    },
    "aggressive": {
        "prompt": "You are an aggressive, hard-bargaining trader. You open far from your limit and concede slowly, "
                  "accepting the risk of not trading.",
        "margin": 0.25,
    },
    "trend_follower": {
        "prompt": "You are a momentum trader. You pay close attention to the direction of recent trade prices "
                  "and expect recent trends to continue.",
        "margin": 0.12,
    },
}


def assign_personas(agent_ids: list[str], spec: str | list[str] | dict, rng) -> dict[str, str]:
    """spec: a single persona name, a list to cycle through, or {"mix": [...]} to sample randomly."""
    if isinstance(spec, str):
        return {a: spec for a in agent_ids}
    if isinstance(spec, list):
        return {a: spec[i % len(spec)] for i, a in enumerate(agent_ids)}
    if isinstance(spec, dict) and "mix" in spec:
        return {a: str(rng.choice(spec["mix"])) for a in agent_ids}
    raise ValueError(f"bad persona spec: {spec!r}")
