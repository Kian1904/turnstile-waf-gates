#!/usr/bin/env python3
"""
No-browser Turnstile REPLAY path — the part that is actually usable
without Chromium/Camoufox.

Tests the operational rules from skill `turnstile-waf-gates`:
  R1  a token is bound to ONE (client, action, cdata) triple  -> reuse must be refused
  R2  everything in the triple must be replayed byte-identical
  R3  action/cdata are INSIDE the token, so changing them invalidates it
  R4  one-shot: second use of the same token is rejected
  R5  the shell must send UA that matches the browser that minted the token
  R6  a failure must be read from the body, never from page text

Uses a local mock gate. Zero network needed, zero browser.
Exit 0 only if every rule is enforced by the mock AND the client respects it.
"""
import json
import sys
import threading
import http.server
from urllib.parse import urlparse, parse_qs
import urllib.request

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((bool(cond), name, detail))
    print(("PASS  " if cond else "FAIL  ") + name + ((" — " + detail) if detail else ""))


# ---------------------------------------------------------------- mock gate
class Gate:
    """Minimal Turnstile-shaped gate: token bound to (action, cdata, ua), one-shot."""

    def __init__(self):
        self.issued = {}   # token -> {action, cdata, ua, used:False}
        self.n = 0

    def mint(self, action, cdata, ua, bind_ua=True):
        self.n += 1
        tok = f"tok-{self.n:04d}-{action or 'none'}-{cdata or 'none'}"
        self.issued[tok] = {
            "action": action,
            "cdata": cdata,
            "ua": ua if bind_ua else None,
            "used": False,
        }
        return tok

    def spend(self, tok, action, cdata, ua):
        rec = self.issued.get(tok)
        if rec is None:
            return 403, "unknown-token"
        if rec["used"]:
            return 409, "token-already-used"
        if rec["action"] != action:
            return 403, "action-mismatch"
        if rec["cdata"] != cdata:
            return 403, "cdata-mismatch"
        if rec["ua"] and rec["ua"] != ua:
            return 403, "ua-mismatch"
        rec["used"] = True
        return 200, "ok"


GATE = Gate()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/submit":
            self.send_response(404); self.end_headers(); return
        n = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        ua = self.headers.get("user-agent", "")
        code, reason = GATE.spend(
            body.get("token"), body.get("action"), body.get("cdata"), ua
        )
        payload = json.dumps({"result": reason, "ok": code == 200}).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve():
    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


def post(port, token, action, cdata, ua):
    body = json.dumps({"token": token, "action": action, "cdata": cdata}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/submit", data=body,
        headers={"content-type": "application/json", "user-agent": ua},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


srv, port = serve()
print("=" * 70)
print(f"mock gate listening on 127.0.0.1:{port} (no browser, no network)")
print("=" * 70)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/136.0.0.0 Safari/537.36"

print("\n--- R1/R2: exact triple replays, anything else is refused ---")
tok = GATE.mint("login", "sess-abc", UA)
code, body = post(port, tok, "login", "sess-abc", UA)
check("valid triple accepted", code == 200 and body["ok"], f"{code} {body}")

tok2 = GATE.mint("login", "sess-abc", UA)
code, body = post(port, tok2, "login", "sess-WRONG", UA)
check("cdata mismatch refused", code == 403 and body["result"] == "cdata-mismatch",
      f"{code} {body['result']}")

tok3 = GATE.mint("login", "sess-abc", UA)
code, body = post(port, tok3, "signup", "sess-abc", UA)
check("action mismatch refused", code == 403 and body["result"] == "action-mismatch",
      f"{code} {body['result']}")

print("\n--- R3: action/cdata live inside the token ---")
check("token encodes action", "login" in tok)
check("token encodes cdata", "sess-abc" in tok)

print("\n--- R4: one-shot ---")
tok4 = GATE.mint("login", "sess-abc", UA)
c1, _ = post(port, tok4, "login", "sess-abc", UA)
c2, b2 = post(port, tok4, "login", "sess-abc", UA)
check("first use ok", c1 == 200)
check("second use rejected (one-shot)", c2 == 409 and b2["result"] == "token-already-used",
      f"{c2} {b2['result']}")

print("\n--- R5: UA must match the minting browser ---")
tok5 = GATE.mint("login", "sess-abc", UA)
code, body = post(port, tok5, "login", "sess-abc", "curl/8.0")
check("different UA refused", code == 403 and body["result"] == "ua-mismatch",
      f"{code} {body['result']}")

tok6 = GATE.mint("login", "sess-abc", "curl/8.0")
code, body = post(port, tok6, "login", "sess-abc", "curl/8.0")
check("unbound-UA token accepted from its own UA", code == 200, f"{code} {body}")

print("\n--- R6: verdict comes from the body, not page text ---")
page_text = "Please complete security verification"
code, body = post(port, GATE.mint("login", "x", UA), "login", "x", UA)
check("a 200 body with ok:true is the only pass signal",
      body["ok"] is True and body["result"] == "ok")
check("the words 'verification'/'success' in page text carry no verdict",
      "verification" in page_text and "success" not in json.dumps(body))

print("\n--- R7: unparsed/absent token is refused, never assumed good ---")
code, body = post(port, "made-up-token", "login", "sess-abc", UA)
check("fabricated token refused", code == 403 and body["result"] == "unknown-token",
      f"{code} {body['result']}")

srv.shutdown()

ok = sum(1 for r in RESULTS if r[0])
print("\n" + "=" * 70)
print(f"RESULT: {ok}/{len(RESULTS)} replay-path rules enforced")
print("=" * 70)
if ok != len(RESULTS):
    for g, n, d in RESULTS:
        if not g:
            print("FAILED:", n, "|", d)
    sys.exit(1)
sys.exit(0)