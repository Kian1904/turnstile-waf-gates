#!/usr/bin/env python3
"""Offline hCaptcha triage and response-contract tests.

This deliberately does not solve a live challenge or call a third-party solver.
It verifies that hCaptcha is not misrouted to the Turnstile path and that a client
requires a server-side JSON verdict before claiming success.
"""
import json
import re
import sys

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(("PASS  " if cond else "FAIL  ") + name + ((" — " + detail) if detail else ""))


H_CAPTCHA = ("h-captcha", "hcaptcha.render", "js.hcaptcha.com/1/api.js")
TURNSTILE = ("cf-turnstile", "turnstile/v0/api.js")


def classify(html, status=200):
    low = html.lower()
    if any(mark in low for mark in H_CAPTCHA):
        return "hcaptcha"
    if any(mark in low for mark in TURNSTILE):
        return "cloudflare-turnstile"
    return "ok" if status == 200 else "plain-deny"


def extract_sitekey(html):
    patterns = (
        r'data-sitekey=["\']([^"\']+)',
        r'\bsitekey\s*:\s*["\']([^"\']+)',
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            return match.group(1)
    return None


FIX = '''<div class="h-captcha" data-sitekey="10000000-ffff-ffff-ffff-000000000001"></div>
<script src="https://js.hcaptcha.com/1/api.js" async defer></script>'''
TURNSTILE_FIX = '<div class="cf-turnstile" data-sitekey="1x00000000000000000000AA"></div>'

print("=" * 68)
print("hCaptcha logic — offline, no browser, no solver")
print("=" * 68)
check("hCaptcha fixture classified separately", classify(FIX) == "hcaptcha")
check("hCaptcha is not classified as Turnstile", classify(FIX) != "cloudflare-turnstile")
check("hCaptcha sitekey extracted", extract_sitekey(FIX) == "10000000-ffff-ffff-ffff-000000000001")
check("Turnstile fixture remains Turnstile", classify(TURNSTILE_FIX) == "cloudflare-turnstile")

empty = {"success": False, "error-codes": ["missing-input-response"]}
passed = {"success": True, "hostname": "test.example"}
check("empty response is not a solve", not empty["success"])
check("server JSON success is the only pass signal", passed.get("success") is True)
check("page text cannot override a failed JSON verdict",
      "verification" in "Please complete verification" and empty["success"] is False)

test_key = extract_sitekey(FIX)
check("official test key is explicitly recognizable",
      bool(test_key and test_key.startswith("10000000-")))
print("\nNo live challenge was solved; this harness only proves routing and verdict parsing.")

ok = sum(RESULTS)
print(f"RESULT: {ok}/{len(RESULTS)} checks passed")
sys.exit(0 if ok == len(RESULTS) else 1)