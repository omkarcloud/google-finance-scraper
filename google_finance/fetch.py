"""Google Finance transport: the page's own batchexecute endpoint over plain
curl_cffi (validated 2026-09-26, direct Indian egress, no cookies).

    POST https://www.google.com/finance/beta/_/FinHubUi/data/batchexecute
         ?rpcids=<id,id,…>&hl=<language>&gl=<country>
    body f.req=[[["<rpcid>","<json args>",null,"<tag>"], …]]
    ->   )]}'\n\n[["wrb.fr","<rpcid>","<json data>",null,null,<error>,"<tag>"], …]

No `at` token, no f.sid / bl, no cookies, no x-same-domain are needed; a
POST carries several rpcs (each echoes its tag at [6], so replies are
matched by tag, not order). Every page of the site is a thin shell over
these rpcs (the page's AF_dataServiceRequests map names them), so this
module is the whole transport.

Escalation per call (config.GOOGLE_FINANCE_*):
  1. the thread's curl session (direct egress);
  2. a thread whose call was refused (403 / 429 / /sorry) moves one
     fallback step down for GOOGLE_FINANCE_DIRECT_COOLDOWN seconds: since
     2026-11-11 first to the shared gateway
     (GOOGLE_FINANCE_FALLBACK_EXIT = "gateway", exit_gateway.py: a fresh gateway
     address on nearly every request; the numbers are in config.py), and
     only when that is refused too to a residential exit
     (GOOGLE_FINANCE_FALLBACK_PROXY_COUNTRY). A call the gateway keeps
     failing without a refusal (the gateway's own errors) makes its last
     attempt on the residential exit;
  3. after GOOGLE_FINANCE_MAX_ATTEMPTS blocked attempts, one headful
     patchright Chrome loads /finance/beta and replays the POST as an
     in-page fetch (on a residential exit, never the gateway).

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  FinanceUpstreamError  transport failure / 5xx / unparseable body  -> 502
  FinanceBlocked        403 / 429 / captcha                         -> 502
  FinanceBadRequest     Google rejected the rpc arguments           -> 400
  FinanceNotFound       unknown symbol                              -> 404
"""
import json
import fastjson
import os
import sys
import threading
import time
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_client  # noqa: E402
import config  # noqa: E402
import egress  # noqa: E402
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError  # noqa: E402
from scraper_utils import debug, sessions

SITE = "https://www.google.com"
SITE_KEY = "google-finance"           # recipe name on the browser box
HOME = f"{SITE}/finance/beta"
BATCH_PATH = "/finance/beta/_/FinHubUi/data/batchexecute"
IMPERSONATE = "chrome"
TIMEOUT = 30
XSSI_PREFIX = ")]}'"
BLOCK_STATUSES = (403, 429)

