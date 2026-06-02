#!/usr/bin/env python3
"""Create today-expanded.json from fresh feed data for the publish pipeline.

The builder now prefers genuine multi-publisher story clusters where feed text
makes that safe. Jeff's editorial baseline is aspirational, not a hard gate:
aim for at least three publishers per story spanning left/center/right when
available, but never force unrelated articles into one story just to satisfy a
metric.
"""
import json
import os
import re
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse, urlunparse

from link_metadata import (
    enrich_digest_link_metadata,
    enrich_digest_story_summaries,
    enrich_link_metadata,
    missing_required_link_metadata,
)

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


STOPWORDS = {
    "about", "after", "again", "against", "amid", "among", "and", "are", "around",
    "as", "at", "back", "be", "been", "before", "being", "but", "by", "can",
    "could", "did", "do", "does", "during", "for", "from", "has", "have", "how",
    "in", "into", "is", "it", "its", "more", "new", "news", "not", "of", "on",
    "over", "says", "than", "that", "the", "their", "they", "this", "to", "up",
    "us", "was", "what", "when", "where", "who", "why", "will", "with", "world",
}

PERSPECTIVE_GROUPS = {
    "left": {"Left", "Lean Left"},
    "center": {"Center"},
    "right": {"Right", "Lean Right"},
}
PERSPECTIVE_ORDER = ("left", "center", "right", "unknown")
MAX_LINKS_PER_STORY = 6


SECTION_CONFIGS = [
    {
        "name": "World / Geopolitics",
        "domains": [
            "aljazeera.com", "bbc.com", "bbc.co.uk", "cnn.com", "foxnews.com",
            "nypost.com", "washingtonexaminer.com", "washingtontimes.com",
            "nationalreview.com", "breitbart.com", "dailywire.com",
        ],
        "sources": {
            "Al Jazeera", "BBC World", "CNN Top Stories", "Fox News", "New York Post",
            "Washington Examiner", "Washington Times", "National Review", "Breitbart", "Daily Wire",
        },
        "count": 7,
    },
    {
        "name": "Australia",
        "domains": ["abc.net.au", "theguardian.com", "spectator.com.au"],
        "sources": {"ABC Australia", "The Guardian Australia", "Spectator Australia"},
        "count": 4,
    },
    {
        "name": "Technology",
        "domains": ["theverge.com", "techcrunch.com", "theguardian.com"],
        "sources": {"The Verge", "TechCrunch", "The Guardian Technology"},
        "count": 5,
    },
    {
        "name": "Asia Pacific",
        "domains": ["rappler.com", "newsinfo.inquirer.net", "inquirer.net"],
        "sources": {"Rappler World", "Philippine Daily Inquirer"},
        "count": 5,
    },
    {
        "name": "Business / Finance",
        "domains": ["wsj.com", "sj.com", "techcrunch.com", "theguardian.com"],
        "sources": {"Wall Street Journal", "TechCrunch", "The Guardian Technology"},
        "count": 5,
    },
]


def normalize_url(value=""):
    """Normalize a URL for dedup comparison (mirrors validate-digest-freshness.mjs)."""
    try:
        parsed = urlparse(value)
        query_params = []
        if parsed.query:
            for param in parsed.query.split("&"):
                key = param.split("=")[0]
                if not re.match(r"^(utm_|fbclid|gclid|mc_cid|mc_eid)", key, re.IGNORECASE):
                    query_params.append(param)
        new_query = "&".join(query_params)
        normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), parsed.params, new_query, ""))
        return normalized.lower()
    except Exception:
        return str(value or "").strip().lower()


def source_domain(item):
    link = item.get("url", "") or item.get("link", "")
    try:
        host = urlparse(link).hostname or ""
    except Exception:
        host = ""
    return host.lower().removeprefix("www.") or str(link).split("://")[-1].split("/")[0].lower().removeprefix("www.")


def strip_html(value):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def item_text(item):
    return " ".join(
        strip_html(item.get(field))
        for field in ("title", "summary", "description", "source")
        if item.get(field)
    )


def title_tokens(item):
    text = item_text(item).lower()
    tokens = []
    for token in re.findall(r"[a-z0-9][a-z0-9'-]{2,}", text):
        token = token.strip("'-")
        if len(token) < 3 or token in STOPWORDS:
            continue
        # Crude singular normalisation helps match headline variants without NLP.
        if len(token) > 4 and token.endswith("s"):
            token = token[:-1]
        tokens.append(token)
    return set(tokens)


