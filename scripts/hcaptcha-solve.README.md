# hCaptcha solver status — honest read

## What works (verified live, 2026-11-22)

- **Token capture** — hCaptcha production widget (sitekey `a5f74b19-9e45-...`,
  302x79 div) renders inside a clean-fp-chrome browser; `hcaptcha-solve`
  collects `h-captcha-response` and returns a real `P1_eyJhbG...` token
  (2226 chars). Auto-pass mode, no click needed on this key.
- **Blank-page mode** — Fetch interception renders our own widget at the
  target origin (origin-bound token contract, same as turnstile-solve).
- **Fingerprint gate** — same doctrine: dirty browser refused, OOPIF-safe.
- **Widget geometry + screenshot capture** — reads container box from the
  parent page and can `Page.captureScreenshot` the challenge region to PNG.

## What does NOT work yet

- **Vision-assisted interactive challenges** — the solver captures the
  challenge screenshot and saves it, but the "look at the image, pick
  coordinates" step needs a vision-capable model. On the current endpoint
  (`knr/ernie-5-5-flash-preview:free` via 9router-k!ky), `vision_analyze`
  returns "I don't have vision support in this session" — the endpoint does
  not pass image data through. So the click-a-tile loop is implemented but
  unverified end-to-end.
- hCaptcha always-pass dummy key (`1x000...`) renders "config issue" on
  `accounts.hcaptcha.com/demo` — page-specific, not a solver bug.

## Path to close the vision gap

1. Run the session on a vision-capable model (one that actually accepts
   image input through its endpoint), then the vision loop verifies.
2. Or wire the screenshot to a separate vision HTTP API and click from its
   returned coordinates — the solver's click plumbing
   (`Input.dispatchMouseEvent` from parent geometry) is already there.

## How to run

```bash
python3 setup.py
clean-fp-chrome
python3 scripts/fp-audit 9222          # must print VERDICT: CLEAN
python3 scripts/hcaptcha-solve --url https://www.hcaptcha.com/ --json
# → {"ok": true, "token": "P1_eyJhbG...", "mode": "auto-pass"}
```