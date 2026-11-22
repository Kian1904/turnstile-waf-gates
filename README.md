# turnstile-waf-gates

**Hermes/agent skill: solve Cloudflare Turnstile, managed challenge, AWS WAF — triage DataDome vs PerimeterX vs Cloudflare before wasting hours on the wrong solver.**

Born from a live production campaign (2026-11-20): Cloudflare Turnstile solved end-to-end on real login pages — token auto-landing, interactive checkbox clicks, session login, email-OTP completion.

## What's inside

```
setup.py                      — one-command installer (auto-detects browser + PATH)
SKILL.md                      — the skill: triage tables, launch recipes, pitfalls
references/
  waf-solver-internals.md     — AWS WAF proof-of-work reverse (Go + Python port)
scripts/
  clean-fp-chrome             — spawn a Turnstile-grade Chromium (auto-detects browser, cross-platform)
  fp-audit                    — fingerprint checker via raw CDP websocket (no deps)
  turnstile-solve             — end-to-end token solver over raw CDP (stdlib only):
                                navigate / blank-page / auto-pass / click fallback,
                                fingerprint gate, error-code aborts, proxy flag, JSON output
  solver-api.py               — local HTTP API (POST /solve, GET /health), lock+queue
  awswaf-solve                — AWS WAF token solver (sha256/scrypt PoW, no browser needed)
  test_turnstile_logic.py     — 23 checks: classifier + sitekey/action/cData extraction
  test_live_triage.py         — 8 live-site checks (TLS only, no browser)
  test_replay_path.py         — 12 checks: token binding rules on a mock gate
  test_hcaptcha_logic.py      — offline hCaptcha routing/verdict checks
  test_solver_offline.py      — 26 checks: solver + API contracts, doctrine guards
  probe_nodom.js              — proves api.js requires a DOM (bare Node throws)
```

## Quick start (any platform)

```bash
# 1. Install (auto-detects Chrome/Chromium, links scripts to PATH)
python3 setup.py

# 2. Launch a clean-fingerprint browser
clean-fp-chrome              # Termux/desktop, auto-detected
clean-fp-chrome --check      # verify it's Turnstile-grade

# 3. Solve
turnstile-solve --url https://target.example/login
```

On Termux: `pkg install chromium` → `python3 setup.py`
On Debian/Ubuntu: `apt install chromium` → `python3 setup.py`
On macOS: `brew install --cask google-chrome` → `python3 setup.py`
On Windows: `winget install Google.Chrome` → `python setup.py`

All scripts are stdlib-only (no pip install needed). The only optional dependency
is `cryptography` for AWS WAF AES-256-GCM (the scrypt PoW path).

## The one finding that matters most

**Interactive vs non-interactive Turnstile is not a property of the sitekey — Cloudflare grades the browser fingerprint first, then picks the challenge.**

| Browser birth | Result |
|---|---|
| `headless_shell` + low-end flags | `webdriver=true`, UA `HeadlessChrome` → interactive challenge **always fails**, even with pixel-perfect trusted clicks |
| `chrome --headless=new` + clean UA + `--disable-blink-features=AutomationControlled` | challenge **downgrades to non-interactive** — token auto-lands in ~9 s, zero clicks |

Same sitekey, same script, same click logic. Only the process birth changed. Patching `navigator.webdriver` on the parent page does **nothing** — the challenge runs in an OOPIF with its own JS context. Fix the fingerprint at launch or not at all.

## hCaptcha expansion

hCaptcha is covered as a separate widget family: `h-captcha`, `hcaptcha.render`,
`hcaptcha-response`, callback/expiry/error handling, and server-side JSON verdicts.
The official always-pass test key is suitable for integration wiring only; it does not
test production anti-bot behavior. The skill also documents a conservative,
authorized-only vision-assisted workflow for visible challenges: screenshot → explicit
tile coordinates → trusted clicks → server response verification. It does not ship a
third-party solver or treat green UI/page text as proof of success.

## Quick start

