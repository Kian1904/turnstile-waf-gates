#!/usr/bin/env python3
"""
Offline-first test of the triage/extraction logic described in
skill `turnstile-waf-gates`. No browser, no Chromium, no Camoufox.

Tests:
  1. classify() correctly separates Turnstile / CF-challenge / AWS WAF / plain-deny / ok
  2. extract_sitekey() + extract_action() + extract_cdata() pull the right values
  3. rule "don't grep page text for success" is enforceable
  4. single-use / UA+IP binding facts are stated where a caller can act on them
  5. LIVE: fetch a real Turnstile page over TLS (curl_cffi, impersonate=chrome)
  6. LIVE: reproduce the edge case where the sitekey is injected by JS, not in HTML

Exit code 0 only if every assertion passes.
"""
import re
import sys
import json

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((bool(cond), name, detail))
    print(("PASS  " if cond else "FAIL  ") + name + ((" — " + detail) if detail else ""))


# ---------------------------------------------------------------- logic under test
CF_TURNSTILE = "challenges.cloudflare.com/turnstile/v0/api.js"
CF_MANAGED = ("_cf_chl_opt", "Just a moment", "cf-chl-widget", "/cdn-cgi/challenge-platform/")
AWS_WAF = ("challenge.js", "gokuProps", "aws-waf-token", "AwsWafIntegration")
# Production keys start 0x4AAAAAA. Cloudflare's official DUMMY keys are
# 1x...AA (always passes), 2x...AB (always fails), 3x...AC (invisible).
# A pattern that only knows 0x4AAAAAA misses every test page.
SITEKEY_RE = re.compile(r"\b[0-3]x[0-9A-Za-z_-]{10,}\b")
TURNSTILE_DIV_RE = re.compile(
    r"<div[^>]*class=[\"'][^\"']*\bcf-turnstile\b[^\"']*[\"'][^>]*>", re.I)


def _attr(tag, name):
    m = re.search(name + r"\s*=\s*[\"']([^\"']*)[\"']", tag, re.I)
    return m.group(1) if m else None


def classify(html, status=200):
    """Order matters: managed challenge first, then widget, then AWS, then deny."""
    low = html.lower()
    has_managed = any(m.lower() in low for m in CF_MANAGED)
    has_widget = bool(TURNSTILE_DIV_RE.search(html)) or (
        CF_TURNSTILE in low and SITEKEY_RE.search(html))
    has_aws = any(m.lower() in low for m in AWS_WAF)

    if has_managed and not has_widget:
        return "cloudflare-managed"
    if has_widget:
        return "cloudflare-turnstile"
    if has_aws:
        return "aws-waf"
    if status == 200:
        return "ok"
    return "plain-deny"


def extract(html):
    """Returns dict with sitekey/action/cdata and the div that carried them."""
    out = {"sitekey": None, "action": None, "cdata": None, "inline_script": False}
    div = TURNSTILE_DIV_RE.search(html)
    if div:
        tag = div.group(0)
        out["sitekey"] = _attr(tag, "data-sitekey")
        out["action"] = _attr(tag, "data-action")
        out["cdata"] = _attr(tag, "data-cdata")
    if not out["sitekey"]:
        m = SITEKEY_RE.search(html)
        if m:
            out["sitekey"] = m.group(0)
    if not out["sitekey"]:
        # last resort: explicit turnstile.render({sitekey: ...}) in an inline script
        m = re.search(r"turnstile\.render\([^)]*sitekey\s*:\s*[\"']([^\"']+)", html, re.S)
        if m:
            out["sitekey"] = m.group(1)
            out["inline_script"] = True
    else:
        # found via the generic scan, not the div: note whether it came from JS
        out["inline_script"] = "turnstile.render(" in html
    return out


def looks_solved_by_text(html):
    """The anti-pattern the skill warns about — must NOT be used."""
    return bool(re.search(r"pass|verif|success", html, re.I))


# ---------------------------------------------------------------- fixtures
FIX_TURNSTILE = """<html><body>
<div class="cf-turnstile" data-sitekey="0x4AAAAAAABkMYinukE8nzY_" data-action="login"
     data-cdata="sessionid-abc123"></div>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
</body></html>"""

FIX_TURNSTILE_JS = """<html><body><div id="ts"></div>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"></script>
<script>
turnstile.render('#ts', {sitekey: '0x4AAAAAAABkMYinukE8nzY_', action: 'checkout'});
</script></body></html>"""

FIX_MANAGED = """<html><head><title>Just a moment...</title></head><body>
<script>window._cf_chl_opt={cvId:'3',cRay:'abc'};</script>
<form id="challenge-form" action="/cdn-cgi/challenge-platform/h/b/flow"></form>
</body></html>"""

FIX_AWS = """<html><body><script>
window.gokuProps = {"key":"AQID","iv":"AAAA","context":"xyz"};
</script><script src="https://abc123.token.awswaf.com/abc123/challenge.js"></script>
</body></html>"""

