#!/usr/bin/env python3
"""Create a test today-expanded.json from fresh feed data for publish pipeline testing."""
import json, os, re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(SCRIPT_DIR, "..")
FEED_PATH = os.environ.get(
    "CROSSECT_FEED_PATH",
    os.path.join(REPO_ROOT, "docs", "data", "feeds", "morning.json"),
)
OUTPUT_PATH = os.environ.get(
    "CROSSECT_OUTPUT_PATH",
    os.path.join(REPO_ROOT, "docs", "data", "digests", "today-expanded.json"),
)

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

with open(FEED_PATH) as f:
    feeds = json.load(f)

items = feeds.get("items", [])
print(f"Loaded {len(items)} feed items")


def normalize_url(value=""):
    """Normalize a URL for dedup comparison (mirrors validate-digest-freshness.mjs)."""
    try:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(value)
        # Strip tracking params
        query_params = []
        if parsed.query:
            for param in parsed.query.split("&"):
                key = param.split("=")[0]
                if not re.match(r"^(utm_|fbclid|gclid|mc_cid|mc_eid)", key, re.IGNORECASE):
                    query_params.append(param)
        new_query = "&".join(query_params)
        normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"),
                                 parsed.params, new_query, ""))
        return normalized.lower()
    except Exception:
        return str(value or "").strip().lower()


# Collect all URLs from previously published digests to avoid repeats
def load_previous_urls():
    """Load all URLs from published digests (via index.json)."""
    index_path = os.path.join(REPO_ROOT, "docs", "data", "digests", "index.json")
    previous_urls = set()

    try:
        with open(index_path) as f:
            index = json.load(f)
    except FileNotFoundError:
        print("No index.json found; skipping dedup.")
        return previous_urls

    current_date = datetime.now().strftime("%Y-%m-%d")
    for entry in index.get("digests", []):
        entry_id = str(entry.get("id", ""))
        if entry.get("date") in {"today", current_date} or entry_id in {"today-expanded.json", f"{current_date}-expanded.json"}:
            continue  # skip aliases/current digest when rebuilding today
        digest_file = os.path.join(REPO_ROOT, "docs", "data", "digests", entry["id"])
        try:
            with open(digest_file) as f:
                digest = json.load(f)
            for section in digest.get("sections", []):
                for story in section.get("stories", []):
                    for link in story.get("links", []):
                        url = normalize_url(link if isinstance(link, str) else link.get("url", ""))
                        if url:
                            previous_urls.add(url)
        except FileNotFoundError:
            continue

    return previous_urls


previous_urls = load_previous_urls()
if previous_urls:
    print(f"Loaded {len(previous_urls)} previously published URLs for dedup")

# Group by source domain
from collections import defaultdict
by_source = defaultdict(list)
for item in items:
    link = item.get("url", "") or item.get("link", "")
    if "://" in link:
        domain = link.split("://")[1].split("/")[0].lstrip("www.")
    else:
        domain = link
    by_source[domain].append(item)

print(f"Sources found: {list(by_source.keys())}")

# Build sections - pick top stories from each source category
sections = []

def make_section(name, domains, count=5):
    """Create a section with top stories from given domains."""
    stories = []
    seen_titles = set()
    for domain in domains:
        search_domain = domain.lstrip("www.")
        for item in by_source.get(search_domain.lower(), [])[:count]:
            title = (item.get("title", "") or "").strip()[:150]
            if not title or len(title) < 20 or title in seen_titles:
                continue
            seen_titles.add(title)
            # Skip URLs already published in previous digests
            url = normalize_url(item.get("url", ""))
            if url and url in previous_urls:
                continue
            desc = (item.get("description", "") or "").replace("<[^>]*>", "").strip()[:400]
            stories.append({
                "title": title,
                "summary": desc,
                "links": [{"url": item.get("url", ""), "source": domain}]
            })
    if stories:
        sections.append({"name": name, "stories": stories})

# World / Geopolitics
make_section("World / Geopolitics", ["aljazeera.com", "bbc.com", "bbc.co.uk", "cnn.com"])

# Australia
make_section("Australia", ["abc.net.au", "theguardian.com"], count=2)

# Technology
make_section("Technology", ["theverge.com", "techcrunch.com"], count=4)

# Asia Pacific
make_section("Asia Pacific", ["rappler.com", "newsinfo.inquirer.net", "inquirer.net"])

# Business / Finance
make_section("Business / Finance", ["sj.com", "wsj.com"])

today = datetime.now().strftime("%Y-%m-%d")
digest = {
    "id": f"{today}-expanded",
    "date": today,
    "title": "Daily Source Digest",
    "generatedAt": datetime.now().isoformat(),
    "note": "Daily source-balanced news digest — morning update.",
    "updatedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    "sections": sections
}

total_stories = sum(len(s["stories"]) for s in sections)
print(f"Created {OUTPUT_PATH}")
print(f"  Sections: {len(sections)}")
for s in sections:
    print(f"    - {s['name']}: {len(s['stories'])} stories")
print(f"  Total stories: {total_stories}")

if previous_urls:
    # Count how many feed items were filtered by dedup
    total_candidate = sum(len(by_source.get(d.lstrip("www.").lower(), [])) for d in [
        "aljazeera.com", "bbc.co.uk", "cnn.com", "abc.net.au",
        "theverge.com", "techcrunch.com", "rappler.com", "inquirer.net", "wsj.com"
    ])
    print(f"\nDedup: {len(previous_urls)} previous URLs loaded, filtering repeats from feed")

with open(OUTPUT_PATH, "w") as f:
    json.dump(digest, f, indent=2)