```bash
# 1. launch a clean-fingerprint browser (Termux/arm64 path; adapt binary path elsewhere)
scripts/clean-fp-chrome

# 2. verify what Cloudflare will see — MUST print "VERDICT: CLEAN ✅"
scripts/fp-audit 9222

# 3. navigate to the target. With a clean fingerprint most Turnstile challenges
#    auto-pass in 9-15 s without any click.

# 4. if a click is genuinely needed, read SKILL.md §"Fingerprint decides the difficulty"
#    for the OOPIF coordinate-click recipe.
```

Run the self-tests (no browser needed for three of four):

```bash
python3 scripts/test_replay_path.py        # 12/12 — token binding rules
python3 scripts/test_hcaptcha_logic.py    # offline hCaptcha routing/verdict rules
node scripts/probe_nodom.js                # DOM requirement proof
# test_turnstile_logic.py & test_live_triage.py need curl_cffi (see SKILL.md)
```

## Verified matrix (2026-11-19/20, Indonesian egress, Termux/arm64)

| Target | Gate | Result |
|---|---|---|
| app.anoman.io (production login) | Turnstile `0x4AAAAAA…` | ✅ auto-pass + login + email-OTP |
| kenari.id (production login, ×2 visits) | Turnstile `0x4AAAAAAD…` | ✅ auto-pass <3 s both times |
| glassdoor.com | CF managed challenge | ✅ auto-resolved |
| crunchyroll.com | CF managed challenge | ✅ auto-resolved |
| 2captcha.com demo | Turnstile interactive (dummy key) | ✅ trusted click → `success: true` |
| etsy.com / g2.com | **DataDome** | correctly identified as NOT Cloudflare |
| zillow.com | **PerimeterX Press&Hold** | correctly identified; behavioral challenge not solved |
| reuters.com | **DataDome** | correctly identified; blocks CDP evaluation (hardest wall tested) |

## Full-provider verdict matrix (2026-11-21)

Five providers executed end-to-end, plus a datacenter-IP replication on an Instabox VM:

| Provider | Termux (mobile IP) | Datacenter IP (VM) |
|---|---|---|
| Turnstile dummy keys | ✅ PASS | ✅ PASS (IP-agnostic) |
| Turnstile interactive `3x…FF` | ❌ BLOCKED (`300030`) | ❌ BLOCKED |
| hCaptcha test keys | ✅ FULL PASS | ✅ PASS |
| AWS WAF CAPTCHA | ✅ PASS (puzzle solved via CDP) | — |
| Arkose (cap.guru demo) | ❌ DENIED ACCESS `400` | ❌ BLOCKED EARLIER (`gt2` never sent) |

**New finding:** Arkose's wall is **IP reputation first, environment second** — on a datacenter IP the `gt2` init request is killed before the challenge flow even starts. See SKILL.md §"Full-provider verdict matrix" for the full tables, the AWS WAF CAPTCHA solve pattern, and official test-key endpoints.

## How this compares

| | **turnstile-waf-gates** (this repo) | Theyka/Turnstile-Solver (986★) | cfsolve (888★) | EzSolver (161★) |
|---|---|---|---|---|
| **Dependencies** | stdlib only (zero pip) | patchright + camoufox | Rust + BoringSSL | Python + Chrome |
| **Termux/arm64** | ✅ native | ❌ no wheels | ❌ Rust cross-compile hell | ✅ |
| **Turnstile solve** | ✅ end-to-end CLI | ✅ + API server | ✅ request-based (no browser) | ✅ + API |
| **AWS WAF** | ✅ CLI (PoW solver) | ❌ | ❌ | ❌ |
| **Batch/Parallel** | ✅ batch + parallel scripts | ✅ async + multithread | ✅ library | ❌ single |
| **Fingerprint doctrine** | ✅ fingerprint-first, OOPIF click, error-code triage | ❌ just click | ❌ | ❌ |
| **Tests** | ✅ 71+ offline checks | ❌ none | ✅ CI | ❌ |
| **API service** | ✅ POST /solve + health | ✅ | ❌ | ✅ |
| **Cross-platform setup** | ✅ setup.py auto-detect | ❌ manual | ❌ cargo build | ❌ |
| **License** | MIT | CC BY-NC 4.0 | — | — |

The trade: Theyka/cfsolve are more mature (more stars, more battle-tested).
This repo trades maturity for portability (zero deps, Termux-native) and
documented doctrine (fingerprint-first, error-code triage, OOPIF mechanics).

## License

MIT
