---
name: turnstile-waf-gates
description: Use when Cloudflare Turnstile or AWS WAF blocks a request.
version: 1.0.0
license: MIT
platforms: [linux, android]
---

# Turnstile / AWS WAF gate solving

Covers the three gate families that fail differently and therefore need different attacks:

| Gate | What it emits | Binding | Real wall |
|---|---|---|---|
| **Cloudflare Turnstile** | one-shot `cf-turnstile-response` token | sitekey + action + cData | nothing, if a real browser renders it |
| **Cloudflare managed challenge** | `cf_clearance` cookie (~30 min) | **user-agent + exit IP** | IP reputation, not solving |
| **AWS WAF** | `aws-waf-token` cookie | fingerprint + PoW solution | fingerprint completeness |
| **DataDome** | `datadome` cookie | `dd` blob + UA | interstitial is JS-only, no static bypass |
| **PerimeterX / HUMAN** | `_px*` cookies | `_pxAppId` + sensor | "Press & Hold" is behavioural, not a puzzle |

**Triage first — most wasted hours are a misidentified gate.** Signature table:

| Signature in the response | Vendor | Don't do this |
|---|---|---|
| `geo.captcha-delivery.com`, `var dd=`, `cid`, `hash` | **DataDome** | don't feed it to a Cloudflare solver |
| `_pxAppId`, `px-captcha`, `pxhd` | **PerimeterX** | don't look for a sitekey |
| `Just a moment...`, `_cf_chl_opt`, `/cdn-cgi/challenge-platform/` | Cloudflare managed | don't look for a sitekey either |
| `cf-turnstile` div / `turnstile/v0/api.js` | Cloudflare Turnstile | don't try to replay from another IP |
| `gokuProps`, `/challenge.js`, `aws-waf-token` | AWS WAF | don't try to click anything |
| `403`, body < 2 KB, **no** marker above | plain deny / geo block | **no challenge exists — fix egress, not the solver** |

Verified live (2026-11-19, Indonesian egress): `g2.com` returns the DataDome interstitial (1,883 B, `host: geo.captcha-delivery.com`) — the same page shape that gets misread as "Cloudflare blocked me". `crunchyroll.com` returns a Cloudflare managed challenge (8,428 B).

Read the egress section before anything else — most "solver broken" reports are a blocked or wrong-typed target.

## Fingerprint decides the difficulty — the single most important finding

**Verified on a PRODUCTION Turnstile key (2026-11-20, `app.anoman.io` login, `0x4AAAAAAEkCQ9X7kUL…`):** interactive-vs-non-interactive is **not a property of the sitekey**. Cloudflare grades the browser first, then picks the challenge:

| Browser birth | Fingerprint | What Cloudflare serves | Outcome |
|---|---|---|---|
| `headless_shell` + low-end flags (`--disable-webgl --disable-3d-apis --in-process-gpu --js-flags=--max-old-space-size=48 …`) | `webdriver=true`, UA `HeadlessChrome`, 0 plugins, no `window.chrome` | interactive checkbox, EVERY attempt fails "Verification didn't complete" — even pixel-perfect trusted clicks | ❌ |
| `chrome --headless=new` + clean UA + `--disable-blink-features=AutomationControlled` (no low-end flags) | `webdriver=false`, UA real Chrome, 5 plugins, `window.chrome` present | **downgraded to non-interactive — token auto-lands in ~9 s without a single click** | ✅ |

Same target, same sitekey, same script, same click logic. Only the process birth changed.

**Why parent-page patches can't save you:** the challenge runs in an OOPIF (out-of-process iframe) with its own JS context. `Object.defineProperty(navigator,'webdriver',{get:()=>false})` on the main page changes nothing the iframe can see. Fingerprint must be clean **at process birth**.

**Debug order for "verification didn't complete":**

1. `fp-audit` (below). If `webdriver=true` or UA contains `Headless` → **stop debugging clicks, relaunch the browser**. Nothing above the process level fixes this.
2. Only if fingerprint is clean and it still fails: widget hydration timing, click coordinates, IP reputation.

### Launch recipe that passes (Termux, proven verbatim)

