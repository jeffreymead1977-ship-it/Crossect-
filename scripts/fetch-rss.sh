#!/usr/bin/env bash
# fetch-rss.sh — Fetch RSS feeds and output structured JSON
# When run with args: ./fetch-rss.sh <output.json> [feed_list.txt]
# When run without args (no_agent cron mode): uses hardcoded defaults

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ $# -ge 1 ]; then
  # Called with arguments — use provided paths
  OUTPUT="$1"
  FEED_LIST="${2:-${SCRIPT_DIR}/feeds.txt}"
else
  # No args (no_agent cron mode) — use hardcoded defaults
  # Check if we're in the hermes scripts dir or Crossect scripts dir
  if echo "$SCRIPT_DIR" | grep -q "hermes"; then
    # Detect which job by checking CRONJOB_JOB_ID env var
    if [ "${CRONJOB_JOB_ID:-}" = "7cd80014ef0c" ]; then
      OUTPUT="/Users/e4042381/github/crossect-/docs/data/feeds/afternoon.json"
    else
      OUTPUT="/Users/e4042381/github/crossect-/docs/data/feeds/morning.json"
    fi
    FEED_LIST="${SCRIPT_DIR}/feeds.txt"
  else
    # Running from Crossect- directory — default to morning
    OUTPUT="docs/data/feeds/morning.json"
    FEED_LIST="${SCRIPT_DIR}/feeds.txt"
  fi
fi

mkdir -p "$(dirname "$OUTPUT")"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Fetch all feeds in parallel
fetch_feed() {
  local url="$1"
  local name="$2"
  local outfile="$3"
  
  # curl with timeout, follow redirects, save to file
  if curl -sS --connect-timeout 10 --max-time 30 -L "$url" -o "$outfile" 2>/dev/null; then
    # Check it's valid XML/HTML and has some content
    local size=$(wc -c < "$outfile")
    if [ "$size" -gt 500 ]; then
      echo "OK $name ($size bytes)"
      return 0
    fi
  fi
  echo "FAIL $name" >&2
  rm -f "$outfile"
  return 1
}

