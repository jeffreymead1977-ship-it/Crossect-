#!/usr/bin/env bash
# publish-digest.sh — Full digest publication pipeline for Crossect News
# Runs: image enrichment → freshness validation → git commit/push
# Bash port of the original publish-digest.ps1 with added enrichment/validation steps

set -euo pipefail

export GIT_TERMINAL_PROMPT=0

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Digest date — default to today if no argument provided
DIGEST_DATE="${1:-$(date +%Y-%m-%d)}"

echo "=== Crossect Publish Pipeline ==="
echo "Digest date: $DIGEST_DATE"
echo ""

# Step 0: Get current branch and origin URL
BRANCH=$(git branch --show-current 2>/dev/null | tr -d '[:space:]')
if [ -z "$BRANCH" ]; then
  BRANCH="main"
fi

ORIGIN=$(git remote get-url origin 2>/dev/null | tr -d '[:space:]')
if [ -z "$ORIGIN" ]; then
  echo "ERROR: No git remote named origin is configured." >&2
  exit 1
fi

# Step 1: Check if there are any changes in data/digests
CHANGED_DIGEST_FILES=$(git status --porcelain -- data/digests)
if [ -z "$CHANGED_DIGEST_FILES" ]; then
  echo "No digest changes to publish."
  exit 0
fi

echo "Found changed digest files:"
echo "$CHANGED_DIGEST_FILES"
echo ""

# If the only change is today-expanded.json (LLM job output), rename it first
DIGEST_PATH="$REPO_ROOT/data/digests/${DIGEST_DATE}-expanded.json"
if [ ! -f "$DIGEST_PATH" ]; then
  TODAY_FILE="$REPO_ROOT/data/digests/today-expanded.json"
  if [ -f "$TODAY_FILE" ]; then
    echo "Found today-expanded.json — renaming to $DIGEST_DATE-expanded.json..."
    cp "$TODAY_FILE" "$DIGEST_PATH"
    git add -- "$DIGEST_PATH"
  fi
fi

# Step 2: Enrich images (download/cache article images for GitHub Pages)
if [ -f "$DIGEST_PATH" ]; then
  echo "Step 1/3: Running image enrichment..."
  node ./scripts/enrich-digest-images.mjs "$DIGEST_PATH" || {
    echo "WARNING: Image enrichment failed or had issues. Continuing anyway." >&2
  }
  echo "Image enrichment complete."
else
  echo "No expanded digest found at $DIGEST_PATH — skipping image enrichment."
fi

# Step 3: Validate digest freshness
if [ -f "$DIGEST_PATH" ]; then
  echo ""
  echo "Step 2/3: Validating digest freshness..."
  VALIDATION_OK=true
  node ./scripts/validate-digest-freshness.mjs "$DIGEST_PATH" "./data/digests" || VALIDATION_OK=false
  
  if [ "$VALIDATION_OK" = false ]; then
    echo "ERROR: Digest freshness validation failed. Regenerate $DIGEST_DATE with fresher current-day sources before publishing." >&2
    exit 1
  fi
  echo "Digest freshness validated OK."
else
  echo ""
  echo "No expanded digest found at $DIGEST_PATH — skipping freshness check."
fi

# Step 4: Update index.json if it exists (metadata for the app)
INDEX_JSON="$REPO_ROOT/data/digests/index.json"
if [ -f "$INDEX_JSON" ]; then
  echo ""
  echo "Step 3/3: Updating index.json..."
  # Rebuild index.json with latest digest info
  python3 << PYEOF
import json, os, glob

digests_dir = "$DIGEST_PATH".rsplit("/", 1)[0]
index_path = "$INDEX_JSON"

# Load existing index or create new
if os.path.exists(index_path):
    with open(index_path) as f:
        idx = json.load(f)
else:
    idx = {"digests": []}

# Find all expanded digests and sort by date (newest first)
digest_files = sorted(glob.glob(os.path.join(digests_dir, "*-expanded.json")), reverse=True)

recent_digests = []
for df in digest_files[:10]:  # Keep last 10
    basename = os.path.basename(df)
    date_str = basename.replace("-expanded.json", "")
    try:
        with open(df) as f:
            data = json.load(f)
        sections = data.get("sections", [])
        total_stories = sum(len(s.get("stories", [])) for s in sections)
        recent_digests.append({
            "date": date_str,
            "stories": total_stories,
            "sections": len(sections),
            "filename": basename
        })
    except:
        pass

idx["digests"] = recent_digests
idx["lastUpdated"] = "$DIGEST_DATE"

with open(index_path, "w") as f:
    json.dump(idx, f, indent=2)

print(f"  Updated index.json with {len(recent_digests)} digest entries")
PYEOF
else
  echo ""
  echo "No index.json found — skipping update."
fi

# Step 5: Git operations (add, commit, pull with rebase, push)
echo ""
echo "--- Git Operations ---"

git add -- data/digests
if [ -f "$INDEX_JSON" ]; then
  git add -- data/digests/index.json
fi

# Check if there are staged changes
if ! git diff --cached --quiet -- data/digests; then
  : # Changes exist, continue with commit
else
  echo "No staged digest changes to publish."
  exit 0
fi

git commit -m "Update daily news digest $DIGEST_DATE"

# Stash any unstaged changes before pulling (e.g., feed data from earlier cron jobs)
STASHED=false
if ! git diff --quiet; then
  git stash push -m "crossect-auto-stash-before-pull"
  STASHED=true
fi

git pull --rebase origin "$BRANCH"

# Re-apply stashed changes if we stashed anything
if [ "$STASHED" = true ]; then
  git stash pop
fi

git push origin "$BRANCH"

echo ""
echo "=== Published daily news digest $DIGEST_DATE to $ORIGIN on $BRANCH ==="
