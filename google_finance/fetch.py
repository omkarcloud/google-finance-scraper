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
  2. a thread whose call was refused (403 / 429 / /sorry) moves to a
     residential exit for GOOGLE_FINANCE_DIRECT_COOLDOWN seconds;
  3. after GOOGLE_FINANCE_MAX_ATTEMPTS blocked attempts, one headful
     patchright Chrome loads /finance/beta and replays the POST as an
     in-page fetch.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  FinanceUpstreamError  transport failure / 5xx / unparseable body  -> 502
  FinanceBlocked        403 / 429 / captcha                         -> 502
  FinanceBadRequest     Google rejected the rpc arguments           -> 400
  FinanceNotFound       unknown symbol                              -> 404
"""
import json
import os
import sys
import threading
import time
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError  # noqa: E402

SITE = "https://www.google.com"
HOME = f"{SITE}/finance/beta"
BATCH_PATH = "/finance/beta/_/FinHubUi/data/batchexecute"
IMPERSONATE = "chrome"
TIMEOUT = 30
XSSI_PREFIX = ")]}'"
BLOCK_STATUSES = (403, 429)

HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
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
    dbg = os.environ.get("GOOGLE_FINANCE_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w") as f:
                f.write(text if isinstance(text, str) else repr(text))
        except OSError:
            pass


# ---- curl sessions -------------------------------------------------------------------------
# One curl session per worker thread (a curl handle must not be shared
# across threads); it keeps its keep-alive connection for the thread's life.
_local = threading.local()


def _session():
    via_fallback = getattr(_local, "proxy_until", 0) > time.time()
    sess = getattr(_local, "session", None)
    if sess is not None and getattr(sess, "_gf_fallback", False) != via_fallback:
        _drop_session()
        sess = None
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = config.google_finance_proxy() or (config.google_finance_fallback_proxy() if via_fallback else None)
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        sess._gf_fallback = via_fallback
        _local.session = sess
    return sess


def _drop_session():
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _escalate():
    """This thread's exit was refused: move it to a residential exit for a while."""
    if config.google_finance_fallback_proxy() is not None:
        _local.proxy_until = time.time() + config.GOOGLE_FINANCE_DIRECT_COOLDOWN
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


# ---- browser fallback ------------------------------------------------------------------------

class _Browser:
    """One headful patchright Chrome on /finance/beta, opened on demand,
    reused while busy and closed after GOOGLE_FINANCE_BROWSER_IDLE_SECONDS."""

    def __init__(self):
        self.lock = threading.Lock()
        self.driver = None
        self.last_used = 0.0
        self.closer = None

    def _open(self):
        from chrome_manager import create_scope
        from patchright_driver import PatchrightDriver
        with create_scope():
            driver = PatchrightDriver(proxy_url=config.google_finance_fallback_proxy(), headless=False)
        try:
            driver.nav(HOME, mode="blocked", challenge_markers=("unusual traffic",))
        except Exception:
            driver.close()
            raise
        return driver

    def _close_if_idle(self):
        while True:
            time.sleep(30)
            with self.lock:
                if self.driver is None:
                    self.closer = None
                    return
                if time.time() - self.last_used > config.GOOGLE_FINANCE_BROWSER_IDLE_SECONDS:
                    self._drop()
                    self.closer = None
                    return

    def _drop(self):
        if self.driver is not None:
            try:
                self.driver.close()
            except Exception:
                pass
        self.driver = None

    def post(self, path_and_query, body, label):
        from patchright_driver import _FETCH_JS, FETCH_TIMEOUT_MS
        headers = {k: v for k, v in HEADERS.items() if not k.startswith(("sec-", "origin", "referer", "accept-language"))}
        with self.lock:
            if self.driver is None:
                self.driver = self._open()
            if self.closer is None:
                self.closer = threading.Thread(target=self._close_if_idle, daemon=True)
                self.closer.start()
            self.last_used = time.time()
            try:
                res = self.driver.call(lambda page: page.evaluate(_FETCH_JS, {
                    "url": SITE + path_and_query, "method": "POST", "headers": headers,
                    "body": body, "referrer": HOME, "timeoutMs": FETCH_TIMEOUT_MS}))
            except Exception:
                self._drop()
                raise
        if not res or (not res.get("status") and res.get("error")):
            raise FinanceUpstreamError(f"browser fetch failed on {label}: {(res or {}).get('error')}")
        status = int(res.get("status") or 0)
        if status in BLOCK_STATUSES:
            with self.lock:
                self._drop()
        return _classify(status, res.get("url") or "", res.get("body") or "", label)


_browser = _Browser()


# ---- batchexecute ----------------------------------------------------------------------------

def _post(path_and_query, body, label):
    """One POST with the escalation ladder -> response text."""
    attempts = max(1, int(config.GOOGLE_FINANCE_MAX_ATTEMPTS))
    last, blocked_only = None, True
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
            _drop_session()
        if attempt < attempts:
            time.sleep(min(config.RETRY_BACKOFF * attempt, 4))
    if blocked_only and config.GOOGLE_FINANCE_BROWSER_FALLBACK:
        return _browser.post(path_and_query, body, label)
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
        candidates.append(json.loads(body))
    except ValueError:
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("[["):
                try:
                    candidates.append(json.loads(line))
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
                    data = json.loads(payload)
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