# Read feed list and fetch all feeds in parallel
pids=()
while IFS='|' read -r url name; do
  # Skip comments and empty lines
  [[ "$url" =~ ^#.*$ || -z "$url" ]] && continue
  
  local_file="$TMPDIR/$(echo "$name" | tr ' /' '__').xml"
  fetch_feed "$url" "$name" "$local_file" &
  pids+=($!)
done < "$FEED_LIST"

# Handle case where no feeds were found in the list
if [ ${#pids[@]} -eq 0 ]; then
  echo "WARNING: No valid feeds found in $FEED_LIST" >&2
fi

# Wait for all fetches to complete (non-blocking, we just want them done)
for pid in "${pids[@]+"${pids[@]}"}"; do
  wait "$pid" 2>/dev/null || true
done

# Now parse all fetched feeds into a single JSON array using Python
export RSS_OUTPUT="$OUTPUT"
python3 << 'PYEOF'
import sys
import os
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

tmpdir = os.environ.get("TMPDIR", "/tmp")
output_file = os.environ.get("RSS_OUTPUT", "")

if not output_file:
    print("ERROR: RSS_OUTPUT environment variable not set", file=sys.stderr)
    sys.exit(1)

# Find all XML files in tmpdir
xml_files = []
for f in sorted(os.listdir(tmpdir)):
    if f.endswith('.xml'):
        xml_files.append(os.path.join(tmpdir, f))

items = []
seen_urls = set()

def clean_text(text):
    """Clean up whitespace and decode entities."""
    if not text:
        return ""
    import html
    text = html.unescape(text)
    # Collapse whitespace
    import re
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_image_from_html(html_content):
    """Extract first image URL from HTML content."""
    if not html_content:
        return ""
    import re
    # Try src="..." or src='...'
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
    if match:
        url = match.group(1)
        # Convert relative URLs
        if url.startswith('//'):
            url = 'https:' + url
        elif not url.startswith('http') and not url.startswith('/'):
            pass  # Keep as-is, enrichment script handles it
        return url
    return ""

def extract_image_from_media(xml_root):
    """Extract image from media:content or media:thumbnail tags."""
    namespaces = {
        'media': 'http://search.yahoo.com/mrss/',
        'atom': 'http://www.w3.org/2005/Atom'
    }
    
    # Try media:content with type=image
    for content in xml_root.findall('.//media:content', namespaces):
        url = content.get('url', '')
        medium = content.get('medium', '') or ''
        if 'image' in medium.lower() and url:
            return url
    
    # Try media:thumbnail
    thumb = xml_root.find('.//media:thumbnail', namespaces)
    if thumb is not None and thumb.get('url'):
        return thumb.get('url')
    
    # Try any media:content with url (fallback)
    for content in xml_root.findall('.//media:content', namespaces):
        url = content.get('url', '')
        if url and ('image' in str(content.get('type', '')).lower() or 
                    'jpg' in url.lower() or 'png' in url.lower() or
                    'jpeg' in url.lower()):
            return url
    
    return ""

def parse_rss(xml_file):
    """Parse an RSS/Atom feed and extract items."""
    try:
        # Quick check: is this actually XML?
        with open(xml_file, 'r', errors='ignore') as f:
            first_chars = f.read(200).strip().lower()
            if '<rss' not in first_chars and '<feed' not in first_chars and '<rdf:' not in first_chars:
                print(f"  SKIP (not XML): {xml_file}", file=sys.stderr)
                return []
        tree = ET.parse(xml_file)
        root = tree.getroot()
    except ET.ParseError as e:
        print(f"  SKIP (parse error): {xml_file} - {e}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  SKIP (error): {xml_file} - {e}", file=sys.stderr)
        return []
    
    source_name = os.path.basename(xml_file).replace('.xml', '').replace('_', ' ')
    items_found = []
    
    # RSS 2.0 format
    for item in root.findall('.//item'):
        title_elem = item.find('title')
        link_elem = item.find('link')
        desc_elem = item.find('description')
        pubdate_elem = item.find('pubDate')
        
        title = clean_text(title_elem.text) if title_elem is not None and title_elem.text else ""
        url = clean_text(link_elem.text) if link_elem is not None and link_elem.text else ""
        summary = clean_text(desc_elem.text) if desc_elem is not None and desc_elem.text else ""
        
        # Parse pubDate
        pub_date = ""
        if pubdate_elem is not None and pubdate_elem.text:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(pubdate_elem.text.strip())
                pub_date = dt.isoformat()
            except:
                pub_date = clean_text(pubdate_elem.text)
        
        # Extract image from media tags or HTML description
        image_url = extract_image_from_media(item)
        if not image_url and desc_elem is not None and desc_elem.text:
            image_url = extract_image_from_html(desc_elem.text)
        
        if title and url and url not in seen_urls:
            seen_urls.add(url)
            items_found.append({
                "title": title,
                "url": url,
                "source": source_name,
                "pubDate": pub_date,
                "summary": summary[:500] if len(summary) > 500 else summary,
                "imageUrl": image_url if image_url and not image_url.startswith('data:') else ""
            })
    
    # Atom format (namespace-based)
    if not items_found:
        atom_ns = {'atom': 'http://www.w3.org/2005/Atom'}
        for entry in root.findall('.//atom:entry', atom_ns):
            title_elem = entry.find('atom:title', atom_ns)
            link_elem = entry.find('atom:link', atom_ns)
            summary_elem = entry.find('atom:summary', atom_ns) or entry.find('atom:content', atom_ns)
            pubdate_elem = entry.find('atom:published', atom_ns) or entry.find('atom:updated', atom_ns)
            
            title = clean_text(title_elem.text) if title_elem is not None and title_elem.text else ""
            url = clean_text(link_elem.get('href', '')) if link_elem is not None else ""
            summary = clean_text(summary_elem.text) if summary_elem is not None and summary_elem.text else ""
            
            pub_date = ""
            if pubdate_elem is not None and pubdate_elem.text:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(pubdate_elem.text.strip())
                    pub_date = dt.isoformat()
                except:
                    pub_date = clean_text(pubdate_elem.text)
            
            if title and url and url not in seen_urls:
                seen_urls.add(url)
                items_found.append({
                    "title": title,
                    "url": url,
                    "source": source_name,
                    "pubDate": pub_date,
                    "summary": summary[:500] if len(summary) > 500 else summary,
                    "imageUrl": ""
                })
    
    return items_found

# Parse all feeds
all_items = []
skipped_files = 0
for xml_file in xml_files:
    try:
        feed_items = parse_rss(xml_file)
        print(f"  {os.path.basename(xml_file)}: {len(feed_items)} items")
        all_items.extend(feed_items)
    except Exception as e:
        skipped_files += 1
        print(f"  SKIP (error): {xml_file} - {e}", file=sys.stderr)

if skipped_files > 0:
    print(f"\n  Skipped {skipped_files} malformed feed files", file=sys.stderr)

# Sort by pubDate (newest first), then by source for deterministic ordering
def sort_key(item):
    try:
        from datetime import datetime
        if item.get('pubDate'):
            # Handle various date formats
            dt_str = item['pubDate']
            # Try ISO format
            for fmt in ['%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%SZ', '%a, %d %b %Y %H:%M:%S %Z']:
                try:
                    return -datetime.strptime(dt_str.replace(' +0000', '+0000').replace('  ', ' +'), fmt).timestamp()
                except:
                    continue
        return 0  # No date, put at end
    except:
        return 0

all_items.sort(key=sort_key)

# Write output
output = {
    "fetchedAt": datetime.now(timezone.utc).isoformat(),
    "totalItems": len(all_items),
    "sources": list(set(item["source"] for item in all_items)),
    "items": all_items
}

with open(output_file, 'w') as f:
    json.dump(output, f, indent=2)

print(f"\nTotal: {len(all_items)} items from {len(output['sources'])} sources")
print(f"Written to: {output_file}")
PYEOF

echo "RSS fetch complete."
