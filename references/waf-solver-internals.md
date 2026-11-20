# AWS WAF solver internals (from `xKiian/awswaf`)

Everything here was read out of the Go and Python sources. Package layout:

```
internal/aws/aws.go            flow: NewAwsWaf → Extract → GetInputs → BuildPayload → Verify
internal/aws/pow.go            HashPoW (sha256) + ComputeScryptNonce
internal/aws/crypto.go         AES-256-GCM seal/open
internal/aws/fingerprint.go    GetFP(userAgent) + encodeWithCRC
internal/aws/structs.go        Verify / Inputs / Fingerprint / Signals / Metrics shapes
internal/aws/captcha/*        captcha.js variant, solved with a vision model
python/awswaf/                 404-line port (aws, crypto, fingerprint, verify)
webgl.json                     GPU table the fingerprint is built from
```

## Struct shapes

`Inputs` (from `GET /inputs?client=browser`):

```json
{ "ChallengeType": "...", "Challenge": { "Input": "..." }, "Difficulty": 0, "gokuProps": {...} }
```

`Verify` (what you POST to `/verify`):

```json
{
  "challenge":  {...},
  "solution":   "<nonce as string>",
  "signals":    [{"Name": "Zoey", "Value": {"Present": "<fp payload>"}}],
  "checksum":   "<crc of fp>" ,
  "existingToken": null,
  "client":     "Browser",
  "domain":     "<domain>" ,
  "metrics":    [{"Name": "2", "Value": 0.42, "Unit": "2"}, ...],
  "gokuProps":  {...}
}
```

`Metrics` — fixed array, units matter (`"2"` vs `"4"`):

| Name | Value | Unit |
|---|---|---|
| 2 | `rand()` | 2 |
| 100..107 | 0 | 2 |
| 103 | 8 | 2 |
| 108 | 1 | 2 |
| 110 | 0 | 2 |
| 111 | 2 | 2 |
| 112 | 0 | 2 |
| 3 | 4 | 2 |
| 7 | 0 | 4 |
| 1 | `rand()*10+10` | 2 |
| 4 | 36.5 | 2 |
| 5 | `rand()` | 2 |
| 6 | `rand()*10+50` | 2 |
| 0 | `rand()*10+130` | 2 |
| 8 | 1 | 4 |

Two entries literally use the name `"undefined"` with value 0 — reproduce that, the server sees it.

## Proof of work

```go
func checkDigest(digest []byte, difficulty int) bool  // difficulty/8 full zero bytes + difficulty%8 zero top bits

HashPoW(challengeInput, checksum string, difficulty int) (string, error):
  combined = challengeInput + checksum
  for nonce := 0; ; nonce++ {
     digest = sha256(combined + strconv.Itoa(nonce))
     if checkDigest(digest, difficulty) { return nonce }
  }

ComputeScryptNonce(challengeInput, checksum string, difficulty int):
  combined = challengeInput + checksum
  for nonce := 0; ; nonce++ {
     result = scrypt(fmt.Sprintf("%s%d", combined, nonce), salt, memoryCost)
     if checkDigest(result, difficulty) { return nonce }
  }
```

`SolveChallenge` dispatches on `challengeType`: scrypt path vs sha256 path. Difficulty is small (single digits to low tens) — the loop is cheap either way.

## Crypto

```go
key = 6f71a512b1e035eaab53d8be73120d3fb68a0ca346b9560aab3e5cdf753d5e98   // static, in-client
iv  = 12 random bytes
out = b64(iv) + "::" + hex(tag) + "::" + hex(ciphertext)
```

AES-256-GCM, no AAD. The Python port uses `cryptography.hazmat.primitives.ciphers.aead.AESGCM` with the same key and the same `iv::tag::ct` format.

## Fingerprint

`GetFP(userAgent)` loads `webgl.json` (a GPU/extension table keyed by renderer string), assembles the `Fingerprint` struct — `metrics`, `plugins`, `screenInfo`, `capabilities` (CSS/JS feature probes), `gpu.web_gl_renderer`, `canvas`, `math`, `stealth`, `automation`, `crypto`, `be` — then `encodeWithCRC` returns `(checksum, payload)`. `checksum` feeds the PoW; `payload` goes into `signals[0].Value.Present`.

Because `webgl.json` is loaded with a **relative** path from the process cwd, run from the repo root (Go) or from `python/` (Python port), or patch the path.

## Header order

`GetInputs` sets `http.HeaderOrderKey` explicitly. Real clients send a specific order; the Python port emulates it with `curl_cffi`'s `impersonate="chrome"` plus a hand-written header dict. If a request works from Go but not from a plain HTTP client, header order and TLS fingerprint are the difference.

## Captcha variant

If the page ships `/captcha.js` instead of `/challenge.js`, it is the interactive AWS WAF captcha. The repo solves it by cropping the puzzle image and asking a vision model (`google/gemini-2.5-flash`) for the answer. That path needs a key; the token/invisible path needs none.

## Practical notes

- Wait and retry: the endpoint occasionally answers with a fresh challenge instead of a token.
- Keep one session per token — the cookie is issued for the fingerprint that produced it.
- CloudFront may block the host IP outright, which looks like "solver broken" but is an egress problem. Retry through a different IP before debugging crypto.
