import asyncio

import pytest

from src.llm import orchestrator as o
from src.llm.chunker import truncate_to_budget
from src.llm.grounding import validate_product

SRC = "Acme Notes is great. Acme Notes Pro costs $8 per month."


def test_chunker_keeps_pricing_and_respects_budget():
    filler = "\n".join(f"Random paragraph number {i} about nothing in particular." for i in range(500))
    text = "Intro line about the company.\n" + filler + "\nPricing: the Pro plan costs $20 per month.\n"
    out = truncate_to_budget(text, 200)
    assert len(out) <= 800
    assert "Pro plan costs $20" in out


def test_grounding_accepts_real_values():
    clean, reason = validate_product(
        {"product_name": "Acme Notes", "pricing_model": "PAID",
         "pricing_evidence": "Acme Notes Pro costs $8 per month."}, SRC)
    assert reason is None and clean["pricing_model"] == "PAID"


def test_grounding_rejects_invented_product():
    clean, reason = validate_product({"product_name": "Zeta Cloud", "pricing_model": None}, SRC)
    assert clean is None and reason == "product_name_not_in_source"


def test_grounding_drops_unsupported_pricing():
    clean, _ = validate_product(
        {"product_name": "Acme Notes", "pricing_model": "ENTERPRISE",
         "pricing_evidence": "Contact our enterprise sales team."}, SRC)
    assert clean["product_name"] == "Acme Notes" and clean["pricing_model"] is None


class Fake(o.LLMOrchestrator):
    def __init__(self, behaviors: dict, **kw):
        provs = [o.Provider(n, "openai", "x", "m", "k", 1000) for n in behaviors]
        super().__init__(providers=provs, base_delay=0, max_delay=0, **kw)
        self.behaviors, self.calls = behaviors, []

    async def _call(self, p, system, user):
        self.calls.append((p.name, len(user)))
        return self.behaviors[p.name](user)


def _raise(exc):
    def f(_):
        raise exc
    return f


def run(llm, text="some text\n" * 50):
    return asyncio.run(llm.extract(text, "sys", lambda t: t))


def test_falls_back_after_429s():
    llm = Fake({"a": _raise(o.Retryable(429)), "b": lambda u: '{"ok": true}'}, max_retries=1)
    res = run(llm)
    assert res.provider == "b" and res.data == {"ok": True}
    assert [c[0] for c in llm.calls].count("a") == 2


def test_shrinks_payload_on_413():
    def a(user):
        if len(user) > 1500:
            raise o.PayloadTooLarge()
        return '{"ok": true}'
    text = "\n".join(f"Line {i} of filler content for the page." for i in range(2000))
    llm = Fake({"a": a})
    res = run(llm, text)
    assert res.provider == "a" and len(res.text_sent) <= 1000


def test_bad_json_moves_to_next_provider():
    llm = Fake({"a": lambda u: "not json at all", "b": lambda u: '{"ok": 1}'})
    assert run(llm).provider == "b"


def test_all_fail_raises():
    llm = Fake({"a": _raise(o.ProviderError("x")), "b": _raise(o.ProviderError("y"))})
    with pytest.raises(o.AllProvidersFailed):
        run(llm)