def story_similarity(tokens_a, tokens_b):
    if not tokens_a or not tokens_b:
        return 0.0, 0
    overlap = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return (overlap / union if union else 0.0), overlap


def likely_same_story(tokens_a, tokens_b):
    score, overlap = story_similarity(tokens_a, tokens_b)
    # RSS titles are short and written differently by outlet. Require enough token
    # overlap to avoid fake balance, with a slightly lower Jaccard threshold for
    # longer titles that share four or more meaningful terms.
    return overlap >= 4 and score >= 0.20 or overlap >= 5 and score >= 0.16


def is_sports_item(item):
    url = str(item.get("url") or item.get("link") or "")
    source = str(item.get("source") or "")
    title = str(item.get("title") or "")
    return bool(
        re.search(r"/(sports?|football|soccer|nfl|nba|mlb|nhl|cricket|rugby|afl)(/|$)", url, flags=re.IGNORECASE)
        or re.search(r"\b(sport|sports|football|soccer|nfl|nba|mlb|nhl|cricket|rugby|afl)\b", source, flags=re.IGNORECASE)
        or re.search(r"\b(world cup|premier league|grand prix|tennis|football|soccer|nfl|nba|cricket|rugby|afl|arsenal|gooner|gooners)\b", title, flags=re.IGNORECASE)
    )


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


# Group feed candidates by source domain.
by_source = defaultdict(list)
for item in items:
    by_source[source_domain(item)].append(item)

print(f"Sources found: {list(by_source.keys())}")


def item_to_link(item, fallback_domain):
    title = strip_html(item.get("title", ""))[:180]
    desc = strip_html(item.get("description", "") or item.get("summary", ""))[:500]
    return enrich_link_metadata({
        "url": item.get("url", ""),
        "source": item.get("source") or fallback_domain,
        "headline": title,
        "excerpt": desc,
        "imageUrl": item.get("imageUrl", ""),
        "imageAlt": item.get("imageAlt", "") or title,
    })


def perspective_for_link(link):
    """Return coarse left/center/right perspective for a digest link, if known."""
    bias = str(link.get("bias") or link.get("alignment") or link.get("sourceBias") or "").strip()
    for perspective, labels in PERSPECTIVE_GROUPS.items():
        if bias in labels:
            return perspective
    return "unknown"


def link_sort_key(link):
    perspective_rank = {"left": 0, "center": 1, "right": 2, "unknown": 3}.get(perspective_for_link(link), 3)
    source = str(link.get("outlet") or link.get("source") or "")
    return (perspective_rank, source.lower(), str(link.get("headline") or "").lower())


def make_story_from_links(title, summary, links):
    selected = []
    seen_urls = set()
    seen_sources = set()
    links = sorted(links, key=link_sort_key)

    def add_link(link):
        url = normalize_url(link.get("url", ""))
        source = str(link.get("outlet") or link.get("source") or "").strip().lower()
        if not url or url in seen_urls or source in seen_sources:
            return False
        selected.append(link)
        seen_urls.add(url)
        seen_sources.add(source)
        return True

    # Pick one source from each perspective first to meet the editorial baseline
    # whenever a real cluster contains those perspectives.
    for perspective in ("left", "center", "right"):
        for link in links:
            if perspective_for_link(link) == perspective and add_link(link):
                break
    for link in links:
        if len(selected) >= MAX_LINKS_PER_STORY:
            break
        add_link(link)

    return {
        "title": title,
        "summary": summary,
        "links": selected,
    }


def cluster_items(candidates):
    clusters = []
    for item in candidates:
        tokens = title_tokens(item)
        best_index = None
        best_score = 0.0
        for idx, cluster in enumerate(clusters):
            score, _overlap = story_similarity(tokens, cluster["tokens"])
            if score > best_score and likely_same_story(tokens, cluster["tokens"]):
                best_index = idx
                best_score = score
        if best_index is None:
            clusters.append({"items": [item], "tokens": set(tokens)})
        else:
            clusters[best_index]["items"].append(item)
            clusters[best_index]["tokens"].update(tokens)
    return clusters