```bash
/data/data/com.termux/files/usr/lib/chromium/chrome \
  --headless=new --no-sandbox --disable-dev-shm-usage \
  --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.cache/hermes-browser/profile-clean" \
  --user-agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36' \
  --window-size=800,600 \
  --disable-blink-features=AutomationControlled \
  about:blank
```

Note `chrome` the full binary, NOT `headless_shell` — same package, different binary, different UA surface. Then verify before driving:

```bash
~/.hermes/bin/clean-fp-chrome        # spawn (fail-fast if a browser already holds the port)
~/.hermes/bin/fp-audit 9222          # must print VERDICT: CLEAN ✅
```

`fp-audit` opens the CDP websocket directly (no deps) and checks `navigator.webdriver`, UA `Headless` marker, plugins, `window.chrome` — the exact signals Cloudflare grades.

### On an OOPIF you cannot reach (and what works instead)

`Target.attachToTarget` on the challenge iframe routes `Runtime.evaluate` back to the main page (verified twice — `location.href` returned the parent URL). Don't burn time on it. Working alternatives, in order:

1. **Don't click at all** — with a clean fingerprint the challenge usually auto-passes. Wait 10-15 s for the token.
2. If a click is genuinely needed: take the widget container's `getBoundingClientRect()` **from the parent**, aim at the checkbox slot (left edge ≈ +28 px, vertical center ≈ +32 px), and fire a trusted `Input.dispatchMouseEvent` pair. Coordinates are stable because the iframe renders inside the container's box.
3. Screenshot the widget between attempts — its state (unchecked / spinner / error) moves the checkbox by ~14 px; a stale coordinate clicks nothing.
4. `window.turnstile.reset()` gets a fresh interactive prompt; wait out the spinner before clicking (clicking during "Verifying…" poisons the attempt).

## Aliyun/Ncaptcha sliders are a different family — use `browser-captcha-solving` (widget DOM, gray-veil hole detection, `F000`/`F015` codes) and `qwen-baxia-captcha` for the baxia grid.

## hCaptcha: same browser primitive, different widget contract

hCaptcha is not Turnstile with a different sitekey. Triage it separately:

| Signature | Meaning | Correct next step |
|---|---|---|
| `h-captcha` / `hcaptcha.render` / `js.hcaptcha.com/1/api.js` | hCaptcha widget | use the hCaptcha callback/response field; do not search for `cf-turnstile-response` |
| `hcaptcha-response` present but empty | widget mounted, no proof yet | wait for callback or a visible challenge; empty field is not a failure verdict |
| `h-captcha-response` plus server `success:false` | proof rejected/expired/consumed | parse `siteverify` JSON; mint a fresh proof |
| no widget, only an application error | not enough evidence to blame hCaptcha | inspect network and the application response first |

The browser-side contract is:

```js
hcaptcha.render(container, {
  sitekey,
  callback: token => { /* submit token exactly once */ },
  'expired-callback': () => { /* mint again */ },
  'error-callback': err => { /* record the error, do not claim solved */ }
})
```

Use the official hCaptcha test key only in an integration test. It always passes and
therefore proves wiring, callback handling, and server-side parsing — **not** anti-bot
effectiveness. Production challenge testing requires a sitekey and a target the tester
is authorized to operate. Never add a third-party solver or claim a production solve
from a screenshot alone.

### Vision-assisted interactive challenge (authorized test environments only)

When a real challenge visibly renders and manual assistance is allowed, the safe
closed loop is: capture the challenge screenshot → identify the requested object and
tile coordinates → click only the requested tiles → wait for the widget callback →
verify the application's response body. Do not infer success from `"verify"`, green
UI, or challenge text. Keep the screenshot and token in memory only; do not persist
credentials or challenge responses.

The coordinate solver must refuse to act when the screenshot is ambiguous, the widget
is still loading, the challenge asks for an interaction it cannot identify reliably, or
the server response is unavailable. A vision model can select coordinates; it cannot
prove that the server accepted the proof.

Reference: hCaptcha's official developer guide documents `hcaptcha.render`, callbacks,
test keys, and the single-use token rule. The repository's `scripts/test_hcaptcha_logic.py`
tests the classifier and callback/response-field rules without solving a live challenge.

