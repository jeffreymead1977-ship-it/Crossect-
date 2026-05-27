#!/usr/bin/env python3
"""Create a test today-expanded.json from fresh feed data for publish pipeline testing."""
import json, os
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(SCRIPT_DIR, "..")
FEED_PATH = os.path.join(REPO_ROOT, "docs", "data", "feeds", "morning.json")
OUTPUT_PATH = os.path.join(REPO_ROOT, "docs", "data", "digests", "today-expanded.json")

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

with open(FEED_PATH) as f:
    feeds = json.load(f)

items = feeds.get("items", [])
print(f"Loaded {len(items)} feed items")

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
            desc = (item.get("description", "") or "").replace("<[^>]*>", "").strip()[:400]
            stories.append({
                "title": title,
                "summary": desc,
                "links": [{"url": item.get("url", ""), "source": domain}]
            })
    if stories:
        sections.append({"name": name, "stories": stories})

# World / Geopolitics
make_section("World / Geopolitics", ["aljazeera.com", "bbc.co.uk", "cnn.com"])

# Australia
make_section("Australia", ["abc.net.au"])

# Technology
make_section("Technology", ["theverge.com", "techcrunch.com"])

# Asia Pacific
make_section("Asia Pacific", ["rappler.com", "inquirer.net"])

# Business / Finance
make_section("Business / Finance", ["wsj.com"])

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

with open(OUTPUT_PATH, "w") as f:
    json.dump(digest, f, indent=2)