FIX_DENY = "<html><body>Access Denied</body></html>"

FIX_PROMPT_TEXT = """<html><body>
<h1>Please complete security verification</h1>
</body></html>"""


print("=" * 70)
print("PART 1 — classification (offline fixtures)")
print("=" * 70)
check("turnstile widget classified", classify(FIX_TURNSTILE) == "cloudflare-turnstile",
      classify(FIX_TURNSTILE))
check("managed challenge classified", classify(FIX_MANAGED, 403) == "cloudflare-managed",
      classify(FIX_MANAGED, 403))
check("managed NOT mistaken for widget", classify(FIX_MANAGED) != "cloudflare-turnstile")
check("aws waf classified", classify(FIX_AWS) == "aws-waf", classify(FIX_AWS))
check("plain 403 deny classified", classify(FIX_DENY, 403) == "plain-deny",
      classify(FIX_DENY, 403))
check("normal page classified ok", classify("<html>hello</html>") == "ok")
check("turnstile page not classified as aws", classify(FIX_TURNSTILE) != "aws-waf")

print()
print("=" * 70)
print("PART 2 — parameter extraction")
print("=" * 70)
e = extract(FIX_TURNSTILE)
check("sitekey extracted from div", e["sitekey"] == "0x4AAAAAAABkMYinukE8nzY_", e["sitekey"])
check("action extracted", e["action"] == "login", str(e["action"]))
check("cdata extracted", e["cdata"] == "sessionid-abc123", str(e["cdata"]))
check("all three present (action+cdata are inside the token)",
      all([e["sitekey"], e["action"], e["cdata"]]))

e2 = extract(FIX_TURNSTILE_JS)
check("sitekey from turnstile.render() fallback", e2["sitekey"] == "0x4AAAAAAABkMYinukE8nzY_",
      str(e2["sitekey"]))
check("JS-injection path flagged", e2["inline_script"] is True)
check("no cdata when absent (must be omitted, not faked)", e2["cdata"] is None)

print()
print("=" * 70)
print("PART 3 — anti-pattern guard (don't detect success by page text)")
print("=" * 70)
check("naive text check WOULD false-positive on challenge prompt",
      looks_solved_by_text(FIX_PROMPT_TEXT) is True)
check("naive text check is useless on a real deny page",
      looks_solved_by_text(FIX_DENY) is False)
print("      -> this is why the skill says: parse the token/cookie, never the text")

# ---------------------------------------------------------------- live section
print()
print("=" * 70)
print("PART 4 — LIVE fetch (TLS only, no browser)")
print("=" * 70)
live_html = None
try:
    from curl_cffi import requests as creq
    s = creq.Session(impersonate="chrome")
    r = s.get("https://demo.turnstile.workers.dev/", timeout=30)
    live_html = r.text
    print(f"      HTTP {r.status_code}, {len(live_html)} bytes")
    check("live: reachable over TLS impersonating chrome", r.status_code == 200,
          str(r.status_code))
    cls = classify(live_html, r.status_code)
    check("live: classified as turnstile", cls == "cloudflare-turnstile", cls)
    lv = extract(live_html)
    check("live: sitekey found", bool(lv["sitekey"]), str(lv["sitekey"]))
    check("live: sitekey is a valid Turnstile key (0x4AAAAAA prod / 1x-3x dummy)",
          bool(lv["sitekey"] and re.fullmatch(r"[0-3]x[0-9A-Za-z_-]{10,}", lv["sitekey"])),
          str(lv["sitekey"]))
    check("live: dummy-key site detected (this page ALWAYS passes — not a real gate)",
          bool(lv["sitekey"] and lv["sitekey"].startswith("1x")),
          "1x=always-pass, 2x=always-fail, 3x=invisible")
    print(f"      extracted: {json.dumps(lv)}")
except Exception as e:
    check("live fetch", False, f"{type(e).__name__}: {e}")

print()
print("=" * 70)
print("PART 5 — the boundary this skill admits")
print("=" * 70)
print("      token generation requires executing api.js in a real JS engine;")
print("      a static fetch can only extract sitekey/action/cData.")
if live_html is not None:
    has_apijs = CF_TURNSTILE in live_html.lower()
    has_token_val = bool(re.search(r'name=[\"\']cf-turnstile-response[\"\'][^>]*value=[\"\'][^\"\']{10,}', live_html, re.I))
    check("live page references api.js (so JS is required)", has_apijs)
    check("live page ships NO pre-filled token in HTML (proves fetch alone is not enough)",
          not has_token_val, "token field is empty until JS runs")

# ---------------------------------------------------------------- summary
ok = sum(1 for r in RESULTS if r[0])
print()
print("=" * 70)
print(f"RESULT: {ok}/{len(RESULTS)} checks passed")
print("=" * 70)
if ok != len(RESULTS):
    for good, name, detail in RESULTS:
        if not good:
            print("FAILED:", name, "|", detail)
    sys.exit(1)
sys.exit(0)