def cluster_score(story):
    links = [link for link in story.get("links", []) if isinstance(link, dict)]
    perspectives = {perspective_for_link(link) for link in links}
    unique_sources = {str(link.get("outlet") or link.get("source") or "").strip().lower() for link in links}
    balance_score = sum(1 for p in ("left", "center", "right") if p in perspectives)
    right_bonus = 1 if "right" in perspectives else 0
    return (balance_score, min(len(unique_sources), 3), right_bonus, len(unique_sources), len(links), len(story.get("summary", "")))


def select_balanced_stories(stories, count):
    """Select section stories while preserving perspective diversity.

    This does not fabricate left/center/right balance within a story. It simply
    stops high-volume left/center feeds from crowding out available right-leaning
    coverage when all remaining clusters are single-source.
    """
    ordered = sorted(stories, key=cluster_score, reverse=True)
    selected = []
    selected_ids = set()

    def story_id(story):
        links = [link for link in story.get("links", []) if isinstance(link, dict)]
        return normalize_url(links[0].get("url", "")) if links else story.get("title", "")

    def add_story(story):
        sid = story_id(story)
        if not sid or sid in selected_ids or len(selected) >= count:
            return False
        selected.append(story)
        selected_ids.add(sid)
        return True

    # First take any genuinely balanced/multi-perspective clusters.
    for story in ordered:
        perspectives = {perspective_for_link(link) for link in story.get("links", []) if isinstance(link, dict)}
        if len(story.get("links", [])) >= 3 and all(p in perspectives for p in ("left", "center", "right")):
            add_story(story)

    # Then ensure at least one story from each broad perspective where available.
    for perspective in ("right", "center", "left"):
        for story in ordered:
            perspectives = {perspective_for_link(link) for link in story.get("links", []) if isinstance(link, dict)}
            if perspective in perspectives and add_story(story):
                break

    for story in ordered:
        if len(selected) >= count:
            break
        add_story(story)
    return selected


def make_section(name, domains, count=5, allowed_sources=None):
    """Create a section that prefers real multi-source clusters where possible."""
    allowed_source_names = {str(source).strip() for source in (allowed_sources or set())}
    candidates = []
    candidate_source_counts = defaultdict(int)
    seen_candidate_urls = set()
    skipped_previous = 0
    skipped_sports = 0
    skipped_section_duplicate = 0
    skipped_source = 0
    for domain in domains:
        search_domain = domain.lower().removeprefix("www.")
        for item in by_source.get(search_domain, []):
            source_name = str(item.get("source") or "").strip()
            if allowed_source_names and source_name not in allowed_source_names:
                skipped_source += 1
                continue
            title = strip_html(item.get("title", ""))[:180]
            if not title or len(title) < 20:
                continue
            url = normalize_url(item.get("url", ""))
            if not url or url in seen_candidate_urls:
                continue
            if url in global_selected_urls:
                skipped_section_duplicate += 1
                continue
            if url in previous_urls:
                skipped_previous += 1
                continue
            if is_sports_item(item):
                skipped_sports += 1
                continue
            seen_candidate_urls.add(url)
            candidate_source_counts[source_name] += 1
            candidates.append(item)

    clusters = cluster_items(candidates)
    stories = []
    for cluster in clusters:
        links = [item_to_link(item, source_domain(item)) for item in cluster["items"]]
        if not links:
            continue
        # Use the most central/longest headline in the cluster as the display title.
        title_item = max(cluster["items"], key=lambda item: (len(title_tokens(item) & cluster["tokens"]), len(strip_html(item.get("title", "")))))
        title = strip_html(title_item.get("title", ""))[:180]
        summary = strip_html(title_item.get("description", "") or title_item.get("summary", ""))[:700]
        story = make_story_from_links(title, summary, links)
        if story["links"]:
            stories.append(story)

    selected = select_balanced_stories(stories, count)
    candidate_perspective_counts = defaultdict(int)
    for story in stories:
        for perspective in {perspective_for_link(link) for link in story.get("links", []) if isinstance(link, dict)}:
            candidate_perspective_counts[perspective] += 1
    for story in selected:
        for link in story.get("links", []):
            if isinstance(link, dict):
                url = normalize_url(link.get("url", ""))
                if url:
                    global_selected_urls.add(url)
    if selected:
        selected_sources = "; ".join(
            ",".join(str(link.get("source") or link.get("outlet") or "") for link in story.get("links", []) if isinstance(link, dict))
            for story in selected
        )
        print(
            f"Section {name}: candidates={len(candidates)}, clusters={len(clusters)}, "
            f"selected={len(selected)}, dedupSkipped={skipped_previous}, "
            f"sportsSkipped={skipped_sports}, crossSectionSkipped={skipped_section_duplicate}, "
            f"sourceSkipped={skipped_source}, candidateSourceCounts={dict(candidate_source_counts)}, "
            f"candidatePerspectiveCounts={dict(candidate_perspective_counts)}, "
            f"selectedSources={selected_sources}"
        )
        sections.append({"name": name, "stories": selected})


