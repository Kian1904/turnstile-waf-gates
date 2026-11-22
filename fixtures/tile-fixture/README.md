# Tile Fixture — vision-loop test rig

Local, deterministic grid that stands in for a tile-based captcha challenge.
Used to validate the **vision → index → click → verify** loop end-to-end
without touching any third-party anti-bot service.

## What it is

- 3x3 grid of tiles, each an emoji rendered as inline SVG (stable visuals)
- Prompt rendered on the page: *pick all fish & flower tiles*
- Ground truth hardcoded: `EXPECTED = [0, 3, 5, 8]`
- Verdict computed in-page: `window.__fixture.pass` — the page itself is the
  source of truth, never the UI state
- Zero network: served from `file://` — runs identically on any machine

## The loop (what gets validated)

```
screenshot (Page.captureScreenshot)
   → vision_analyze  → returns tile INDICES (not pixels)
   → scripts/tile-click  → maps indices to live DOM geometry,
                           trusted CDP clicks, re-reads geometry
                           before every click
   → --assert "window.__fixture.pass === true"  → page verdict or bust
```

## Reproduce

```bash
# 1. browser up
scripts/clean-fp-chrome && scripts/fp-audit 9222

# 2. open the fixture
#    (navigate any CDP client to file://<repo>/fixtures/tile-fixture/index.html)

# 3. half A — vision step (agent-side):
#    screenshot the page, ask the vision model for indices of fish+flower tiles

# 4. half B — mechanical step:
python3 scripts/tile-click --selector ".tile" --tiles 0,3,5,8 \
    --assert "window.__fixture.pass === true" --json

# adversarial variant: ask vision for the WRONG object class, run tile-click,
# and confirm --assert returns false (the page catches the mismatch)
```

## Verified runs (2026-11-22, Termux/arm64, glm-5.3-flash vision)

| Round | Vision answer | Clicks | Page verdict |
|---|---|---|---|
| 1 — fish & flower | `[0,3,5,8]` | 4 | **PASS** ✅ |
| 2 — adversarial (asked for trees) | `[1,7]` | 2 | **FAIL** — assert correctly false ✅ |
| 2b — same-session recovery | clear + `[0,3,5,8]` | 6 | **PASS** ✅ |

Round 2 is the important one: the mechanical half clicks whatever indices it
is given, and the **page verdict catches the wrong selection**. The loop's
discipline matches the repo doctrine — verdict comes from the page/server,
never from UI state or "the click worked".

## Design note

Vision returns **indices, not pixel coordinates**. Geometry is re-read from
`getBoundingClientRect()` immediately before every click, so scroll,
re-render, or banner overlays cannot produce stale coordinates. Smaller
failure surface than passing pixels around.
