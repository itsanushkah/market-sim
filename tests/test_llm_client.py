from llm.client import LLMClient, LLMSettings


def test_cache_roundtrip(tmp_path):
    c = LLMClient(LLMSettings(backend="mock", cache_dir=str(tmp_path)))
    k = c._key("sys", "user", {"type": "object"})
    assert c._cache_get(k) is None
    c._cache_put(k, {"a": 1})
    assert c._cache_get(k) == {"a": 1}
    assert k != c._key("sys", "user2", {"type": "object"})


def test_mock_backend_counts_calls(tmp_path):
    c = LLMClient(LLMSettings(backend="mock", cache_dir=str(tmp_path)))
    out = c.complete_json(agent_id="B0", system="s", user="u", schema={}, mock_fn=lambda: {"x": 1})
    assert out == {"x": 1}
    assert c.usage.calls == 1 and c.usage.by_agent["B0"]["calls"] == 1


def test_lenient_parse_recovers_truncated_reasoning():
    from llm.client import parse_json_lenient
    schema = {"required": ["action", "price", "reasoning"]}
    cut = '{"action": "bid", "price": 95, "reasoning": "Given the recent trades and the analys'
    out = parse_json_lenient(cut, schema)
    assert out["action"] == "bid" and out["price"] == 95 and out["_truncated"]
    assert parse_json_lenient('{"action": "bid", "pri', schema) is None   # required fields missing
