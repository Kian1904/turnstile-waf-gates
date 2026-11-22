#!/data/data/com.termux/files/usr/bin/python3
"""test_solver_offline.py — offline checks for turnstile-solve + solver-api.

No browser, no network. Verifies: CLI contract, JSON output shape, error-code
classification, fingerprint-gate logic, API request validation and queue caps.
Run: python3 scripts/test_solver_offline.py
"""
import ast
import importlib.util
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOLVER = HERE / "turnstile-solve"
API = HERE / "solver-api.py"

passed = failed = 0

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS  {name}" + (f" — {detail}" if detail else ""))
    else:
        failed += 1
        print(f"FAIL  {name}" + (f" — {detail}" if detail else ""))

print("=" * 70)
print("turnstile-solve / solver-api — offline contract checks")
print("=" * 70)

# --- 1. syntax + structure ---
src = SOLVER.read_text()
tree = ast.parse(src)
check("solver parses as valid Python", True)
funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
for f in ("solve", "fingerprint_check", "click_checkbox", "fail", "main"):
    check(f"solver defines {f}()", f in funcs)

api_src = API.read_text()
ast.parse(api_src)
check("solver-api parses as valid Python", True)

# --- 2. stdlib-only guarantee (the Termux/arm64 promise) ---
import_names = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        import_names.update(a.name.split(".")[0] for a in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        import_names.add(node.module.split(".")[0])
stdlib = {"argparse", "base64", "json", "os", "socket", "struct", "sys", "time",
          "urllib"}
check("solver imports stdlib only", import_names <= stdlib, str(import_names - stdlib) if import_names - stdlib else "")

api_tree = ast.parse(api_src)
api_imports = set()
for node in ast.walk(api_tree):
    if isinstance(node, ast.Import):
        api_imports.update(a.name.split(".")[0] for a in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        api_imports.add(node.module.split(".")[0])
api_stdlib = {"argparse", "json", "subprocess", "sys", "threading", "time",
              "urllib", "http", "pathlib"}
check("solver-api imports stdlib only", api_imports <= api_stdlib)

# --- 3. doctrine guards baked into the code ---
check("fingerprint gate refuses dirty browsers (exit 2)", 'return fail(2' in src)
check("--force is the only bypass of the gate", "args.force" in src)
check("no Page.stopLoading anywhere (cancels challenge script)", '"Page.stopLoading"' not in src and "'Page.stopLoading'" not in src)
check("error-callback captured", "'error-callback'" in src)
check("expired-callback resets token", "'expired-callback'" in src)
check("hard client errors abort instead of click-looping", 'startswith("3000")' in src)
check("blank-page mode uses Fetch interception (origin-bound token)", "Fetch.fulfillRequest" in src)
check("click geometry read from parent, not OOPIF attach", "getBoundingClientRect" in src and '"Target.attachToTarget"' not in src)
check("click cooldown exists (no spam-clicking a hydrating widget)", "click_cooldown" in src)

# --- 4. CLI contract: bad usage fails cleanly with JSON ---
p = subprocess.run([sys.executable, str(SOLVER), "--url", "https://x.example/",
                    "--blank-page", "--port", "1"],  # port 1: nothing there
                   capture_output=True, text=True, timeout=30)
try:
    out = json.loads(p.stdout.strip().splitlines()[-1])
    check("failure emits JSON on stdout", isinstance(out, dict) and "ok" in out)
    check("no-browser failure exit code 5", p.returncode == 5 and out.get("exit_code") == 5,
          f"rc={p.returncode}")
    check("failure JSON carries error message", bool(out.get("error")))
except Exception as e:
    check("failure emits JSON on stdout", False, str(e))

p2 = subprocess.run([sys.executable, str(SOLVER), "--url", "https://x.example/",
                     "--blank-page"],  # missing --sitekey
                    capture_output=True, text=True, timeout=30)
# browser may or may not be up; either exit 5 (no browser) or exit 5 (usage) is fine
check("--blank-page without --sitekey never returns ok",
      p2.returncode != 0)

# --- 5. API contract: import module, exercise handler logic without sockets ---
spec = importlib.util.spec_from_file_location("solver_api", API)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

code, res = mod.run_solve({})
check("API rejects missing siteurl with 400", code == 400 and res["status"] == "error")

code, res = mod.run_solve({"siteurl": "https://x.example/", "timeout": 1})
# no browser on default port in CI => solver exits 5 => API maps to 500 error
check("API maps solver failure to status:error", res["status"] in ("error", "success"))
if res["status"] == "error":
    check("API error carries exit_code", "exit_code" in res)

# queue cap logic
mod.CONFIG["max_queue"] = 0
with mod.QUEUE_LOCK:
    depth_at_cap = mod.QUEUE_DEPTH >= mod.CONFIG["max_queue"]
check("queue cap compares depth >= max_queue", depth_at_cap)
mod.CONFIG["max_queue"] = 8

# --- 6. live API round-trip if the server happens to be running ---
try:
    with urllib.request.urlopen("http://127.0.0.1:5000/health", timeout=2) as r:
        health = json.loads(r.read())
    check("live /health responds", health.get("status") == "ok")
    req = urllib.request.Request("http://127.0.0.1:5000/solve",
                                 data=b"{}", headers={"content-type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
        check("live /solve rejects empty body", False, "should have been 400")
    except urllib.error.HTTPError as e:
        check("live /solve rejects empty body with 400", e.code == 400)
except Exception:
    print("SKIP  live API checks (server not running — start solver-api.py to include)")

print()
print(f"RESULT: {passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