sections = []
global_selected_urls = set()
for section_config in SECTION_CONFIGS:
    make_section(
        section_config["name"],
        section_config["domains"],
        section_config["count"],
        section_config.get("sources"),
    )


def report_source_balance(digest):
    """Print non-blocking source-balance diagnostics for the generated digest."""
    story_count = 0
    balanced_count = 0
    link_count = 0
    digest_perspectives = defaultdict(int)
    total_links_by_perspective = defaultdict(int)
    short_stories = []
    missing_perspective_stories = []

    for section in digest.get("sections", []):
        for story in section.get("stories", []):
            story_count += 1
            links = [link for link in story.get("links", []) if isinstance(link, dict)]
            link_count += len(links)
            perspectives = {perspective_for_link(link) for link in links}
            for link in links:
                total_links_by_perspective[perspective_for_link(link)] += 1
            for perspective in perspectives:
                digest_perspectives[perspective] += 1
            missing = [name for name in ("left", "center", "right") if name not in perspectives]
            if len(links) >= 3 and not missing:
                balanced_count += 1
            else:
                if len(links) < 3:
                    short_stories.append(story.get("title", "Untitled story"))
                if missing:
                    missing_perspective_stories.append((story.get("title", "Untitled story"), missing))

    print("\nSource-balance baseline report (non-blocking):")
    print(f"  Stories with 3+ links and left/center/right coverage: {balanced_count}/{story_count}")
    print(f"  Total links: {link_count}; average links/story: {(link_count / story_count if story_count else 0):.2f}")
    print(
        "  Story perspective presence: "
        + ", ".join(f"{key}={digest_perspectives.get(key, 0)}" for key in PERSPECTIVE_ORDER)
    )
    print(
        "  Link perspective totals: "
        + ", ".join(f"{key}={total_links_by_perspective.get(key, 0)}" for key in PERSPECTIVE_ORDER)
    )
    if total_links_by_perspective.get("right", 0) == 0:
        print("  WARNING: no right/lean-right coverage is present in this generated digest.")
    if short_stories:
        print(f"  WARNING: {len(short_stories)} stories have fewer than 3 source links.")
    if missing_perspective_stories:
        print(f"  WARNING: {len(missing_perspective_stories)} stories are missing one or more left/center/right perspectives.")
        for title, missing in missing_perspective_stories[:5]:
            print(f"    - missing {', '.join(missing)}: {title[:120]}")


today = datetime.now().strftime("%Y-%m-%d")
digest = {
    "id": f"{today}-expanded",
    "date": today,
    "title": "Daily Source Digest",
    "generatedAt": datetime.now().isoformat(),
    "note": "Daily source-balanced news digest — morning update.",
    "updatedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    "sections": sections,
}

digest = enrich_digest_story_summaries(digest)
digest = enrich_digest_link_metadata(digest)
report_source_balance(digest)

missing_link_metadata = missing_required_link_metadata(digest)
if missing_link_metadata:
    raise SystemExit(f"Digest link metadata validation failed: {missing_link_metadata[:10]}")

total_stories = sum(len(s["stories"]) for s in sections)
print(f"Created {OUTPUT_PATH}")
print(f"  Sections: {len(sections)}")
for s in sections:
    print(f"    - {s['name']}: {len(s['stories'])} stories")
print(f"  Total stories: {total_stories}")

if previous_urls:
    total_candidate = sum(len(by_source.get(d.lower(), [])) for config in SECTION_CONFIGS for d in config["domains"])
    print(f"\nDedup: {len(previous_urls)} previous URLs loaded, filtering repeats from {total_candidate} section candidates")

with open(OUTPUT_PATH, "w") as f:
    json.dump(digest, f, indent=2)