HEADERS = {
    "accept": "*/*",
    "accept-language": egress.site_accept_language("google-finance"),
    "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    "origin": SITE,
    "referer": HOME,
    "x-same-domain": "1",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

# batchexecute error codes seen at wrb.fr[5]: [3] malformed arguments,
# [13] invalid value (bad window / exchange), [5] entity not found.
_ARG_ERRORS = {3, 13}
_NOT_FOUND_ERRORS = {5}


class FinanceUpstreamError(UpstreamError):
    """Transport failure, 5xx or an unparseable body — retryable."""


class FinanceBlocked(FinanceUpstreamError, Blocked):
    """403 / 429 / captcha — retryable on another exit."""


class FinanceBadRequest(BadRequest):
    """Google rejected the rpc arguments — never retried."""


class FinanceNotFound(NotFound):
    """Unknown symbol — never retried."""


class RpcError(Exception):
    """One rpc of a batch came back with an error code instead of data."""

    def __init__(self, rpcid, code):
        super().__init__(f"{rpcid} error {code}")
        self.rpcid = rpcid
        self.code = code


def dump_debug(name, text):
    """Write a raw body to $GOOGLE_FINANCE_DEBUG_DIR/<name>.txt."""
    debug.dump("GOOGLE_FINANCE_DEBUG_DIR", name, text, render=repr)


# ---- curl sessions -------------------------------------------------------------------------
# One session per worker thread (a curl handle must not be shared across
# threads; egress.new_session: curl_cffi, or the gateway exit's look-alike);
# it keeps its keep-alive connection for the thread's life. A thread whose
# direct egress got blocked moves down the fallback steps
# (config.google_finance_fallback_exits(): the gateway exit, then a
# residential exit) until `proxy_until`, then goes back to direct.
_local = threading.local()


def _gateway_step(step):
    """True when fallback step `step` is the gateway exit with another exit
    configured behind it."""
    exits = config.google_finance_fallback_exits()
    return 0 < step < len(exits) and bool(config.gateway_exit(exits[step - 1]))


def _step():
    """This thread's fallback step: 0 = the configured exit (the server's
    own IP), 1, 2 = config.google_finance_step_proxy(step) while its
    cooldown runs; one step past the gateway for the last attempt of a call
    the gateway keeps failing (_retry_fresh)."""
    step = getattr(_local, "step", 1) if getattr(_local, "proxy_until", 0) > time.time() else 0
    if getattr(_local, "past_gateway", False) and _gateway_step(step):
        step += 1
    return step


def _session():
    step = _step()
    sess = getattr(_local, "session", None)
    if sess is not None and getattr(sess, "_gf_step", 0) != step:
        _drop_session()
        sess = None
    if sess is None:
        proxy = config.google_finance_proxy() or (config.google_finance_step_proxy(step) if step else None)
        sess = egress.new_session(proxy, impersonate=IMPERSONATE)     # None, a proxy URL, or the gateway exit ("gateway")
        sess._gf_step = step
        _local.session = sess
    return sess


def _drop_session():
    sessions.drop(_local)


def _escalate():
    """This thread's exit was refused: move it one fallback step down for a
    while (own IP -> the gateway exit -> residential; on the last step it
    stays there on a fresh exit). None configured = just rebuild the session."""
    exits = config.google_finance_fallback_exits()
    if getattr(_local, "past_gateway", False):
        # the refused exit was the one borrowed behind the gateway for this
        # call's last attempt (_retry_fresh): no verdict on the gateway, the
        # thread keeps its own step and cooldown
        _drop_session()
        return
    step = min(_step() + 1, len(exits))
    if step:
        if any(config.gateway_exit(e) for e in exits):     # how often each step is refused is the number to watch
            print(f"google-finance: exit refused, thread on fallback step {step} ({exits[step - 1]}) "
                  f"for {config.GOOGLE_FINANCE_DIRECT_COOLDOWN} s")
        _local.step = step
        _local.proxy_until = time.time() + config.GOOGLE_FINANCE_DIRECT_COOLDOWN
    _drop_session()


def _retry_fresh(attempt, attempts):
    """A transport failure / 5xx, not a refusal: the retry rides a fresh
    session. While the thread is on the gateway exit step the LAST attempt of
    the call rides the next step (the residential exit), for that call only:
    the gateway's own errors (its throttle, its 29 s timeout) are no verdict
    on the exit, so they must not park the thread on the paid proxy."""
    if attempt + 1 == attempts and _gateway_step(_step()):
        _local.past_gateway = True
    _drop_session()


def _is_sorry(status, url, text):
    return "/sorry/" in (url or "") or (status in (200, 429) and "unusual traffic" in (text or "")[:6000])


def _classify(status, url, text, label):
    if status in BLOCK_STATUSES or _is_sorry(status, url, text):
        dump_debug(f"blocked_{label}", text)
        raise FinanceBlocked(f"HTTP {status} on {label}")
    if status == 400:
        raise FinanceBadRequest(f"{label}: Google rejected the request")
    if status != 200:
        raise FinanceUpstreamError(f"HTTP {status} on {label}")
    return text


def _curl_post(url, body, label):
    try:
        resp = _session().post(url, data=body, headers=HEADERS, timeout=TIMEOUT)
    except Exception as e:
        raise FinanceUpstreamError(f"{label}: request failed: {type(e).__name__}: {e}")
    return _classify(resp.status_code, str(resp.url or ""), resp.text or "", label)


# ---- browser fallback (on the browser box) ---------------------------------------------------

# One sticky US residential exit for the box's parked /finance/beta page; the
# token-less calls replay as in-page fetches there (recipes/google_finance.py).
# A refusal (403/429/sorry) burns the exit: the box closes that browser and
# the next fallback call starts on a fresh one. Chrome left GKE 2026-10-22.
# Sticky US residential exits per parked box browser (browser_client.ExitPool:
# the box keys its browser by the proxy URL; rotate only the exit a call
# failed on). INPAGE_BROWSER_SLOTS browsers are the share; the pool offers
# share x BROWSER_BURST_FACTOR candidates and the box picks an idle one or
# opens another while it has headroom (2026-11-04).
_EXITS = browser_client.ExitPool(SITE_KEY, lambda: config.google_finance_fallback_proxy(),
                                 size=lambda: config.INPAGE_BROWSER_SLOTS, burst=True)


def _box_fetch(method, url, headers, body, label):
    """Replay one blocked call on the box's parked page -> text (classified)."""
    try:
        _proxy, res = _EXITS.fetch_any(SITE_KEY, url=url, method=method, headers=headers or {}, body=body)
    except browser_client.BoxRefused as e:
        _EXITS.rotate(e.proxy)                   # only the exit the box was using
        raise FinanceBlocked(f"{label}: refused in the box browser: {e}") from e
    except browser_client.BoxUnavailable as e:
        raise FinanceUpstreamError(f"{label}: browser box unavailable: {e}") from e
    status = int(res.get("status") or 0)
    return _classify(status, res.get("final_url") or "", res.get("body") or "", label)


# ---- batchexecute ----------------------------------------------------------------------------

def _post(path_and_query, body, label):
    """One POST with the escalation ladder -> response text."""
    attempts = max(1, int(config.GOOGLE_FINANCE_MAX_ATTEMPTS))
    last, blocked_only = None, True
    _local.past_gateway = False       # a new call starts on the thread's own step again
    for attempt in range(1, attempts + 1):
        try:
            return _curl_post(SITE + path_and_query, body, label)
        except FinanceBadRequest:
            raise
        except FinanceBlocked as e:
            last = e
            _escalate()
        except FinanceUpstreamError as e:
            last, blocked_only = e, False
            _retry_fresh(attempt, attempts)
        if attempt < attempts:
            time.sleep(min(config.RETRY_BACKOFF * attempt, 4))
    if blocked_only and config.GOOGLE_FINANCE_BROWSER_FALLBACK:
        return _box_fetch("POST", SITE + path_and_query, HEADERS, body, label)
    raise last


def decode(text, label="batchexecute"):
    """A batchexecute body -> {tag: (rpcid, data | None, error code | None)}.
    Handles both the plain `)]}'` JSON form and the `rt=c` chunked form."""
    body = (text or "").lstrip()
    if body.startswith(XSSI_PREFIX):
        body = body[len(XSSI_PREFIX):]
    out = {}
    candidates = []
    try:
        candidates.append(fastjson.loads(body))
    except ValueError:
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("[["):
                try:
                    candidates.append(fastjson.loads(line))
                except ValueError:
                    continue
    for chunk in candidates:
        for item in chunk if isinstance(chunk, list) else []:
            if not (isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr"):
                continue
            rpcid, payload = item[1], item[2]
            tag = item[6] if len(item) > 6 else "generic"
            code = None
            if payload is None and len(item) > 5 and isinstance(item[5], list) and item[5]:
                code = item[5][0]
            data = None
            if isinstance(payload, str):
                try:
                    data = fastjson.loads(payload)
                except ValueError:
                    dump_debug(f"badjson_{label}_{rpcid}", payload)
                    code = code or "unparseable"
            out[str(tag)] = (rpcid, data, code)
    if not out:
        dump_debug(f"nodata_{label}", text)
        raise FinanceUpstreamError(f"{label}: no rpc payload in the response")
    return out


# The page's client-side rpcs come in A/B experiment pairs that answer
# identically (seen 2026-09-26 on consecutive page loads). An rpc id Google
# no longer knows turns the WHOLE POST into an HTTP 400, so batch() splits a
# failed POST, retries a failing id under its twin and remembers dead ids.
ALT_RPC_IDS = {"lP79gf": "Xs5i3b", "Z462t": "Iaiw6c", "AYGGC": "TNo8E", "elz5Ef": "wj5Bh", "wVr6Jc": "wKsYyb",
               "XB3kn": "RelbPe", "mKsvE": "XB3kn", "ADgT7b": "dlNq8b", "smi6ye": "gXxkFd", "c2u4wc": "AiCwsd",
               "Kcy68c": "XxQsbd"}
ALT_RPC_IDS.update({v: k for k, v in list(ALT_RPC_IDS.items()) if v not in ALT_RPC_IDS})
_dead_ids = set()


def _live_id(rpcid):
    alt = ALT_RPC_IDS.get(rpcid)
    return alt if rpcid in _dead_ids and alt and alt not in _dead_ids else rpcid


def _post_batch(calls, language, country, label):
    f_req = [[rpcid, json.dumps(args, separators=(",", ":")), None, str(i + 1)] for i, (rpcid, args) in enumerate(calls)]
    params = {"rpcids": ",".join(dict.fromkeys(c[0] for c in calls)), "hl": language or "en",
              "gl": (country or "US").upper()}
    body = urlencode({"f.req": json.dumps([f_req], separators=(",", ":"))})
    return decode(_post(f"{BATCH_PATH}?{urlencode(params)}", body, label), label)


def _replies(calls, language, country, label):
    """{tag: reply} for `calls`, surviving unknown rpc ids."""
    calls = [(_live_id(rpcid), args) for rpcid, args in calls]
    try:
        return _post_batch(calls, language, country, label)
    except FinanceBadRequest:
        if len(calls) > 1:
            out = {}
            for i, call in enumerate(calls):
                try:
                    one = _replies([call], language, country, label)
                    out[str(i + 1)] = next(iter(one.values()))
                except FinanceBadRequest:
                    out[str(i + 1)] = (call[0], None, "unknown rpc")
            return out
        rpcid, args = calls[0]
        _dead_ids.add(rpcid)
        alt = ALT_RPC_IDS.get(rpcid)
        if alt and alt not in _dead_ids:
            print(f"google-finance: rpc {rpcid} rejected, retrying as {alt}")
            return _replies([(alt, args)], language, country, label)
        raise


def batch(calls, *, language="en", country="US", label=None, strict=True):
    """Run several rpcs in ONE POST.

    calls: [(rpcid, args), …] -> [data, …] aligned with `calls`. An rpc that
    came back with an error code yields an RpcError in its slot when
    strict=False; with strict=True the first error raises (arg errors as
    FinanceBadRequest, not-found as FinanceNotFound)."""
    if not calls:
        return []
    label = label or "+".join(sorted({c[0] for c in calls}))
    replies = _replies(calls, language, country, label)
    results = []
    for i, (rpcid, _args) in enumerate(calls):
        reply = replies.get(str(i + 1))
        if reply is None and len(calls) == 1:
            reply = next(iter(replies.values()))
        if reply is None:
            err = RpcError(rpcid, "missing")
        elif reply[2] is not None:
            err = RpcError(rpcid, reply[2])
        else:
            results.append(reply[1])
            continue
        if strict:
            _raise_for(err, label)
        results.append(err)
    return results


def rpc(rpcid, args, *, language="en", country="US", label=None):
    """One rpc -> its decoded data (errors raise)."""
    return batch([(rpcid, args)], language=language, country=country, label=label or rpcid)[0]


def _raise_for(err, label):
    if err.code in _ARG_ERRORS:
        raise FinanceBadRequest(f"{label}: Google rejected the arguments ({err.rpcid} error {err.code})")
    if err.code in _NOT_FOUND_ERRORS:
        raise FinanceNotFound(f"{label}: not found")
    raise FinanceUpstreamError(f"{label}: {err}")


def ok(value):
    """A batch(strict=False) slot -> its data, or None for an RpcError."""
    return None if isinstance(value, RpcError) else value
