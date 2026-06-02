# crossect-balanced-three-source-baseline-review

- owner: Barry
- chosen worker: Dazza (local LM Studio)
- objective: Review and verify the source-balance baseline implementation in Crossect — confirm correct domain normalization, conservative clustering, left/center/right preference where genuinely available, non-blocking reporting, sports filtering, and duplicate URL handling.
- current status: reviewed; no code defects found requiring fixes. Implementation is sound.

## Files inspected

- `scripts/create-test-digest.py` (full review of 532 lines)
- `scripts/feeds.txt` (19 feeds including 7 right/lean-right additions)
- `scripts/link_metadata.py` (SOURCE_METADATA domain and source-name entries for new feeds)
- `.agent-status/crossect-balanced-three-source-baseline.md` (previous status from Barry's work)
- `docs/data/feeds/morning.json` (current feed data — left/center only, pre-right-feeds fetch)
- `docs/data/digests/today-expanded.json` (current digest — 26 stories, 30 links)

## Files changed

**None.** No defects were found that required edits. The implementation is correct as-is.

## Commands run

```text
cd /Users/e4042381/github/crossect- && pwd && git status --short
```
Result: confirmed working directory, 5 modified files (create-test-digest.py, feeds.txt, link_metadata.py + feed JSONs).

```text
git diff HEAD -- scripts/create-test-digest.py
```
Result: large diff showing full rewrite from source-by-source selection to token-based clustering with perspective-aware balancing.

```text
git diff HEAD -- scripts/feeds.txt
```
Result: 7 right/lean-right feeds added (Fox News, NY Post, Washington Examiner, Washington Times, National Review, Breitbart, Daily Wire) + Spectator Australia.

```text
git diff HEAD -- scripts/link_metadata.py
```
Result: domain and source-name metadata entries for all new right/lean-right sources with correct bias labels.

```text
python3 -m py_compile scripts/create-test-digest.py scripts/link_metadata.py
```
Result: EXIT_CODE=0 — syntax check passes cleanly.

```text
bash scripts/fetch-rss.sh /tmp/crossect-test-feed.json scripts/feeds.txt
```
Result: fetched 615 items from 19 sources including all right/lean-right feeds.

```text
CROSSECT_FEED_PATH=/tmp/crossect-test-feed.json CROSSECT_OUTPUT_PATH=/tmp/crossect-balanced-fresh.json CROSSECT_RATING_MODE=heuristic CROSSECT_SUMMARY_MODE=feed python3 scripts/create-test-digest.py
```
Result: 26 stories, 39 links. Source-balance report shows right coverage present (16 right links vs 9 left, 14 center).

```text
node scripts/validate-digest-freshness.mjs /tmp/crossect-balanced-fresh.json ./docs/data/digests
```
Result: Repeated URLs: 0/39 (0%), Similar story titles: 0/26 (0%). Freshness check passes.

```text
python3 /tmp/inspect-digest.py docs/data/digests/today-expanded.json
```
Current digest metrics: 26 stories, 30 links, 0 duplicates, 0 sports hits, {1:23, 2:2, 3:1} histogram, 4 right-link stories.

```text
python3 /tmp/inspect-digest.py /tmp/crossect-balanced-fresh.json
```
Fresh digest metrics: 26 stories, 39 links, 0 duplicates, 0 sports hits, {1:16, 2:7, 3:3} histogram, 11 right-link stories.

## Raw errors

None. All commands completed successfully (exit code 0).

## Fixes attempted

No fixes needed. Code review confirmed:

1. **Domain normalization**: `source_domain()` uses `.removeprefix("www.")` — no `lstrip("www.")` bug remains anywhere in the repo (verified with grep).
2. **Conservative same-story clustering**: Jaccard threshold of 0.20 with minimum overlap of 4 tokens (or 0.16 with 5+ overlap) prevents fake balance from unrelated articles.
3. **Left/center/right preference**: `make_story_from_links()` picks one source from each perspective first when a genuine cluster contains them, then fills remaining slots up to MAX_LINKS_PER_STORY=6.
4. **Per-section source balancing**: `select_balanced_stories()` prioritizes genuinely balanced clusters first, then ensures at least one story per broad perspective where available, preventing left/center feeds from crowding out right coverage.
5. **Non-blocking baseline reporting**: `report_source_balance()` prints diagnostics after digest generation without raising errors or blocking the pipeline.
6. **Sports filtering**: `is_sports_item()` checks URL paths, source names, and titles for sports keywords including Arsenal/Gooner cases found in Spectator Australia data. Zero sports hits in generated digests.
7. **Duplicate URL handling**: URLs normalized via query param stripping (utm_, fbclid, etc.) before dedup comparison. Zero duplicates across both test runs.

## Current blocker

None. The implementation is complete and correct.

The zero fully balanced stories (left+center+right in a single story) is expected behavior — RSS headlines from different outlets rarely share enough token overlap to be classified as the same story by conservative clustering thresholds. This is by design: the code does not force unrelated articles together just to satisfy a metric. With real-world RSS data, genuine multi-perspective clusters are rare but do occur (the World section shows some 2-link cross-perspective stories like BBC+Daily Wire).

## Next action

The implementation is ready for production use. When Barry or Jeff runs the normal fetch/build/publish chain:
1. `bash scripts/fetch-rss.sh` will pull all 19 feeds including right/lean-right sources
2. `python3 scripts/create-test-digest.py` will generate a digest with source-balance diagnostics
3. The non-blocking report will show actual balance metrics for monitoring

No further code changes are needed at this time.
