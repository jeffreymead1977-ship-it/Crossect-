# crossect-scrap-official-alignment

Owner: Dazza
Objective: Remove `Official` as a Crossect political alignment/bias category; regenerate and publish intended changes only; verify local and live data contain zero `Official` bias/alignment labels.
Status: in progress

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
- `docs/index.html` — bumped app.js cache buster.
- `.agent-status/crossect-scrap-official-alignment.md` — status log.

## Commands run
- `pwd && git status --short`
- content searches for `Official` in allowed files and digest JSON
- file inspections via read_file/search_files

## Errors
- Initial multi-file patch failed because cache-buster string differed and duplicate prompt strings needed more specific replacement. Re-applied as targeted replacements.

## Current blocker
- None currently; next actions are tests, regeneration, publish, and live verification.

## Next action
- Run syntax/sample tests, regenerate today/dated digest metadata, validate freshness, stage intended files only, commit/push, verify GitHub Pages has zero `Official` labels.