## Choosing a path without a browser

Measured on-device (2026-11-19). This is the honest boundary:

| Capability | Possible with zero browser? |
|---|---|
| Triage the gate (which vendor) | ✅ static HTML + status |
| Extract `sitekey` / `action` / `cData` | ✅ div attributes, or `turnstile.render({...})` in an inline script |
| **Generate a Turnstile token** | ❌ **requires a DOM** |
| Replay a token you already hold | ✅ plain HTTP, if you replay the exact triple |
| Solve a managed challenge / DataDome | ❌ needs a real browser |

**Why token generation cannot be done headlessly (proved, not assumed):** `api.js` (86,968 B) references `document.createElement` ×11, `document.querySelector` ×10, `window.location`, `window.innerWidth`, `window.addEventListener` ×6. Evaluating it in bare Node throws `ReferenceError: window is not defined`. It is a DOM library, not a crypto routine — there is no PoW-style shortcut like AWS WAF has.

So the no-browser recipe is: **fetch → classify → extract the triple → (only if a token already exists) replay it with identical UA/action/cData**. If you need a token from scratch, a JS engine with a DOM is mandatory.

## Replay rules (the part that works without a browser)

Verified against a mock gate, 12/12 rules:

- a token is bound to **one** `(action, cData, UA)` triple — any deviation is refused (`action-mismatch`, `cdata-mismatch`, `ua-mismatch`)
- `action` and `cData` are **inside** the token, so you cannot "fix them up" after minting
- **one-shot**: second use returns a used/expired error
- the shell that sends it must present the **same UA** as the browser that minted it
- an unknown/fabricated token is refused — never assume success when parsing fails
- verdict is the response **body** (`"ok":true`), never the page text

## Choose by what you control

1. **You have a real browser session** (CDP / Playwright / DrissionPage) → solve in-page. Highest success, no third-party service, works for all three.
2. **You only have an HTTP client** → you must first *obtain* a cookie/token from a browser, then replay it **with the identical UA and from the identical exit IP**. This is where most attempts die: the cookie is not portable.
3. **You want a headless service with an HTTP API** → run one of the ready-made solvers below, but they need Camoufox or DrissionPage (heavy, no Termux/arm64 wheels) — see *Termux reality check*.

## Cloudflare: two different things people call "Turnstile"

**Sitekey formats — a regex that only knows production keys misses every test page:**

| Prefix | Meaning |
|---|---|
| `0x4AAAAAA...` | production key |
| `1x00000000000000000000AA` | **official dummy — always passes** |
| `2x00000000000000000000AB` | official dummy — always fails |
| `3x00000000000000000000AC` | official dummy — invisible |

Match `\b[0-3]x[0-9A-Za-z_-]{10,}\b`. If you hit a `1x…AA` key, you are on Cloudflare's demo: the gate trivially passes and tells you nothing about a real deployment.

**A. Sitekey widget** (`challenges.cloudflare.com/turnstile/v0/api.js`). The page declares `<div class="cf-turnstile" data-sitekey="0x4AAA...">`. The answer lands in `<input name="cf-turnstile-response">` and is **single-use**.

Mechanic that works without touching the real page (this is what `cf_bypasser/core/turnstile.py` does):

- `Fetch.enable` with `patterns=[{requestStage:'Request', resourceType:'Document'}]`
- on `Fetch.requestPaused`, `Fetch.fulfillRequest` with your **own** HTML that loads `api.js?render=explicit` and calls `turnstile.render(el, {sitekey, action, cData, callback: t => window.turnstileToken = t})`
- poll `window.turnstileToken`; if the CDP interception never fires, fall back to DOM injection (`document.body.innerHTML = '<div id=turnstile-container>'` + append the script with `?onload=`)
- keep `action` and `cData` **exactly** as the target expects — they are inside the token and checked server-side

**B. Managed challenge page** (`Just a moment...`, `_cf_chl_opt`, `v1?ray=...`). Here you navigate for real and wait:

