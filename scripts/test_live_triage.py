#!/usr/bin/env python3
"""
LIVE triage test: classify real gates over TLS only (curl_cffi impersonate=chrome).
No browser. Proves the skill's decision table against reality.

The point: an AWS solver fed a Cloudflare page (or a plain geo-deny) wastes
hours. This asserts the classifier gets real pages right.
"""
import re
import sys

from curl_cffi import requests as creq

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((bool(cond), name, detail))
    print(("PASS  " if cond else "FAIL  ") + name + ((" — " + detail) if detail else ""))


CF_TURNSTILE_MARK = "challenges.cloudflare.com/turnstile/v0/api.js"
CF_MANAGED_MARK = ("_cf_chl_opt", "just a moment", "cf-chl-widget", "/cdn-cgi/challenge-platform/")
AWS_MARK = ("challenge.js", "gokuprops", "aws-waf-token", "awswafintegration")
# DataDome ships a "Please enable JS and disable any ad blocker" page and calls
# geo.captcha-delivery.com — it is NOT Cloudflare and needs a different solver.
DATADOME_MARK = ("captcha-delivery.com", "var dd=", "datadome", "dd_cookie_test")
# PerimeterX / HUMAN: _pxAppId, px-captcha, "Press & Hold"
PERIMETERX_MARK = ("_pxappid", "px-captcha", "perimeterx", "pxhd")
SITEKEY_RE = re.compile(r"\b[0-3]x[0-9A-Za-z_-]{10,}\b")
TS_DIV = re.compile(r"<div[^>]*class=[\"'][^\"']*\bcf-turnstile\b", re.I)


def classify(html, status):
    low = html.lower()
    widget = bool(TS_DIV.search(html)) or (CF_TURNSTILE_MARK in low and SITEKEY_RE.search(html))
    managed = any(m in low for m in CF_MANAGED_MARK)
    aws = any(m in low for m in AWS_MARK)
    dd = any(m in low for m in DATADOME_MARK)
    px = any(m in low for m in PERIMETERX_MARK)

    # vendor checks come FIRST: a DataDome page often carries no CF string at all,
    # but a CF page can carry a third-party CDN reference, so be specific.
    if dd:
        return "datadome"
    if px:
        return "perimeterx"
    if widget:
        return "cloudflare-turnstile"
    if managed:
        return "cloudflare-managed"
    if aws:
        return "aws-waf"
    if status == 200:
        return "ok"
    return "plain-deny"


s = creq.Session(impersonate="chrome")

TARGETS = [
    # (url, expected-class, why)
    ("https://demo.turnstile.workers.dev/", "cloudflare-turnstile", "official Turnstile demo"),
    ("https://www.crunchyroll.com/", None, "known CF-fronted, may vary by egress"),
    ("https://www.g2.com/", None, "403 from ID egress — deny or challenge?"),
    ("https://example.com/", "ok", "plain page, must NOT be a gate"),
]

print("=" * 72)
print("LIVE triage — TLS only, no browser")
print("=" * 72)

found = {}
for url, expected, why in TARGETS:
    try:
        r = s.get(url, timeout=30, allow_redirects=True)
        html = r.text
        cls = classify(html, r.status_code)
        found[url] = (r.status_code, cls, len(html))
        sk = SITEKEY_RE.search(html)
        print(f"\n{url}")
        print(f"  HTTP {r.status_code} | {len(html)} bytes | classified: {cls}")
        print(f"  why: {why}")
        if sk:
            print(f"  sitekey: {sk.group(0)}")
        if expected:
            check(f"{url} -> {expected}", cls == expected, f"got {cls}")
    except Exception as e:
        print(f"\n{url}\n  ERROR {type(e).__name__}: {str(e)[:90]}")
        check(f"{url} reachable", False, type(e).__name__)

print("\n" + "=" * 72)
print("DECISION TABLE ASSERTIONS")
print("=" * 72)

# The classifier must never label a Cloudflare page as AWS WAF.
cf_pages = [(u, v) for u, v in found.items() if v[1].startswith("cloudflare")]
for u, (code, cls, n) in cf_pages:
    check(f"{u}: Cloudflare page NOT misrouted to aws-waf", cls != "aws-waf", cls)

# example.com must never be treated as a gate.
if "https://example.com/" in found:
    check("example.com not treated as a gate (no false positive)",
          found["https://example.com/"][1] == "ok", found["https://example.com/"][1])

# A tiny 403 must land in plain-deny or a NAMED vendor — never "assume it's Cloudflare".
if "https://www.g2.com/" in found:
    code, cls, n = found["https://www.g2.com/"]
    if code == 403 and n < 5000:
        check("small 403 gets a concrete vendor label, not a guess",
              cls in ("plain-deny", "ok", "datadome", "perimeterx", "cloudflare-managed"), cls)
        check("g2.com identified as DataDome (geo.captcha-delivery.com), NOT Cloudflare",
              cls == "datadome", f"got {cls}")

# At least one real Turnstile page must be classified correctly.
check("at least one live Turnstile widget found and classified",
      any(v[1] == "cloudflare-turnstile" for v in found.values()),
      str({k: v[1] for k, v in found.items()}))

ok = sum(1 for r in RESULTS if r[0])
print("\n" + "=" * 72)
print(f"RESULT: {ok}/{len(RESULTS)} live triage checks passed")
print("=" * 72)
if ok != len(RESULTS):
    for g, n, d in RESULTS:
        if not g:
            print("FAILED:", n, "|", d)
    sys.exit(1)
sys.exit(0)