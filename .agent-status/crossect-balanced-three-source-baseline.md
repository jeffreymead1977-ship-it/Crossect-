# crossect-balanced-three-source-baseline

- owner: Barry
- chosen worker: Barry supervisor-side completion after Dazza likely interrupted by power failure
- objective: Finish Jeff's editorial baseline so Crossect aims for multi-publisher story clusters with left/center/right coverage where feed data safely supports it.
- current status: implemented and verified locally against an expanded fetched feed; not committed or published.

## Files inspected

- `scripts/create-test-digest.py`
- `scripts/link_metadata.py`
- `scripts/feeds.txt`
- `scripts/fetch-rss.sh`
- `/tmp/crossect-expanded-feed.json`
- `/tmp/crossect-balanced-test.json`

## Files changed

- `scripts/create-test-digest.py`
  - Replaced source-by-source one-link story selection with token-based story clustering.
  - Added section configs with explicit allowed sources to prevent Guardian Australia stories leaking into Technology/Business.
  - Added left/center/right perspective helpers.
  - Added cluster link selection that prefers one source from left, center, and right when a genuine same-story cluster contains them.
  - Added section story selection that preserves perspective diversity so right/lean-right coverage is not crowded out.
  - Added cross-section URL de-duplication.
  - Added sports filtering by URL/source/title, including Arsenal/Gooner cases found during verification.
  - Fixed the old `lstrip("www.")` domain bug by using `removeprefix("www.")`; `lstrip` turned `wsj.com` into `sj.com`.
  - Extended source-balance diagnostics with total links, average links/story, per-story perspective presence, and per-link perspective totals.
- `scripts/feeds.txt`
  - Added verified free RSS feeds: Fox News, New York Post, Washington Examiner, Washington Times, National Review, Breitbart, Daily Wire, Spectator Australia.
- `scripts/link_metadata.py`
  - Added domain and source-name metadata for the new right/lean-right feeds.

## Commands run

```text
pwd && git status --short && git diff -- scripts/create-test-digest.py
```

```text
python3 -m py_compile scripts/create-test-digest.py scripts/link_metadata.py
```

```text
bash scripts/fetch-rss.sh /tmp/crossect-expanded-feed.json scripts/feeds.txt
```

Result: fetched 615 items from 19 sources including right/lean-right sources.

```text
CROSSECT_FEED_PATH=/tmp/crossect-expanded-feed.json CROSSECT_OUTPUT_PATH=/tmp/crossect-balanced-test.json CROSSECT_RATING_MODE=heuristic CROSSECT_SUMMARY_MODE=heuristic python3 scripts/create-test-digest.py
```

Result summary:

```text
Section World / Geopolitics: candidates=288, clusters=250, selected=7, selectedSources=BBC World,Daily Wire,Washington Times; BBC World,Daily Wire; Al Jazeera,BBC World; BBC World,Washington Times; Breitbart,Fox News,Washington Times; Washington Examiner,Washington Times; Breitbart,Fox News
Section Australia: candidates=133, clusters=71, selected=4, selectedSources=Spectator Australia; ABC Australia; The Guardian Australia; Spectator Australia
Section Technology: candidates=72, clusters=65, selected=5, selectedSources=The Guardian Technology,TechCrunch,The Verge; The Verge,TechCrunch; The Guardian Technology; The Guardian Technology; The Guardian Technology
Section Asia Pacific: candidates=50, clusters=39, selected=5, selectedSources=Philippine Daily Inquirer,Rappler World; Philippine Daily Inquirer; Philippine Daily Inquirer; Philippine Daily Inquirer; Philippine Daily Inquirer
Section Business / Finance: candidates=71, clusters=67, selected=5, selectedSources=Wall Street Journal; TechCrunch; The Guardian Technology; Wall Street Journal; Wall Street Journal

Source-balance baseline report (non-blocking):
  Stories with 3+ links and left/center/right coverage: 0/26
  Total links: 39; average links/story: 1.50
  Story perspective presence: left=8, center=13, right=11, unknown=0
  Link perspective totals: left=9, center=14, right=16, unknown=0
  WARNING: 23 stories have fewer than 3 source links.
  WARNING: 26 stories are missing one or more left/center/right perspectives.
```

```text
node scripts/validate-digest-freshness.mjs /tmp/crossect-balanced-test.json ./docs/data/digests
```

Result:

```text
Freshness check 2026-06-03-expanded vs 2026-06-02-expanded
Repeated URLs: 0/39 (0%)
Similar story titles: 0/26 (0%)
Australia stories: 4/26 (15%)
Largest journalism source family: The Guardian 6/39 (15%)
```

Additional verification:

```text
VERIFY date= 2026-06-03 stories= 26
duplicate urls= 0
sports title hits= []
link histogram= {3: 3, 2: 7, 1: 16}
balanced 3-perspective stories= 0
stories with right links= 11
total bucket links= {'center': 14, 'right': 16, 'left': 9}
```

## Errors

- Initial verification accidentally ran the Node `.mjs` validator with `python3`, producing:

```text
  File "/Users/e4042381/github/crossect-/scripts/validate-digest-freshness.mjs", line 1
    import fs from "node:fs/promises";
              ^
SyntaxError: invalid syntax
```

- Corrected by running the validator with `node`, which passed.

## Fixes attempted

- Fixed the original `lstrip("www.")` bug that prevented `wsj.com` from being selected correctly.
- Added source-name filters to avoid broad `theguardian.com` domain pulling Australia stories into Technology/Business.
- Added sports-title exclusions after Spectator Australia Arsenal/Gooner items appeared in the test digest.

## Current blocker

- None for the code-level baseline.
- The generated test feed still had zero fully balanced left+center+right clusters because the fetched RSS headlines/excerpts did not contain enough genuine same-story overlap across all three perspectives. The code now aims for that where possible and reports when it is not achieved, instead of forcing unrelated items together.

## Next recommended action

- Run the normal Crossect fetch/build/publish chain when ready. The next fetched digest should include the new right/lean-right feed pool and the non-blocking source-balance report.
- Do not publish automatically from this status note; final live publish should be a deliberate separate step.
