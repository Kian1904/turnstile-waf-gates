#!/data/data/com.termux/files/usr/bin/python3
"""solver-api — local HTTP API in front of turnstile-solve. Stdlib only.

Same contract as the popular hosted solvers, minus the hosting:
  POST /solve   {"sitekey": "...", "siteurl": "...", "action"?, "cdata"?,
                 "timeout"?, "blank_page"?, "click"?}
                -> 200 {"status": "success", "token": "...", "elapsed": 9.2}
                -> 500 {"status": "error", "error": "...", "exit_code": N}
  GET  /health  -> {"status": "ok", "browser_up": true, "queued": 0}
  GET  /        -> tiny usage page

One shared browser, one solve at a time (a lock — same honest limit EzSolver
documents). Requests queue; the browser is NEVER parallel-driven because
concurrent Page.navigate on one tab corrupts the challenge state.

Usage:
  solver-api [--port 5000] [--cdp-port 9222] [--max-queue 8]
Requires: a clean-fingerprint browser already running (clean-fp-chrome).
"""
import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SOLVER = str(Path(__file__).resolve().parent / "turnstile-solve")
LOCK = threading.Lock()
QUEUE_DEPTH = 0
QUEUE_LOCK = threading.Lock()
CONFIG = {"cdp_port": 9222, "max_queue": 8}

USAGE_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>turnstile solver</title></head>
<body style="font-family:monospace;max-width:640px;margin:2em auto">
<h3>local turnstile solver</h3>
<pre>POST /solve
{"sitekey": "0x4AAA...", "siteurl": "https://target/login", "timeout": 45}

GET /health</pre>
<p>One browser, one solve at a time. Fingerprint gate enforced.</p>
</body></html>"""


def browser_up():
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{CONFIG['cdp_port']}/json/version", timeout=3) as r:
            return b"Browser" in r.read()
    except Exception:
        return False


def run_solve(body):
    siteurl = body.get("siteurl") or body.get("url")
    if not siteurl:
        return 400, {"status": "error", "error": "siteurl required"}
    cmd = [sys.executable, SOLVER, "--url", siteurl,
           "--port", str(CONFIG["cdp_port"]),
           "--timeout", str(body.get("timeout", 45)), "--json"]
    if body.get("sitekey"):
        cmd += ["--sitekey", body["sitekey"]]
    if body.get("action"):
        cmd += ["--action", body["action"]]
    if body.get("cdata"):
        cmd += ["--cdata", body["cdata"]]
    if body.get("blank_page"):
        cmd += ["--blank-page"]
    if body.get("click"):
        cmd += ["--click"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=float(body.get("timeout", 45)) + 30)
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        return 500, {"status": "error", "error": "solver process timed out"}
    except Exception as e:
        return 500, {"status": "error", "error": f"solver invocation failed: {e}"}
    if result.get("ok"):
        return 200, {"status": "success", "token": result["token"],
                     "elapsed": result["elapsed"], "mode": result.get("mode"),
                     "error_codes": result.get("error_codes", [])}
    return 500, {"status": "error", "error": result.get("error"),
                 "exit_code": result.get("exit_code"),
                 "error_codes": result.get("error_codes", [])}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *a):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), format % a))

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            with QUEUE_LOCK:
                q = QUEUE_DEPTH
            self._send(200, {"status": "ok", "browser_up": browser_up(), "queued": q})
        elif self.path == "/":
            data = USAGE_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self._send(404, {"status": "error", "error": "not found"})

    def do_POST(self):
        global QUEUE_DEPTH
        if self.path != "/solve":
            self._send(404, {"status": "error", "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send(400, {"status": "error", "error": "invalid JSON body"})
            return
        with QUEUE_LOCK:
            if QUEUE_DEPTH >= CONFIG["max_queue"]:
                self._send(429, {"status": "error", "error": "queue full"})
                return
            QUEUE_DEPTH += 1
        try:
            with LOCK:  # one solve at a time on the shared browser
                code, result = run_solve(body)
            self._send(code, result)
        finally:
            with QUEUE_LOCK:
                QUEUE_DEPTH -= 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--cdp-port", type=int, default=9222)
    ap.add_argument("--max-queue", type=int, default=8)
    args = ap.parse_args()
    CONFIG["cdp_port"] = args.cdp_port
    CONFIG["max_queue"] = args.max_queue
    if not browser_up():
        print(f"WARNING: no browser on :{args.cdp_port} — launch clean-fp-chrome first",
              file=sys.stderr)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"solver-api listening on http://127.0.0.1:{args.port} "
          f"(CDP :{args.cdp_port}, max queue {args.max_queue})", file=sys.stderr)
    srv.serve_forever()


if __name__ == "__main__":
    main()