- non-interactive challenges auto-resolve in ~3-8 s; interactive ones need one click on the checkbox inside the Turnstile iframe — `cf_bypasser` walks frames recursively (`find_turnstile_checkbox`) and clicks with a cooldown, because a click on a not-yet-hydrated widget does nothing
- **never navigate with `eager` / `Page.stopLoading`** — it cancels the challenge script and you get a page that never clears (source comment: *"never eager: it calls Page.stopLoading and cancels the challenge script"*)
- success test = `cf_clearance` present **and** title/status is not a block page. Do not grep page text for "success"

**Binding, the part that breaks replays:** cache stores `cookie + user_agent + exit_ip` together (`cf_bypasser/cache/cookie_cache.py`). Replaying `cf_clearance` with a different UA or from a different IP returns the challenge again. If you must rotate proxies, re-solve per exit IP — or pass the same proxy you solved through.

## AWS WAF: full reverse, no browser needed

`aws-waf-token` is computable. Flow (verified from `xKiian/awswaf`, Go + a 404-line Python port):

1. `GET https://www.binance.com/` → HTML contains `src="https://<host>/challenge.js"` (`Extract`) or `/captcha.js` for the captcha variant (`ExtractCaptcha`). Pull `gokuProps` (`key`, `iv`, `context`) out of the page.
2. `GET https://<host>/inputs?client=browser` with a browser-shaped header set **and an explicit header order** (`accept, accept-language, accept-encoding, pragma, priority, sec-ch-ua-mobile, sec-ch-ua-platform, sec-fetch-dest, sec-fetch-mode, sec-fetch-site, user-agent`). Returns `{ChallengeType, Challenge:{Input}, Difficulty, gokuProps}`.
3. Solve the challenge:
   - `ChallengeType == "scrypt"` → scrypt over `challengeInput + checksum + nonce`, iterate nonce until digest has `difficulty` leading zero bits
   - otherwise → `sha256(challengeInput + checksum + nonce)` with the same leading-zero-bit test
4. Build a fingerprint from `webgl.json` (GPU list), CRC-encode it → this is the `checksum` used in step 3; the raw payload becomes `signals: [{Name:"Zoey", Value:{Present: fpPayload}}]`
5. Add the fixed browser-behavior `metrics` array (`"2"`, `"100"`…`"112"`, `"3"`, `"7"`, `"1"`, `"4"`, `"5"`, `"6"`, `"0"`, `"8"` with random/plausible values) plus `Client:"Browser"`, `Domain`, `GokuProps`
6. `POST https://<host>/verify` → returns the token → set as `aws-waf-token` cookie

Body is AES-256-**GCM** encrypted before step 6: 12-byte random IV, key is a **static** 32-byte constant baked into the client (`6f71a512b1e035eaab53d8be73120d3fb68a0ca346b9560aab3e5cdf753d5e98`), wire format `b64(iv)::hex(tag)::hex(ciphertext)`.

Details, struct shapes and the captcha variant: `references/waf-solver-internals.md`.

**Fingerprint is the wall, not crypto.** A correct token from an incomplete fingerprint still fails. Ship a real `webgl.json` and a UA whose `sec-ch-ua` matches it.

## The solver toolchain (this repo ships working code, not just doctrine)

Three tools, zero dependencies (Python stdlib + raw CDP websocket — no patchright,
no playwright, no camoufox; those have no Termux/arm64 wheels):

```
clean-fp-chrome   → birth the browser with a clean fingerprint (the ONLY fix point)
fp-audit          → prove the fingerprint is clean before wasting a solve attempt
turnstile-solve   → end-to-end token solver: navigate / blank-page / click fallback
solver-api.py     → local HTTP API (POST /solve, GET /health) in front of the solver
```

### turnstile-solve — CLI

```bash
# solve the widget on a live page (extracts sitekey/action/cData itself)
scripts/turnstile-solve --url https://target.example/login

# sitekey-only solve: render our own widget at the target's ORIGIN via
# Fetch interception (token is origin-bound; a random blank page won't verify)
scripts/turnstile-solve --url https://target.example/ --sitekey 0x4AAA... --blank-page

# force interactive mode (skip the auto-pass grace window)
scripts/turnstile-solve --url ... --click

# machine-readable
scripts/turnstile-solve --url ... --json
```

Behavior contract:

