"""Google Finance transport egress (2026-11-11): calls leave from the
server's own IP; a refused thread steps to the gateway exit
(config.GOOGLE_FINANCE_FALLBACK_EXIT), and only when that is refused too to
the residential exit (config.GOOGLE_FINANCE_FALLBACK_PROXY_COUNTRY); the box
browser comes last and never rides the gateway. Offline, no network.

    python -m pytest google_finance/test_fetch.py -q
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from google_finance import fetch as F  # noqa: E402
from scraper_utils.testing import hosted_only

RESI = "http://resi-us:1"
BODY = ")]}'\n[[\"wrb.fr\",\"x\",\"[1]\",null,null,null,\"1\"]]"


class Resp:
    def __init__(self, status):
        self.status_code, self.text, self.url = status, BODY, "https://www.google.com/finance/beta/x"


class Session:
    """What egress.new_session() hands out, answering per exit from `plan`
    (exit -> a status, or an exception to raise)."""

    def __init__(self, exit, plan, seen):
        self.exit, self.plan, self.seen = exit, plan, seen

    def post(self, url, **kwargs):
        self.seen.append(self.exit)
        answer = self.plan[self.exit]
        answer = answer.pop(0) if isinstance(answer, list) else answer
        if isinstance(answer, Exception):
            raise answer
        return Resp(answer)

    def close(self):
        pass


@pytest.fixture
def ladder(monkeypatch):
    """(plan, seen): the exits' answers and the exit of every request sent."""
    plan, seen = {}, []
    for name, value in (("proxy_until", 0), ("step", 0), ("past_gateway", False), ("session", None)):
        monkeypatch.setattr(F._local, name, value, raising=False)
    monkeypatch.setattr(F.egress, "new_session", lambda exit=None, impersonate=None: Session(exit, plan, seen))
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    monkeypatch.setattr(F, "_box_fetch", lambda *a: seen.append("box") or BODY)
    monkeypatch.setattr(config, "residential_proxy", lambda c, states=None: f"http://resi-{c}:1")
    monkeypatch.setattr(config, "GOOGLE_FINANCE_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(config, "GOOGLE_FINANCE_BROWSER_FALLBACK", True)
    monkeypatch.setattr(config, "GOOGLE_FINANCE_PROXY_COUNTRY", None)
    monkeypatch.setattr(config, "GOOGLE_FINANCE_FALLBACK_EXIT", "gateway")
    monkeypatch.setattr(config, "GOOGLE_FINANCE_FALLBACK_PROXY_COUNTRY", "us")
    return plan, seen


def post():
    return F._post("/finance/beta/_/FinHubUi/data/batchexecute?rpcids=x", "f.req=x", "t")


@hosted_only
def test_default_is_own_ip_then_the_gateway_then_residential():
    assert config.GOOGLE_FINANCE_PROXY_COUNTRY is None
    assert config.GOOGLE_FINANCE_FALLBACK_EXIT == "gateway"
    assert config.GOOGLE_FINANCE_FALLBACK_PROXY_COUNTRY == "us"


@hosted_only
def test_fallback_steps(ladder, monkeypatch):
    assert config.google_finance_proxy() is None
    assert [config.google_finance_step_proxy(step) for step in (1, 2, 3)] == ["gateway", RESI, RESI]
    assert config.google_finance_fallback_proxy() == RESI           # the box browser's exit: never the gateway
    monkeypatch.setattr(config, "GOOGLE_FINANCE_FALLBACK_EXIT", None)    # the ladder before the gateway
    assert config.google_finance_fallback_exits() == ["us"] and config.google_finance_step_proxy(1) == RESI
    monkeypatch.setattr(config, "GOOGLE_FINANCE_FALLBACK_PROXY_COUNTRY", None)
    assert config.google_finance_step_proxy(1) is None
    monkeypatch.setattr(config, "GOOGLE_FINANCE_FALLBACK_EXIT", "gateway")
    assert [config.google_finance_step_proxy(step) for step in (1, 2)] == ["gateway", "gateway"]
    assert config.google_finance_fallback_proxy() is None
    monkeypatch.setattr(config, "GOOGLE_FINANCE_PROXY_COUNTRY", "gateway")
    assert config.google_finance_proxy() == "gateway"


@hosted_only
def test_a_refused_own_ip_costs_gateway_requests_not_residential(ladder):
    plan, seen = ladder
    plan.update({None: 429, "gateway": 200})
    assert post() == BODY
    assert seen == [None, "gateway"]
    post()                                                  # the thread stays on the gateway for the cooldown
    assert seen == [None, "gateway", "gateway"]
    F._local.proxy_until = time.time() - 1                  # cooldown over: the own IP again
    plan[None] = 200
    post()
    assert seen[-1] is None


@hosted_only
def test_a_refused_gateway_steps_on_to_residential_then_the_box(ladder):
    plan, seen = ladder
    plan.update({None: 429, "gateway": 403, RESI: 200})
    assert post() == BODY
    assert seen == [None, "gateway", RESI]
    post()
    assert seen == [None, "gateway", RESI, RESI] and F._step() == 2
    for name in ("proxy_until", "step"):
        setattr(F._local, name, 0)
    del seen[:]
    plan[RESI] = 403                                        # every exit refused: the box browser replays the call
    assert post() == BODY
    assert seen == [None, "gateway", RESI, "box"]


@hosted_only
def test_last_attempt_of_a_call_the_gateway_keeps_failing_rides_residential(ladder):
    plan, seen = ladder
    plan.update({None: 403, "gateway": 200, RESI: 200})
    post()                                                  # the thread is on the gateway step now
    del seen[:]
    plan["gateway"] = [RuntimeError("GatewayError: gateway 504"), 502, 200]
    assert post() == BODY
    assert seen == ["gateway", "gateway", RESI]
    assert post() == BODY                                   # for that call only: no cooldown on the paid exit
    assert seen == ["gateway", "gateway", RESI, "gateway"] and F._step() == 1
    plan.update({"gateway": [RuntimeError("GatewayError: gateway 504"), 502, 200], RESI: 403})
    with pytest.raises(Exception):
        post()                                              # the borrowed exit refused: no verdict on the gateway
    assert post() == BODY and seen[-1] == "gateway" and F._step() == 1


@hosted_only
def test_without_the_gateway_step_a_refusal_goes_straight_to_residential(ladder, monkeypatch):
    plan, seen = ladder
    monkeypatch.setattr(config, "GOOGLE_FINANCE_FALLBACK_EXIT", None)
    plan.update({None: 403, RESI: [RuntimeError("reset"), 200]})
    assert post() == BODY
    assert seen == [None, RESI, RESI]                       # the ladder it always had
    monkeypatch.setattr(config, "GOOGLE_FINANCE_FALLBACK_PROXY_COUNTRY", None)
    for name in ("proxy_until", "step"):
        setattr(F._local, name, 0)
    F._drop_session()
    del seen[:]
    plan[None] = [403, 200]
    assert post() == BODY                                   # no fallback at all: just a rebuilt session
    assert seen == [None, None] and F._step() == 0


@hosted_only
def test_a_pinned_exit_still_carries_every_call(ladder, monkeypatch):
    plan, seen = ladder
    monkeypatch.setattr(config, "GOOGLE_FINANCE_PROXY_COUNTRY", "gb")
    plan.update({"http://resi-gb:1": [403, 200]})
    assert post() == BODY
    assert seen == ["http://resi-gb:1", "http://resi-gb:1"]
    monkeypatch.setattr(config, "GOOGLE_FINANCE_PROXY_COUNTRY", "gateway")     # every call through the gateway
    F._drop_session()
    plan["gateway"] = 200
    post()
    assert seen[-1] == "gateway"
