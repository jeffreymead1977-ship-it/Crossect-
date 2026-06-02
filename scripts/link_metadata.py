"""Per-link source metadata enrichment for Crossect digests.

The generation pipeline should emit article-level link fields so the app does not
have to infer alignment/reliability entirely from dashboard fallback metadata.
This module preserves valid link-level LLM/manual ratings and only fills missing
or invalid values from deterministic source/domain metadata.
"""
from __future__ import annotations

from copy import deepcopy
from urllib.parse import urlparse

ALLOWED_BIASES = {
    "Left",
    "Lean Left",
    "Center",
    "Lean Right",
    "Right",
    "Unknown/Mixed",
    "Official",
    "Company",
}
ALLOWED_CONFIDENCES = {"high", "medium", "low"}

DEFAULT_METADATA = {
    "outlet": "Unknown source",
    "bias": "Unknown/Mixed",
    "confidence": "low",
}

SOURCE_METADATA = {
    # Domains used by current RSS sources / dashboard fallback.
    "abc.net.au": {
        "outlet": "ABC News",
        "bias": "Center",
        "confidence": "high",
        "quality": "Public broadcaster",
    },
    "aljazeera.com": {
        "outlet": "Al Jazeera",
        "bias": "Lean Left",
        "confidence": "medium",
    },
    "bbc.co.uk": {
        "outlet": "BBC",
        "bias": "Center",
        "confidence": "high",
        "quality": "Public broadcaster",
    },
    "bbc.com": {
        "outlet": "BBC",
        "bias": "Center",
        "confidence": "high",
        "quality": "Public broadcaster",
    },
    "cnn.com": {
        "outlet": "CNN",
        "bias": "Lean Left",
        "confidence": "medium",
    },
    "inquirer.net": {
        "outlet": "Philippine Daily Inquirer",
        "bias": "Center",
        "confidence": "medium",
    },
    "newsinfo.inquirer.net": {
        "outlet": "Philippine Daily Inquirer",
        "bias": "Center",
        "confidence": "medium",
    },
    "rappler.com": {
        "outlet": "Rappler",
        "bias": "Center",
        "confidence": "medium",
    },
    "techcrunch.com": {
        "outlet": "TechCrunch",
        "bias": "Center",
        "confidence": "medium",
    },
    "theguardian.com": {
        "outlet": "The Guardian",
        "bias": "Lean Left",
        "confidence": "high",
    },
    "theverge.com": {
        "outlet": "The Verge",
        "bias": "Lean Left",
        "confidence": "medium",
    },
    "wsj.com": {
        "outlet": "Wall Street Journal",
        "bias": "Lean Right",
        "confidence": "high",
    },
    # Historical typo/alias kept for compatibility with existing docs/app.js data.
    "sj.com": {
        "outlet": "Wall Street Journal",
        "bias": "Lean Right",
        "confidence": "high",
    },
    # Source names emitted by scripts/fetch-rss.sh.
    "abc australia": {
        "outlet": "ABC News",
        "bias": "Center",
        "confidence": "high",
        "quality": "Public broadcaster",
    },
    "al jazeera": {
        "outlet": "Al Jazeera",
        "bias": "Lean Left",
        "confidence": "medium",
    },
    "bbc world": {
        "outlet": "BBC",
        "bias": "Center",
        "confidence": "high",
        "quality": "Public broadcaster",
    },
    "cnn top stories": {
        "outlet": "CNN",
        "bias": "Lean Left",
        "confidence": "medium",
    },
    "philippine daily inquirer": {
        "outlet": "Philippine Daily Inquirer",
        "bias": "Center",
        "confidence": "medium",
    },
    "rappler world": {
        "outlet": "Rappler",
        "bias": "Center",
        "confidence": "medium",
    },
    "techcrunch": {
        "outlet": "TechCrunch",
        "bias": "Center",
        "confidence": "medium",
    },
    "the guardian australia": {
        "outlet": "The Guardian",
        "bias": "Lean Left",
        "confidence": "high",
    },
    "the guardian technology": {
        "outlet": "The Guardian",
        "bias": "Lean Left",
        "confidence": "high",
    },
    "the verge": {
        "outlet": "The Verge",
        "bias": "Lean Left",
        "confidence": "medium",
    },
    "wall street journal": {
        "outlet": "Wall Street Journal",
        "bias": "Lean Right",
        "confidence": "high",
    },
}


def source_key(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        host = urlparse(text).hostname if "://" in text else text.split("/")[0]
    except Exception:
        host = text
    return str(host or text).lower().removeprefix("www.")


def metadata_for_link(link: dict) -> dict:
    keys = [source_key(link.get("url")), source_key(link.get("source")), source_key(link.get("outlet"))]
    for key in keys:
        if not key:
            continue
        if key in SOURCE_METADATA:
            return deepcopy(SOURCE_METADATA[key])
        for source, metadata in SOURCE_METADATA.items():
            if "." in source and (key == source or key.endswith(f".{source}")):
                return deepcopy(metadata)
    fallback = deepcopy(DEFAULT_METADATA)
    source = str(link.get("source") or "").strip()
    if source:
        fallback["outlet"] = source
    else:
        host = source_key(link.get("url"))
        if host:
            fallback["outlet"] = host
    return fallback


def enrich_link_metadata(link: dict) -> dict:
    """Return a link copy with required per-link metadata filled.

    Valid existing link-level fields are kept to allow future LLM/grouping stages
    to provide article-specific judgements. Invalid/missing bias/confidence values
    are replaced with deterministic metadata fallback.
    """
    enriched = dict(link)
    metadata = metadata_for_link(enriched)

    if not str(enriched.get("outlet") or "").strip():
        enriched["outlet"] = metadata.get("outlet") or DEFAULT_METADATA["outlet"]

    if enriched.get("bias") not in ALLOWED_BIASES:
        alignment = enriched.get("alignment")
        enriched["bias"] = alignment if alignment in ALLOWED_BIASES else metadata.get("bias", DEFAULT_METADATA["bias"])

    confidence = str(enriched.get("confidence") or enriched.get("reliability") or "").strip().lower()
    if confidence not in ALLOWED_CONFIDENCES:
        confidence = str(metadata.get("confidence") or DEFAULT_METADATA["confidence"]).lower()
    enriched["confidence"] = confidence if confidence in ALLOWED_CONFIDENCES else DEFAULT_METADATA["confidence"]

    if not str(enriched.get("quality") or "").strip() and metadata.get("quality"):
        enriched["quality"] = metadata["quality"]

    return enriched


def missing_required_link_metadata(digest: dict) -> list[dict]:
    missing = []
    for section_index, section in enumerate(digest.get("sections", [])):
        for story_index, story in enumerate(section.get("stories", [])):
            for link_index, link in enumerate(story.get("links", [])):
                if not isinstance(link, dict):
                    missing.append({"section": section_index, "story": story_index, "link": link_index, "field": "link-object"})
                    continue
                for field in ("outlet", "bias", "confidence"):
                    if not str(link.get(field) or "").strip():
                        missing.append({"section": section_index, "story": story_index, "link": link_index, "field": field})
                if link.get("bias") and link.get("bias") not in ALLOWED_BIASES:
                    missing.append({"section": section_index, "story": story_index, "link": link_index, "field": "bias", "value": link.get("bias")})
                if link.get("confidence") and str(link.get("confidence")).lower() not in ALLOWED_CONFIDENCES:
                    missing.append({"section": section_index, "story": story_index, "link": link_index, "field": "confidence", "value": link.get("confidence")})
    return missing