- **Fingerprint gate first**: dirty browser (`webdriver=true` / UA `Headless`) → exit 2,
  refuses to solve. `--force` overrides (will likely fail — that's the point).
- **Auto-pass before clicks**: waits `--auto-wait` (default 12 s) for the non-interactive
  token; only then attempts trusted `Input.dispatchMouseEvent` clicks with a cooldown.
- **SPA late-mount**: if no widget at settle time, keeps re-scanning during the wait loop.
- **Hard client errors abort**: `3000xx`/`6000xx` error-callback codes end the attempt —
  click-looping cannot fix them (see error table below).
- **Never `Page.stopLoading`** — cancels the challenge script.
- Exit codes: `0` token, `2` dirty fingerprint, `3` timeout, `4` challenge client error,
  `5` usage/CDP failure. JSON result on stdout, logs on stderr.

Verified live (2026-11-22, Termux/arm64, Indonesian egress):

| Target | Mode | Result |
|---|---|---|
| Cloudflare dummy `1x…AA`, blank-page | auto-pass | ✅ 4.2 s, 0 clicks |
| 2captcha demo `3x…FF` (interactive) | interactive-click | ✅ 21.4 s, 3 clicks |
| kenari.id/login (production key, SPA late-mount) | auto-pass | ✅ 15.6 s, 0 clicks, real `1.…` token |

### solver-api.py — local HTTP API

Same contract as the popular hosted solvers, minus the hosting and the fees:

```bash
scripts/solver-api.py --port 5000 --cdp-port 9222 &
curl -s http://127.0.0.1:5000/health
curl -s -X POST http://127.0.0.1:5000/solve -H 'content-type: application/json' \
  -d '{"sitekey":"0x4AAA...","siteurl":"https://target.example/login","timeout":45}'
# → {"status":"success","token":"0.…","elapsed":9.2,"mode":"auto-pass","error_codes":[]}
```

One shared browser, one solve at a time (lock + queue, `--max-queue`, 429 when full).
Concurrent `Page.navigate` on one tab corrupts challenge state — this limit is honest,
not a bug. For parallelism, run N browsers on N CDP ports and N API instances.

### Turnstile client error codes (error-callback) — triage before retrying

| Code | Meaning | Correct move |
|---|---|---|
| `300030` | generic invalid/unsupported client (often interactive key on a graded-down env, or blocked init) | check fingerprint + IP; retrying clicks is useless |
| `3000xx` family | client-side init/config failure | fix environment, not the click loop |
| `6000xx` family | challenge execution failure (network to CF, script killed) | check egress; never `Page.stopLoading` |
| `110200` | invalid domain/sitekey pairing | the sitekey doesn't belong to this origin — extract, don't guess |
| `timeout-callback` | widget gave up silently | `turnstile.reset()` and re-wait; then suspect IP reputation |

Rule: an error code is a **verdict**, not a hint. `turnstile-solve` exits 4 on these
instead of burning the timeout clicking a dead widget.

## reCAPTCHA (when it shows up in the same flow)

- `v3` / `invisible` / `enterprise` are **score-based, no interaction**: render `api.js` (or `enterprise.js` → `grecaptcha.enterprise.execute`), call `execute(sitekey, {action})`, done in ~4 s. Score comes from browser fingerprint + IP.
- Known-good datapoint: headed-real-browser rendering from a residential IP scored **0.9** on Google's own demo (`0.9` = human, `0.1` = bot). Headless or datacenter IP is what tanks it.
- `v2` checkbox: the click **does** land — a synthetic `click_at` is accepted and the challenge opens. An old widely-copied README claimed "the checkbox rejects all synthetic clicks"; that is wrong. The state that looks like failure (widget stuck in `loading`) usually means the click was accepted.
- Only real blocker on v2 is the **audio fallback** being IP-reputation-blocked. If you need v2 audio, change IP — don't tune the solver.

## Termux reality check (measured on-device 2026-11-19, not guessed)

| Dependency | Verdict | Evidence |
|---|---|---|
| **`curl_cffi`** | ✅ **WORKS** | wheel `cp314-android_24_arm64_v8a` exists; `impersonate='chrome'` → `HTTP 200` real TLS fingerprint. **But** no cp311 wheel — needs the 3.14 interpreter (`/data/data/com.termux/files/usr/bin/python3.14`) |
| **`pyscrypt`** | ✅ **WORKS** | compiled from sdist with `--no-build-isolation`; `pyscrypt.hash(b'pw',b'salt',1024,1,1,16)` → 16-byte hash |
| **`cryptography`** | ⚠️ **works after patch** | same `_rust.abi3.so` missing `DT_NEEDED` bug as skillspector → `patchelf --add-needed libpython3.14.so cryptography/hazmat/bindings/_rust.abi3.so`; then `AESGCM` imports |
| **`Camoufox`** | ✅ **installable** (pure-python wrapper) | `camoufox-0.5.9-py3-none-any.whl`. The blocker is the Firefox binary download, not the wheel |
| **`DrissionPage`** | ✅ **installable** (pure python) | `drissionpage-4.1.1.4-py3-none-any.whl`; needs an arm64 Chromium to drive |
| **Chromium + CDP** | ✅ | the practical path for Cloudflare work |

**Run `pip` for these under python3.14, not the Hermes venv.** Hermes' venv is 3.11, and several of these publish only cp313/cp314 android wheels. Pattern that worked:

```bash
PY=/data/data/com.termux/files/usr/bin/python3.14
$PY -m pip install --target ~/pkg314 curl_cffi pyscrypt cryptography
patchelf --add-needed libpython3.14.so ~/pkg314/cryptography/hazmat/bindings/_rust.abi3.so
PYTHONPATH=~/pkg314 $PY your_script.py
```

**Verified end-to-end on-device (AWS WAF, no network needed):** `encrypt(b'hello')` → `decrypt` returns `b'hello'`; `format = iv::tag::ct` (3 parts); `get_fp(UA)` → checksum 8 chars + payload 7,408 bytes. **Not** verified on-device: a live `/verify` → token, because Binance is unreachable from Indonesian egress (see below).

Because Chromium/CDP is the only reliable primitive for Cloudflare, prefer: drive the real page → wait for auto-resolve → click checkbox if interactive → read cookies/token from CDP.

## Egress matters more than the solver

Before debugging any solver, check whether the target is reachable at all:

- `curl -s -o /dev/null -w '%{http_code} %{time_total}' <url>` — a 40 s timeout on one host while another answers in 0.3 s is an **egress block**, not a solver bug.
- Indonesia blocks `binance.com` outright (DNS/SNI). The AWS WAF solver's own example target is therefore untestable from here without a relay.
- A `403` with `<title>Just a moment...` is **Cloudflare**, not AWS WAF. Don't feed it to an AWS solver.
- A `403` with size < 2 KB and no `challenge.js` / `gokuProps` markers is usually a plain WAF/geo denial — no challenge exists to solve.

## Ready-made solvers (provenance, if you need a service)

- `sarperavci/CloudflareBypassForScraping` (2.6k★, MIT) — Python, Brave+DrissionPage pool. Endpoints: `GET /cookies?url=&proxy=`, `GET /turnstile?url=&sitekey=`, `GET /html`, mirror mode via `x-hostname` header. Prod-grade: cookie TTL, proxy exit-IP check, concurrency cap.
- `najibyahya/Boterdrop-Solver` (229★, MIT) — FastAPI+Camoufox. `GET /turnstile`, `/clearance`, `/aws-token`, `/recaptchaV3`, `GET /result`. Its AWS route just drives a real page and polls for `aws-waf-token`, retrying with a proxy when CloudFront blocks the host IP (so it is *not* a pure-crypto solver).
- `xKiian/awswaf` (379★, MIT) — the pure-crypto one; 19 commits, not heavily maintained.
- `borys25ol/amazon-location-cookies-service` (48★) — Amazon-specific wrapper around Playwright; only useful for the delivery-country cookie use case.
- `0xMissy22/captcha-solver-global` (11★) — reCAPTCHA/hCaptcha/Turnstile behind a Bearer-authed service on `:8877`; needs `cloakbrowser` (commercial) + Xvfb + systemd.

## Full-provider verdict matrix (verified 2026-11-21, Termux headless_shell Chrome/155, Indonesian mobile egress)

Every row below was mechanically executed, not inferred. Use it to set expectations before spending time on a provider.

| Provider | Path | Result |
|---|---|---|
| Turnstile dummy keys (`1x…AA`, siteverify) | curl siteverify | ✅ **PASS** — deterministic, IP-agnostic |
| Turnstile interactive `3x…FF` | widget in headless | ❌ **BLOCKED** — err `300030` (fingerprint, not IP; UA + UA-CH spoof fails) |
| hCaptcha test keys (`10000000-ffff…0001` + secret `0x000…`) | widget headless + siteverify | ✅ **FULL PASS** — token lands in hidden field `h-captcha-response`, verify `success:true` |
| AWS WAF CAPTCHA (officeworks.com.au) | headless, puzzle solved via CDP | ✅ **PASS** — challenge JS runs, `aws-waf-token` set, verify 200, CLEAR. Needs solve < ~30 s time limit |
| Arkose (cap.guru demo → snap-api.arkoselabs.com) | headless **and** headed Xvfb | ❌ **DENIED ACCESS** — `POST /fc/gt2/public_key/` → `400 {"error":"DENIED ACCESS"}` in BOTH modes. Axis is fingerprint environment (WebGL/GPU or IP), not headless-only |

### Datacenter-IP replication (verified 2026-11-21, Instabox VM, Debian 13 x86_64, Chromium 154 headless + headed Xvfb, IP `152.236.28.27` US Latitude.sh `hosting=true`)

| Test | Result on datacenter IP |
|---|---|
| Turnstile siteverify dummy keys | ✅ **PASS** — same as Termux, IP-agnostic |
| hCaptcha siteverify (3 keysets) | ✅ **PASS** (publisher + enterprise safe, `scoped_uid` returned) |
| Turnstile `3x…FF` widget (headless) | ❌ **BLOCKED** — null token, `ev []` (same as Termux) |
| Arkose demo (headless & headed Xvfb) | ❌ **BLOCKED EARLIER** — `gt2` init is **never sent** (0 requests); frame log shows `error: Failed to load resource: 400`. Arkose flags the datacenter IP **before** the challenge flow starts — harder than on mobile IP |

**Key datacenter finding:** on the VM, `gt2` never appears in the frame network log at all (not a 400-with-body like Termux — the request is killed earlier). Arkose's wall is IP reputation first, environment second.

**VM replication recipe:** resume via MCP `resume_machine`, spawn chromium `--headless=new --remote-debugging-port=9222` (on Chrome 154 without `--remote-allow-origins`, `/json/new?URL` PUT still works). Node 22 built-in WebSocket for CDP. Xvfb preinstalled at `/usr/bin/Xvfb`. Kill all chromium + `rm /tmp/*.mjs` when done, then suspend the VM.

## AWS WAF CAPTCHA solve pattern (the one that worked live)

Distinct from the pure-crypto `aws-waf-token` reverse above — this is the **interactive CAPTCHA** variant, solved in a real headless browser:

1. `curl -si https://target/` → `405` + `x-amzn-waf-action: captcha` confirms AWS WAF CAPTCHA is live (`202` = challenge interstitial).
2. Open in headless → challenge JS auto-runs → click **Begin** via DOM (`document.querySelectorAll('button').find(b => b.innerText === 'Begin').click()`).
3. Puzzle grid: `button.amzn-grid-cell` (3×3). Instruction is in the body text ("Choose all the X").
4. **Time limit ~30 s from puzzle render** — the loop must be ONE pull: screenshot (`Page.captureScreenshot`) → visual classify (cells 1-9 row-by-row → index 0-8) → click cells → click Confirm. All within <10 s total.
5. Submit → `POST <hash>.captcha.awswaf.com/<…>/verify` → 200. Wrong answer = new puzzle (retry is fine, not a ban). Late = "Time limit exceeded". Persistent error after a correct answer = check the network (submit may have failed, "Temporary error").
6. Success = title changes from "Let's confirm you are human" → real page (or a CloudFront 403 from a *different* rule — separate layer, CAPTCHA still cleared).

## Official test-key endpoints

- **Turnstile:** `developers.cloudflare.com/turnstile/troubleshooting/testing` (`1x…AA` pass, `2x…AB` fail, `3x…FF` interactive, secret `1x/2x/3x…AA`)
- **hCaptcha:** sitekey `10000000-ffff-ffff-ffff-000000000001` (publisher pass), `20000000…0002` (enterprise safe), `30000000…0003` (enterprise bot), secret `0x0000000000000000000000000000000000000000`, dummy token `10000000-aaaa-bbbb-cccc-000000000001`. Widget: `js.hcaptcha.com/1/api.js`. Verify: `api.hcaptcha.com/siteverify`.
- **Arkose:** NO public dummy key. Public demo: `test.cap.guru/en/demo/funcap` (embed `iframe.arkoselabs.com`, key `EA4B65CB-594A-438E-B4B5-D0DBA28C9334`). Never hit a key you don't own outside the demo.
- **AWS WAF:** no demo key; find a live target returning `x-amzn-waf-action: captcha` (officeworks.com.au proven, may change).

## Pitfalls

- **Misidentifying the vendor is the #1 time sink.** A 403 with `geo.captcha-delivery.com` is DataDome, not Cloudflare; a 403 with no markers at all means no challenge exists. Use the triage table before touching a solver.
- **A regex that only matches `0x4AAAAAA` misses the official dummy keys** (`1x…AA` always-pass, `2x…AB` always-fail, `3x…AC` invisible). Test pages use dummies; production uses `0x4`. Match `[0-3]x`.
- **Single-use tokens.** `cf-turnstile-response` and the Aliyun `captcha_verify_param` both die on second use. Whoever POSTs first wins — if a page's own JS will spend it, intercept with `Fetch.failRequest` and send it yourself.
- **`cf_clearance` is UA+IP bound.** Replaying from another IP/UA re-challenges. Do not "solve once, spray everywhere".
- **Don't detect success by page text.** Parse the response body / cookie, never grep for `success` / `verified`.
- **`eager` navigation kills the challenge.** So does anything that calls `Page.stopLoading` mid-challenge.
- **Click too early = silent no-op.** Poll until the widget is hydrated (`document.querySelectorAll('button').length > 2`-style checks), then click, then confirm the DOM actually changed.
- **Hardcoded absolute paths in the Python AWS port** (`open("../webgl.json")`) — run it from `python/` or patch the path.

## Self-test (run before trusting any change)

All four run with **zero browser**. `scripts/` ships them.

```bash
~/.hermes/bin/fp-audit 9222                                 # fingerprint of the live browser (needs chrome up)
PY=/data/data/com.termux/files/usr/bin/python3.14
PYTHONPATH=~/pkg314 $PY scripts/test_turnstile_logic.py   # 23 checks, offline fixtures + 1 live
PYTHONPATH=~/pkg314 $PY scripts/test_live_triage.py        # 8 checks, live sites, TLS only
python3 scripts/test_replay_path.py                          # 12 checks, local mock gate
node scripts/probe_nodom.js                                  # proves api.js needs a DOM
```

What each one actually proves:

| Script | Proves |
|---|---|
| `fp-audit` | the browser Cloudflare will see: webdriver/UA/plugins/chrome — run BEFORE any challenge attempt |
| `test_turnstile_logic.py` | classifier separates all 5 gate types; sitekey/action/cData extraction incl. the `turnstile.render()` fallback; naive text-success check false-positives on a challenge prompt |
| `test_live_triage.py` | real pages classify correctly — `demo.turnstile.workers.dev`→turnstile, `crunchyroll.com`→managed, `g2.com`→**datadome**, `example.com`→ok |
| `test_replay_path.py` | token bound to `(action, cData, UA)`, one-shot, unknown token refused |
| `probe_nodom.js` | `api.js` throws `ReferenceError: window is not defined` in bare Node |

## Attribution

Mechanics summarized from MIT-licensed repositories: `sarperavci/CloudflareBypassForScraping`, `xKiian/awswaf`, `najibyahya/Boterdrop-Solver`, `0xMissy22/captcha-solver-global`. No code copied; behavioural notes only. Keep the MIT notice if you lift actual source.
