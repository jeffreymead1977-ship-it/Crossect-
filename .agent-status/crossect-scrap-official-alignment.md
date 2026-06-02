# crossect-scrap-official-alignment

Owner: Dazza
Objective: Remove `Official` as a Crossect political alignment/bias category; regenerate and publish intended changes only; verify local and live data contain zero `Official` bias/alignment labels.
Status: completed and published

## Files inspected
- `scripts/link_metadata.py`
- `docs/app.js`
- `docs/styles.css`
- `docs/index.html`
- `docs/data/digests/*.json`
- `scripts/create-test-digest.py`
- `scripts/publish-digest.sh`

## Files changed
- `scripts/link_metadata.py` — removed `Official` from allowed biases and heuristic alignment cues; official source provenance now falls back to political/source/article prior with basis note; prompts forbid `Official`; guard suppresses any returned `Official`.
- `docs/app.js` — removed `Official` from bias order and maps any legacy Official value to `Unknown/Mixed` for rendering.
- `docs/index.html` — bumped app.js cache buster to `20260602-no-official-alignment`.
- `docs/data/digests/2026-05-16-expanded.json` through `2026-05-22-expanded.json` — re-enriched 39 legacy links that had `bias`/`alignment: Official`.
- `.agent-status/crossect-scrap-official-alignment.md` — status log.

## Commands run
- `pwd && git status --short`
- searched `Official` in `scripts/link_metadata.py`, `docs/app.js`, `docs/styles.css`, and digest JSON
- `python3 -m py_compile scripts/link_metadata.py scripts/create-test-digest.py`
- `node --check docs/app.js`
- direct sample tests for White House/gov.uk official statements and BBC `officials said` article
- re-enrichment script over `docs/data/digests/*-expanded.json` plus `today-expanded.json`
- local JSON verification script: zero `bias/alignment == Official`
- `node scripts/validate-digest-freshness.mjs ...` for changed digests and current dated digest
- explicit `git add -- <intended files only>`
- `git commit -m "Scrap Official alignment category"`
- `git pull --rebase --autostash origin main && git push origin main`
- GitHub Pages fetch/parse for index and listed digests
- GitHub Pages `index.html` cache-buster check

## Verification results
- Python compile: passed.
- Node syntax check: passed.
- Official samples: White House => `Right`; gov.uk with left cues => `Left`; gov.uk no cues => `Unknown/Mixed` with `official-source-provenance` basis.
- BBC `officials said` sample: `Center`.
- Local digest JSON: `Official bias/alignment matches: 0`.
- Live GitHub Pages listed digest JSON: `Official bias/alignment matches 0` across 10 indexed digests.
- Live GitHub Pages app cache buster includes `app.js?v=20260602-no-official-alignment`.
- Published commit: `05bd0ec Scrap Official alignment category`.

## Errors
- Initial multi-file patch failed because cache-buster string differed and duplicate prompt strings needed more specific replacement. Re-applied as targeted replacements.
- Freshness validation for historical `2026-05-17-expanded.json` exits 1 due pre-existing Australia-heavy mix (`Australia stories: 9/17 (53%)`, `ABC Australia 20/36 (56%)`). This task only changed Official labels; current dated digest freshness passed.

## Current blocker
- None.

## Next action
- None unless Jeff wants historical digest source-mix/freshness repaired separately.
