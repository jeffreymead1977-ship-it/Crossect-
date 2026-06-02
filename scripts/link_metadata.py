"""Per-link article metadata enrichment for Crossect digests.

The generation pipeline should emit article-level link fields so the app does not
have to infer alignment/reliability entirely from dashboard fallback metadata.
This module keeps source metadata as a prior/fallback, then prefers a local
LM Studio OpenAI-compatible per-article judgement when available. If local LLM
judging is disabled, unavailable, times out, or returns invalid JSON, it falls
back to a conservative deterministic/source-prior result.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse
import re

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

DEFAULT_LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
DEFAULT_LM_STUDIO_MODEL = "qwen3.6-35b-a3b-mtp"
DEFAULT_LM_STUDIO_SUMMARY_MODEL = DEFAULT_LM_STUDIO_MODEL
DEFAULT_LM_STUDIO_TIMEOUT_SECONDS = 5.0

ALIGNMENT_CUES = {
    "Left": [
        r"\b(union-backed|labou?r union|strike action|collective bargaining)\b",
        r"\b(climate crisis|polluters?|environmental justice)\b",
        r"\b(wealth inequality|social programmes?|public housing|human rights advocates?)\b",
        r"\b(far-right|hard-right|right-wing extremis[mt]|authoritarian)\b",
        r"\b(police brutality|racial justice|indigenous rights|refugee rights)\b",
    ],
    "Right": [
        r"\b(tax cuts?|red tape|small business|property rights|free speech)\b",
        r"\b(border security|illegal immigration|tough on crime|law and order)\b",
        r"\b(woke|cancel culture|left-wing extremis[mt]|socialist agenda)\b",
        r"\b(government waste|spending cuts?|deficit reduction)\b",
        r"\b(gun rights|religious liberty|parental rights)\b",
    ],
    "Official": [
        r"\b(government|ministry|department|court|regulator|commission|police said|officials? said)\b",
        r"\b(white house|palace|senate|parliament|council|agency)\b",
    ],
    "Company": [
        r"\b(company|startup|earnings|shares?|stock|ipo|product launch|quarterly results?)\b",
        r"\b(ceo|founder|investors?|funding round|acquisition|merger)\b",
    ],
}

RELIABILITY_CUES = {
    "raise": [
        r"\b(reuters|associated press|ap news|court documents?|officials? said|according to)\b",
        r"\b(data|study|report|filing|statement|interview|confirmed|verified)\b",
        r"\b(public broadcaster|regulator|court|ministry|department)\b",
    ],
    "lower": [
        r"\b(rumou?rs?|unverified|alleged without evidence|speculation|conspiracy)\b",
        r"\b(opinion|op-ed|analysis|sponsored|advertorial|promoted)\b",
        r"\b(shocking|bombshell|you won't believe|secret plot|exposed)\b",
    ],
}

OFFICIAL_SOURCE_NAME_CUES = [
    r"\b(?:department|ministry|office|bureau|agency)\s+of\b",
    r"\b(?:government|parliament|senate|congress|court|supreme court|police|regulator|commission)\b",
    r"\b(?:white house|downing street|palace|official gazette)\b",
]

OFFICIAL_SOURCE_DOMAINS = {
    "gov.uk",
    "gov.au",
    "govt.nz",
    "gc.ca",
    "europa.eu",
    "un.org",
    "who.int",
    "worldbank.org",
    "imf.org",
}

CONFIDENCE_SCORE = {"low": 0, "medium": 1, "high": 2}
SCORE_CONFIDENCE = {0: "low", 1: "medium", 2: "high"}

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


def article_text(link: dict) -> str:
    """Return searchable article text available locally in the feed/digest."""
    return " ".join(
        str(link.get(field) or "")
        for field in ("headline", "title", "excerpt", "summary", "description", "content", "source", "outlet", "url")
    ).strip()


def source_identity_text(link: dict, metadata: dict) -> str:
    """Return source identity fields only, excluding article prose."""
    return " ".join(
        str(value or "")
        for value in (
            link.get("source"),
            link.get("outlet"),
            metadata.get("outlet"),
            source_key(link.get("url")),
        )
    ).strip()


def is_official_source(link: dict, metadata: dict) -> bool:
    """True only when the source/outlet/domain itself is official.

    Article body phrases such as "officials said", "government", "court" or
    "police said" are common in normal journalism and must not turn media
    outlets (BBC, ABC, Guardian, Reuters-like sources, etc.) into Official.
    """
    if metadata.get("bias") == "Official":
        return True

    hosts = [source_key(link.get("url")), source_key(link.get("source")), source_key(link.get("outlet"))]
    for host in hosts:
        if not host or " " in host:
            continue
        if host == "gov" or host.endswith(".gov") or ".gov." in host:
            return True
        if any(host == domain or host.endswith(f".{domain}") for domain in OFFICIAL_SOURCE_DOMAINS):
            return True
        if re.search(r"(^|\.)(?:parliament|senate|congress|court|police|regulator)\.", host):
            return True

    identity = source_identity_text(link, metadata)
    return any(re.search(pattern, identity, flags=re.IGNORECASE) for pattern in OFFICIAL_SOURCE_NAME_CUES)


def matching_cues(text: str, patterns: list[str]) -> list[str]:
    matches = []
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            # Keep basis readable while not leaking regex syntax into every entry.
            matches.append(pattern.replace(r"\b", "").replace("?", "").replace("\\", ""))
    return matches


def judge_article_alignment(link: dict, metadata: dict) -> tuple[str, str]:
    """Judge alignment from article text with source metadata as a safe prior."""
    text = article_text(link)
    scores: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}
    official_source = is_official_source(link, metadata)

    for label, patterns in ALIGNMENT_CUES.items():
        cues = matching_cues(text, patterns)
        if cues:
            scores[label] = len(cues)
            evidence[label] = cues[:2]

    # Official/company are provenance descriptors. Use them when those cues are
    # clearly stronger than ideological cues, otherwise keep ideological result.
    ideological = {k: v for k, v in scores.items() if k in {"Left", "Right"}}
    if ideological:
        left_score = ideological.get("Left", 0)
        right_score = ideological.get("Right", 0)
        if left_score == right_score and left_score:
            return "Unknown/Mixed", "article-text: balanced/conflicting left and right framing cues"
        winner = "Left" if left_score > right_score else "Right"
        return winner, f"article-text: {winner} cue(s): {', '.join(evidence[winner])}"

    if official_source:
        if scores.get("Official"):
            return "Official", f"official-source: source identity plus provenance cue(s): {', '.join(evidence['Official'])}"
        return "Official", "official-source: source/outlet/domain is official"

    if scores.get("Company"):
        return "Company", f"article-text: company provenance cue(s): {', '.join(evidence['Company'])}"

    fallback = metadata.get("bias", DEFAULT_METADATA["bias"])
    return fallback, f"source-default-fallback: no article alignment cues; source prior={fallback}"


def guard_official_alignment_for_media_source(link: dict, metadata: dict, alignment: str, alignment_basis: str) -> tuple[str, str]:
    """Prevent ordinary media articles quoting officials from being labelled Official."""
    if alignment != "Official" or is_official_source(link, metadata):
        return alignment, alignment_basis
    fallback = metadata.get("bias", DEFAULT_METADATA["bias"])
    if fallback == "Official" or fallback not in ALLOWED_BIASES:
        fallback = DEFAULT_METADATA["bias"]
    return fallback, (
        "source-prior-guard: non-official media/source kept at "
        f"source prior={fallback}; suppressed Official from {alignment_basis[:220]}"
    )


def judge_article_reliability(link: dict, metadata: dict) -> tuple[str, str]:
    """Judge reliability from article text with source reliability as a prior."""
    text = article_text(link)
    source_confidence = str(metadata.get("confidence") or DEFAULT_METADATA["confidence"]).lower()
    score = CONFIDENCE_SCORE.get(source_confidence, CONFIDENCE_SCORE[DEFAULT_METADATA["confidence"]])

    raise_cues = matching_cues(text, RELIABILITY_CUES["raise"])
    lower_cues = matching_cues(text, RELIABILITY_CUES["lower"])
    if raise_cues:
        score += 1
    if lower_cues:
        score -= 1

    reliability = SCORE_CONFIDENCE[max(0, min(2, score))]
    basis_parts = [f"source-prior={source_confidence}"]
    if raise_cues:
        basis_parts.append("article-text raises reliability: " + ", ".join(raise_cues[:2]))
    if lower_cues:
        basis_parts.append("article-text lowers reliability: " + ", ".join(lower_cues[:2]))
    if not raise_cues and not lower_cues:
        basis_parts.append("article-text: no reliability modifier cues")
    return reliability, "; ".join(basis_parts)


def source_default_judgement(metadata: dict) -> tuple[str, str, str, str]:
    """Return the safest fallback: source prior and source confidence."""
    bias = metadata.get("bias", DEFAULT_METADATA["bias"])
    if bias not in ALLOWED_BIASES:
        bias = DEFAULT_METADATA["bias"]
    reliability = str(metadata.get("confidence") or DEFAULT_METADATA["confidence"]).lower()
    if reliability not in ALLOWED_CONFIDENCES:
        reliability = DEFAULT_METADATA["confidence"]
    return (
        bias,
        reliability,
        f"source-default-fallback: conservative source prior={bias}",
        f"source-default-fallback: conservative source reliability prior={reliability}",
    )


def local_rating_mode() -> str:
    """Return normalized rating mode.

    Default is local LLM first. Supported env values:
    - local/lm/llm/auto/default: try LM Studio, fallback deterministic
    - heuristic/deterministic: skip LM, use conservative deterministic article cues
    - source/off: skip LM and article cues, use source defaults only
    """
    raw = str(os.environ.get("CROSSECT_RATING_MODE") or "local").strip().lower()
    aliases = {
        "": "local",
        "auto": "local",
        "default": "local",
        "lm": "local",
        "llm": "local",
        "lmstudio": "local",
        "lm-studio": "local",
        "deterministic": "heuristic",
        "source-default": "source",
        "none": "source",
        "off": "source",
    }
    return aliases.get(raw, raw)


def local_summary_mode() -> str:
    """Return normalized story-summary mode.

    Summaries are intentionally configured independently from article ratings so
    cron can run local AI summaries while keeping ratings deterministic. This
    avoids asking LM Studio to load a second model after the summary model.
    Supported env values:
    - local/lm/llm/auto/default: try LM Studio, fallback to RSS/feed summaries
    - rss/feed/fallback/source/off/none: skip LM, keep RSS/feed summaries
    """
    raw = str(os.environ.get("CROSSECT_SUMMARY_MODE") or "local").strip().lower()
    aliases = {
        "": "local",
        "auto": "local",
        "default": "local",
        "lm": "local",
        "llm": "local",
        "lmstudio": "local",
        "lm-studio": "local",
        "rss": "feed",
        "fallback": "feed",
        "source": "feed",
        "none": "feed",
        "off": "feed",
    }
    return aliases.get(raw, raw)


def lm_studio_config() -> tuple[str, str, float]:
    base_url = str(os.environ.get("CROSSECT_LM_STUDIO_BASE_URL") or DEFAULT_LM_STUDIO_BASE_URL).rstrip("/")
    requested_model = str(os.environ.get("CROSSECT_LM_STUDIO_MODEL") or DEFAULT_LM_STUDIO_MODEL).strip()
    # Hard pin Crossect to the MTP Qwen model. Loading any other LM Studio model
    # can open a second model and bog the machine down, so env fallbacks/overrides
    # are ignored unless they exactly match the approved model.
    model = DEFAULT_LM_STUDIO_MODEL
    if requested_model and requested_model != DEFAULT_LM_STUDIO_MODEL:
        os.environ["CROSSECT_LM_STUDIO_MODEL_IGNORED"] = requested_model
    try:
        timeout = float(os.environ.get("CROSSECT_LM_STUDIO_TIMEOUT") or DEFAULT_LM_STUDIO_TIMEOUT_SECONDS)
    except ValueError:
        timeout = DEFAULT_LM_STUDIO_TIMEOUT_SECONDS
    return base_url, model, max(0.5, timeout)


def lm_studio_summary_config() -> tuple[str, str, float]:
    """Return LM Studio config for story summaries.

    Story summaries are configured separately from link alignment/reliability
    ratings. Cron can set CROSSECT_RATING_MODE=heuristic and
    CROSSECT_SUMMARY_MODE=local so LM Studio only needs the summary model loaded.
    """
    base_url = str(os.environ.get("CROSSECT_LM_STUDIO_BASE_URL") or DEFAULT_LM_STUDIO_BASE_URL).rstrip("/")
    model = str(
        os.environ.get("CROSSECT_LM_STUDIO_SUMMARY_MODEL")
        or DEFAULT_LM_STUDIO_SUMMARY_MODEL
    ).strip() or DEFAULT_LM_STUDIO_SUMMARY_MODEL
    try:
        timeout = float(
            os.environ.get("CROSSECT_LM_STUDIO_SUMMARY_TIMEOUT")
            or os.environ.get("CROSSECT_LM_STUDIO_BATCH_TIMEOUT")
            or os.environ.get("CROSSECT_LM_STUDIO_TIMEOUT")
            or DEFAULT_LM_STUDIO_TIMEOUT_SECONDS
        )
    except ValueError:
        timeout = DEFAULT_LM_STUDIO_TIMEOUT_SECONDS
    return base_url, model, max(0.5, timeout)


def lm_studio_summary_batch_size() -> int:
    """Return story-summary batch size for LM Studio calls.

    Qwen MTP on LM Studio returns JSON most reliably when constrained with a JSON
    schema and kept in small batches. Default to one article per request so the
    already-loaded Qwen worker model can be reused without loading Gemma.
    """
    try:
        raw = int(os.environ.get("CROSSECT_LM_STUDIO_SUMMARY_BATCH_SIZE") or 1)
    except ValueError:
        raw = 1
    return max(1, min(8, raw))


def extract_json_object(text: str) -> dict:
    """Parse a strict JSON object, tolerating only surrounding whitespace/fences."""
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("LM rating JSON was not an object")
    return parsed


def validate_lm_judgement(parsed: dict) -> dict:
    bias = str(parsed.get("bias") or "").strip()
    confidence = str(parsed.get("confidence") or "").strip().lower()
    alignment_basis = str(parsed.get("alignmentBasis") or "").strip()
    reliability_basis = str(parsed.get("reliabilityBasis") or "").strip()

    if bias not in ALLOWED_BIASES:
        raise ValueError(f"invalid bias: {bias!r}")
    if confidence not in ALLOWED_CONFIDENCES:
        raise ValueError(f"invalid confidence: {confidence!r}")
    if not alignment_basis or not reliability_basis:
        raise ValueError("missing basis field(s)")

    return {
        "bias": bias,
        "confidence": confidence,
        "alignmentBasis": alignment_basis[:500],
        "reliabilityBasis": reliability_basis[:500],
    }


def judge_article_with_lm_studio(link: dict, metadata: dict) -> tuple[dict | None, str | None, str | None]:
    """Call local LM Studio for a per-article judgement.

    Returns (judgement, error, raw_content). Only stdlib urllib is used so cron
    can run without agent-only dependencies. Errors are deliberately converted to
    short strings so callers can mark fallback provenance.
    """
    base_url, model, timeout = lm_studio_config()
    url = f"{base_url}/chat/completions"
    source_bias = metadata.get("bias", DEFAULT_METADATA["bias"])
    source_reliability = str(metadata.get("confidence") or DEFAULT_METADATA["confidence"]).lower()
    outlet = metadata.get("outlet") or link.get("outlet") or link.get("source") or DEFAULT_METADATA["outlet"]
    article = article_text(link)[:3500]

    system_prompt = (
        "You are rating a single news article for Crossect. Return strict JSON only. Do not include reasoning. "
        "Judge the article's own framing, claims, evidence, sourcing, and tone; do not merely copy the source prior. "
        "Use the source prior lightly when article text is too thin. "
        "Allowed bias values: Left, Lean Left, Center, Lean Right, Right, Unknown/Mixed, Official, Company. "
        "Use Official only when the source/outlet/domain itself is government, court, regulator, police, parliament, ministry or an official dispatch; never use Official for normal journalism merely quoting officials or mentioning government/court/police. "
        "Allowed confidence values: high, medium, low. "
        "alignmentBasis and reliabilityBasis must each be one short sentence."
    )
    user_prompt = {
        "task": "Rate this article/link. Return only JSON with keys bias, confidence, alignmentBasis, reliabilityBasis. No markdown and no explanation outside JSON.",
        "sourcePrior": {"outlet": outlet, "bias": source_bias, "confidence": source_reliability},
        "article": {
            "headline": link.get("headline") or link.get("title") or "",
            "excerpt": link.get("excerpt") or link.get("summary") or link.get("description") or "",
            "source": link.get("source") or "",
            "url": link.get("url") or "",
            "availableText": article,
        },
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
        ],
        "temperature": 0,
        "max_tokens": 500,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", "replace")[:500].replace("\n", " ")
        return None, f"lm-studio-http-error: {exc.code}: {error_body}", None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        return None, f"lm-studio-error: {type(exc).__name__}: {exc}", None

    try:
        completion = json.loads(body)
        raw_content = completion["choices"][0]["message"]["content"]
        return validate_lm_judgement(extract_json_object(raw_content)), None, raw_content
    except Exception as exc:
        raw = body[:1000].replace("\n", " ")
        return None, f"lm-studio-invalid: {type(exc).__name__}: {exc}; raw={raw}", body[:1000]


def enrich_link_metadata(link: dict, use_local_lm: bool = False) -> dict:
    """Return a link copy with per-article and source metadata filled.

    By default this is fast and deterministic. Whole-digest builders should call
    enrich_digest_link_metadata() after constructing the digest to get one local
    LM Studio batch judgement, instead of making a slow model call per link.
    """
    enriched = dict(link)
    metadata = metadata_for_link(enriched)

    if not str(enriched.get("outlet") or "").strip():
        enriched["outlet"] = metadata.get("outlet") or DEFAULT_METADATA["outlet"]

    source_bias = metadata.get("bias", DEFAULT_METADATA["bias"])
    source_reliability = str(metadata.get("confidence") or DEFAULT_METADATA["confidence"]).lower()
    if source_reliability not in ALLOWED_CONFIDENCES:
        source_reliability = DEFAULT_METADATA["confidence"]

    enriched["sourceBias"] = source_bias
    enriched["sourceReliability"] = source_reliability

    mode = local_rating_mode()
    rating_method = "deterministic-local-article-heuristic-v2"
    rating_error = ""

    if mode == "source":
        alignment, confidence, alignment_basis, reliability_basis = source_default_judgement(metadata)
        rating_method = "source-default-v1"
    else:
        llm_judgement = None
        if mode == "local" and use_local_lm:
            llm_judgement, rating_error, _raw = judge_article_with_lm_studio(enriched, metadata)
        elif mode == "local" and not use_local_lm:
            # Fast path for builders: deterministic metadata first; the builder
            # will try one LM Studio batch call after the whole digest exists.
            pass
        elif mode not in {"heuristic", "local"}:
            rating_error = f"unknown CROSSECT_RATING_MODE={mode!r}; used heuristic fallback"

        if llm_judgement:
            alignment = llm_judgement["bias"]
            confidence = llm_judgement["confidence"]
            alignment_basis = "lm-studio: " + llm_judgement["alignmentBasis"]
            reliability_basis = "lm-studio: " + llm_judgement["reliabilityBasis"]
            alignment, alignment_basis = guard_official_alignment_for_media_source(enriched, metadata, alignment, alignment_basis)
            rating_method = "lm-studio-local-article-json-v1"
        else:
            alignment, alignment_basis = judge_article_alignment(enriched, metadata)
            confidence, reliability_basis = judge_article_reliability(enriched, metadata)
            alignment, alignment_basis = guard_official_alignment_for_media_source(enriched, metadata, alignment, alignment_basis)
            if rating_error:
                rating_method = "deterministic-local-article-heuristic-v2-fallback"
                alignment_basis = f"{alignment_basis}; fallbackReason={rating_error[:240]}"
                reliability_basis = f"{reliability_basis}; fallbackReason={rating_error[:240]}"

    if alignment not in ALLOWED_BIASES:
        alignment = source_bias
        alignment_basis = f"source-default-fallback: invalid article alignment; source prior={source_bias}"
        rating_method = "source-default-v1-fallback"
    enriched["bias"] = alignment
    enriched["alignment"] = alignment
    enriched["alignmentBasis"] = alignment_basis

    if confidence not in ALLOWED_CONFIDENCES:
        confidence = source_reliability
        reliability_basis = f"source-default-fallback: invalid article reliability; source prior={source_reliability}"
        rating_method = "source-default-v1-fallback"
    enriched["confidence"] = confidence
    enriched["reliability"] = confidence
    enriched["reliabilityBasis"] = reliability_basis
    enriched["ratingMethod"] = rating_method

    if not str(enriched.get("quality") or "").strip() and metadata.get("quality"):
        enriched["quality"] = metadata["quality"]

    return enriched


def iter_digest_links(digest: dict):
    """Yield (section_index, story_index, link_index, link) for dict links."""
    for section_index, section in enumerate(digest.get("sections", [])):
        for story_index, story in enumerate(section.get("stories", [])):
            for link_index, link in enumerate(story.get("links", [])):
                if isinstance(link, dict):
                    yield section_index, story_index, link_index, link


def judge_digest_links_with_lm_studio(digest: dict) -> tuple[dict[int, dict], str | None, str | None]:
    """Call local LM Studio once for all links in a digest.

    Returns (ratings_by_index, error, raw_content). This keeps cron practical:
    one local model request for the whole morning digest instead of one slow
    request per article.
    """
    base_url, model, _timeout = lm_studio_config()
    timeout = max(
        _timeout,
        float(os.environ.get("CROSSECT_LM_STUDIO_BATCH_TIMEOUT") or 60),
    )
    url = f"{base_url}/chat/completions"
    articles = []
    for idx, (_section_index, _story_index, _link_index, link) in enumerate(iter_digest_links(digest)):
        metadata = metadata_for_link(link)
        articles.append({
            "index": idx,
            "sourcePrior": {
                "outlet": metadata.get("outlet") or link.get("outlet") or link.get("source") or DEFAULT_METADATA["outlet"],
                "bias": metadata.get("bias", DEFAULT_METADATA["bias"]),
                "confidence": str(metadata.get("confidence") or DEFAULT_METADATA["confidence"]).lower(),
            },
            "headline": link.get("headline") or link.get("title") or "",
            "excerpt": link.get("excerpt") or link.get("summary") or link.get("description") or "",
            "source": link.get("source") or link.get("outlet") or "",
            "url": link.get("url") or "",
        })
    if not articles:
        return {}, None, None

    system_prompt = (
        "You rate individual news article links for Crossect. Return strict JSON only. "
        "Judge each article's own framing, language, claims, evidence, sourcing and tone. "
        "Do not simply copy the source prior. Use source prior only when text is thin. "
        "Allowed bias values: Left, Lean Left, Center, Lean Right, Right, Unknown/Mixed, Official, Company. "
        "Use Official only when the source/outlet/domain itself is government, court, regulator, police, parliament, ministry or an official dispatch; never use Official for normal journalism merely quoting officials or mentioning government/court/police. "
        "Use Company only for company/product/earnings/startup items. "
        "Allowed confidence values: high, medium, low. "
        "Return JSON object {\"ratings\":[...]} with one item per input article: index, bias, confidence, alignmentBasis, reliabilityBasis. "
        "alignmentBasis and reliabilityBasis must be short human-readable per-article explanations."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({"articles": articles}, ensure_ascii=False)},
        ],
        "temperature": 0,
        "max_tokens": max(1200, min(6000, 180 * len(articles))),
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", "replace")[:500].replace("\n", " ")
        return {}, f"lm-studio-batch-http-error: {exc.code}: {error_body}", None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        return {}, f"lm-studio-batch-error: {type(exc).__name__}: {exc}", None

    try:
        completion = json.loads(body)
        raw_content = completion["choices"][0]["message"]["content"]
        parsed = extract_json_object(raw_content)
        ratings = parsed.get("ratings")
        if not isinstance(ratings, list):
            raise ValueError("ratings was not a list")
        by_index: dict[int, dict] = {}
        for item in ratings:
            if not isinstance(item, dict):
                continue
            if "index" not in item:
                continue
            index = int(item["index"])
            by_index[index] = validate_lm_judgement(item)
        return by_index, None, raw_content
    except Exception as exc:
        raw = body[:1000].replace("\n", " ")
        return {}, f"lm-studio-batch-invalid: {type(exc).__name__}: {exc}; raw={raw}", body[:1000]


def enrich_digest_link_metadata(digest: dict) -> dict:
    """Apply one local-LM batch judgement to all links in a digest when enabled.

    Existing link fields from enrich_link_metadata() remain as fallback. This
    mutates and returns digest for easy use by builder scripts.
    """
    mode = local_rating_mode()
    if mode == "source":
        return digest
    links = list(iter_digest_links(digest))
    if not links:
        return digest
    if mode != "local":
        return digest

    ratings_by_index, error, _raw = judge_digest_links_with_lm_studio(digest)
    if error:
        for _section_index, _story_index, _link_index, link in links:
            link["ratingMethod"] = "deterministic-local-article-heuristic-v2-fallback"
            link["alignmentBasis"] = f"{link.get('alignmentBasis', '')}; batchFallbackReason={error[:240]}".strip("; ")
            link["reliabilityBasis"] = f"{link.get('reliabilityBasis', '')}; batchFallbackReason={error[:240]}".strip("; ")
        return digest

    for idx, (_section_index, _story_index, _link_index, link) in enumerate(links):
        judgement = ratings_by_index.get(idx)
        if not judgement:
            continue
        metadata = metadata_for_link(link)
        alignment, alignment_basis = guard_official_alignment_for_media_source(
            link,
            metadata,
            judgement["bias"],
            "lm-studio-batch: " + judgement["alignmentBasis"],
        )
        link["bias"] = alignment
        link["alignment"] = alignment
        link["confidence"] = judgement["confidence"]
        link["reliability"] = judgement["confidence"]
        link["alignmentBasis"] = alignment_basis
        link["reliabilityBasis"] = "lm-studio-batch: " + judgement["reliabilityBasis"]
        link["ratingMethod"] = "lm-studio-local-digest-batch-json-v1"
    return digest


def iter_digest_stories(digest: dict):
    """Yield (section_index, story_index, story) for story dicts."""
    for section_index, section in enumerate(digest.get("sections", [])):
        for story_index, story in enumerate(section.get("stories", [])):
            if isinstance(story, dict):
                yield section_index, story_index, story


def normalize_story_summary_text(summary, limit: int = 1200) -> str:
    """Normalize a story summary while preserving up to two prose paragraphs.

    Crossect story summaries are displayed as digest prose, not lists. Keep
    paragraph breaks from the local model when available, but collapse accidental
    extra whitespace and reject obvious bullet/list formatting elsewhere.
    """
    text = str(summary or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"<[^>]+>", " ", text)
    if not text:
        return ""
    paragraphs = []
    for part in re.split(r"\n\s*\n+", text):
        cleaned = re.sub(r"[ \t]+", " ", part).strip()
        cleaned = re.sub(r"\n+", " ", cleaned).strip()
        if cleaned:
            paragraphs.append(cleaned)
        if len(paragraphs) == 2:
            break
    if not paragraphs:
        paragraphs = [re.sub(r"\s+", " ", text).strip()]
    normalized = "\n\n".join(paragraphs)
    return normalized[:limit].rstrip()


def validate_lm_summary(parsed: dict) -> str:
    summary = normalize_story_summary_text(parsed.get("summary"), limit=1200)
    if not summary:
        raise ValueError("missing summary")
    if re.search(r"(^|\n)\s*(?:[-*•]|\d+[.)])\s+", summary):
        raise ValueError("summary looked like a bullet/list")
    return summary


def fallback_story_summary(story: dict) -> str:
    """Build a deterministic mini-story from locally available metadata.

    This is deliberately extractive/synthetic from title, RSS summary and link
    excerpts only. It does not add facts beyond the feed/digest metadata.
    """
    title = normalize_story_summary_text(story.get("title"), limit=220).strip()
    original = normalize_story_summary_text(story.get("summary"), limit=700).strip()
    links = [link for link in story.get("links", []) if isinstance(link, dict)]

    snippets: list[str] = []
    seen = set()

    def sentence(text: str) -> str:
        cleaned = normalize_story_summary_text(text, limit=700).strip()
        if cleaned and cleaned[-1] not in ".!?":
            cleaned += "."
        return cleaned

    def remember(text: str) -> bool:
        cleaned = sentence(text)
        if not cleaned:
            return False
        key = cleaned.lower()
        if key == title.lower() or key in seen:
            return False
        if any(key in existing.lower() or existing.lower() in key for existing in snippets):
            return False
        snippets.append(cleaned)
        seen.add(key)
        return True

    for value in [original]:
        remember(value)
    for link in links[:4]:
        outlet = str(link.get("outlet") or link.get("source") or "").strip()
        headline = normalize_story_summary_text(link.get("headline") or link.get("title"), limit=220).strip()
        excerpt = normalize_story_summary_text(
            link.get("excerpt") or link.get("summary") or link.get("description"),
            limit=500,
        ).strip()
        if headline and headline.lower() != title.lower():
            text = f"{outlet}: {headline}" if outlet else headline
            remember(text)
        if excerpt:
            text = f"{outlet} reports that {excerpt[0].lower() + excerpt[1:]}" if outlet and excerpt[:1].isupper() else (f"{outlet} reports that {excerpt}" if outlet else excerpt)
            remember(text)

    if snippets:
        summary = snippets[0]
        for addition in snippets[1:3]:
            if len(summary) >= 650:
                break
            if addition and addition not in summary:
                summary = f"{summary} {addition}"
    else:
        summary = title

    summary = normalize_story_summary_text(summary, limit=900)
    if title and summary and not summary.lower().startswith(title.lower()):
        summary = f"{title}. {summary}"
    return normalize_story_summary_text(summary, limit=900) or title


def extract_qwen_reasoning_summaries_batch(reasoning: str, articles: list[dict]) -> dict[int, str] | None:
    """Extract per-article summaries from Qwen's reasoning_content for batch requests.

    When Qwen MTP ignores no-thinking flags it puts all output in reasoning_content.
    For a batch of N articles the reasoning will contain draft summaries for each.
    Returns {index: summary} or None if nothing extractable.
    """
    text = str(reasoning or "")
    if not text.strip():
        return None

    # Strategy 1: Look for per-article numbered sections with "Draft" patterns
    # Qwen typically structures batch reasoning like:
    #   Index: 0, Title: "...", Draft Summary (Mental): "..."
    #   Index: 1, Title: "...", Draft Summary: "..."
    results: dict[int, str] = {}

    # Split on index markers that Qwen uses in batch reasoning
    index_sections = re.split(r'\*\s*Index:\s*(\d+)', text)
    # index_sections is ['', '0', 'section0', '1', 'section1', ...]
    for i in range(1, len(index_sections), 3):
        try:
            idx = int(index_sections[i])
        except (ValueError, IndexError):
            continue
        section = index_sections[i + 2] if i + 2 < len(index_sections) else ""

        # Try to find a draft summary in this section
        patterns = [
            r"Draft Summary \(Mental\):\s*\n\s*(.+?)(?:\n\s*[-*]\s*Check constraints|\n\s*Refinement|\n\s*$)",
            r"Draft Summary:\s*\n\s*(.+?)(?:\n\s*[-*]\s*Check constraints|\n\s*Refinement|\n\s*$)",
            r"Draft 1:\s*(.+?)(?:\n|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, section, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            candidate = re.sub(r"\s+", " ", match.group(1)).strip(" -*`\"'")
            # Clean up check constraints notes
            candidate = re.sub(r"\s*\*?\s*Check constraints.*$", "", candidate, flags=re.IGNORECASE).strip()
            if 40 <= len(candidate) <= 1200 and candidate.endswith((".", "!", "?")):
                results[idx] = normalize_story_summary_text(candidate, limit=1200)
                break

    # Strategy 2: If strategy 1 found nothing, try to find any numbered draft sentences
    # matching article indices from the input
    if not results:
        for article in articles:
            idx = int(article["index"])
            title = str(article.get("title", "")).lower()[:80]
            # Look for this title mentioned followed by a draft sentence
            pattern = re.escape(title[:30]) + r".*?(?:Draft|Summary).*?([^.]*\.[^.\n]{0,200}\.)"
            match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            candidate = re.sub(r"\s+", " ", match.group(1)).strip()
            if 40 <= len(candidate) <= 1200 and candidate.endswith("."):
                results[idx] = normalize_story_summary_text(candidate, limit=1200)

    return results if results else None


def extract_qwen_reasoning_summary(reasoning: str) -> str | None:
    """Extract Qwen's draft sentence when LM Studio returns reasoning_content only.

    The local Qwen MTP model can ignore no-thinking flags and put the useful
    draft in reasoning_content with empty message.content. This keeps the host on
    the already-loaded Qwen model instead of loading Gemma.
    """
    text = str(reasoning or "")
    patterns = [
        r"Draft Summary \(Mental\):\s*\n\s*(.+?)(?:\n\s*\d+\.|\n\s*[-*]\s*One sentence|\n\s*Check Constraints|$)",
        r"Draft Summary:\s*\n\s*(.+?)(?:\n\s*\d+\.|\n\s*[-*]\s*One sentence|\n\s*Check Constraints|$)",
        r"Draft 1:\s*(.+?)(?:\n|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        candidate = re.sub(r"\s+", " ", match.group(1)).strip(" -*`\"'")
        candidate = re.sub(r"\s*\*\s*Check constraints.*$", "", candidate, flags=re.IGNORECASE).strip()
        if 40 <= len(candidate) <= 1200 and candidate.endswith((".", "!", "?")):
            return normalize_story_summary_text(candidate, limit=1200)
    return None


def summarize_story_batch_with_lm_studio(articles: list[dict]) -> tuple[dict[int, str], str | None, str | None]:
    """Call local LM Studio for one chunk of story summaries.

    Article indexes are digest-global, so callers can merge successful chunks and
    fall back only failed/missing indexes. Each article entry may represent a
    grouped story with multiple locally available source materials.
    """
    base_url, model, _timeout = lm_studio_summary_config()
    timeout = max(
        _timeout,
        float(os.environ.get("CROSSECT_LM_STUDIO_BATCH_TIMEOUT") or 60),
    )
    url = f"{base_url}/chat/completions"
    if not articles:
        return {}, None, None

    system_prompt = (
        "You write neutral Crossect digest mini-stories from source metadata. Return strict JSON only. "
        "Do not include prose outside JSON, comments, bullets, markdown, or reasoning. "
        "Use only the supplied title, RSS summary, source metadata, headlines, excerpts and URLs; do not invent facts. "
        "Synthesize across multiple source materials when present instead of copying one RSS blurb. "
        "Prefer two concise paragraphs in the summary field; use one substantial paragraph if source material is thin. "
        "Mention disagreement or framing differences only when they are explicit in the supplied material. "
        "Keep tone factual, neutral, digest-style and readable. "
        "Return JSON object {\"summaries\":[...]} with one item per input article: index, summary. "
        "Each summary must be prose only, no bullet lists, around 80-180 words unless the supplied material is too thin."
    )
    user_prompt = (
        "<think>\n\n</think>\n"
        "Return the JSON in assistant content. Do not put the answer only in reasoning_content. "
        "Summarize these grouped stories as strict JSON only. Each summary should read like a 1-2 paragraph mini-story, not a headline blurb:\n"
        + json.dumps({"articles": articles}, ensure_ascii=False)
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": max(420, min(2800, 420 * len(articles) + 180)),
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "crossect_story_summaries",
                "schema": {
                    "type": "object",
                    "properties": {
                        "summaries": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "index": {"type": "integer"},
                                    "summary": {"type": "string"},
                                },
                                "required": ["index", "summary"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["summaries"],
                    "additionalProperties": False,
                },
            },
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", "replace")[:500].replace("\n", " ")
        return {}, f"lm-studio-summary-http-error: {exc.code}: {error_body}", None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        return {}, f"lm-studio-summary-error: {type(exc).__name__}: {exc}", None

    try:
        completion = json.loads(body)
        message = completion["choices"][0]["message"]
        raw_content = message.get("content") or ""
        reasoning_text = message.get("reasoning_content") or ""

        by_index: dict[int, str] | None = None

        def parse_summary_json(source_text: str) -> dict[int, str] | None:
            if not source_text:
                return None
            parsed = extract_json_object(source_text)
            summaries = parsed.get("summaries")
            if not isinstance(summaries, list):
                return None
            parsed_by_index: dict[int, str] = {}
            for item in summaries:
                if not isinstance(item, dict) or "index" not in item:
                    continue
                summary_text = validate_lm_summary(item)
                lower = summary_text.lower()
                if (summary_text.startswith((": ", '"', "'", "- "))
                        or "word count" in lower
                        or "meets constraint" in lower
                        or len(summary_text) < 40):
                    return None
                parsed_by_index[int(item["index"])] = summary_text
            return parsed_by_index or None

        # Try assistant content first. With LM Studio JSON schema enabled on Qwen,
        # the valid JSON may arrive in reasoning_content instead, so parse that as
        # structured JSON before falling back to heuristic reasoning extraction.
        try:
            by_index = parse_summary_json(raw_content)
        except Exception:
            by_index = None
        if not by_index and reasoning_text:
            try:
                by_index = parse_summary_json(reasoning_text)
            except Exception:
                by_index = None
        if not by_index and reasoning_text:
            extracted = extract_qwen_reasoning_summaries_batch(reasoning_text, articles)
            if extracted:
                return extracted, None, reasoning_text

        if not by_index:
            raise ValueError("no valid summaries found in content or reasoning_content")
        return by_index, None, raw_content
    except Exception as exc:
        raw = body[:1000].replace("\n", " ")
        return {}, f"lm-studio-summary-invalid: {type(exc).__name__}: {exc}; raw={raw}", body[:1000]


def summarize_digest_stories_with_lm_studio(digest: dict) -> tuple[dict[int, str], dict[int, str], str | None]:
    """Call local LM Studio for digest story summaries in reliable chunks.

    Returns (summaries_by_index, fallback_reasons_by_index, raw_content). Unlike
    the previous whole-digest request, failures are isolated to the affected
    chunk so successful local Qwen batches still become local AI summaries.
    """
    articles = []
    for idx, (section_index, _story_index, story) in enumerate(iter_digest_stories(digest)):
        links = [link for link in story.get("links", []) if isinstance(link, dict)]
        first_link = links[0] if links else {}
        source_materials = []
        for link_index, link in enumerate(links[:6]):
            source_materials.append({
                "linkIndex": link_index,
                "source": link.get("source") or link.get("outlet") or "",
                "outlet": link.get("outlet") or "",
                "headline": link.get("headline") or link.get("title") or "",
                "excerpt": link.get("excerpt") or link.get("summary") or link.get("description") or "",
                "url": link.get("url") or "",
            })
        articles.append({
            "index": idx,
            "section": digest.get("sections", [{}])[section_index].get("name", "") if section_index < len(digest.get("sections", [])) else "",
            "title": story.get("title") or first_link.get("headline") or "",
            "rssSummary": story.get("summary") or first_link.get("excerpt") or "",
            "source": first_link.get("source") or first_link.get("outlet") or "",
            "url": first_link.get("url") or "",
            "sourceMaterials": source_materials,
        })
    if not articles:
        return {}, {}, None

    batch_size = lm_studio_summary_batch_size()
    summaries_by_index: dict[int, str] = {}
    fallback_reasons_by_index: dict[int, str] = {}
    raw_content = None

    def apply_chunk(chunk: list[dict], requested_size: int, retry_single: bool = True) -> None:
        nonlocal raw_content
        chunk_indexes = [int(article["index"]) for article in chunk]
        chunk_summaries, error, raw = summarize_story_batch_with_lm_studio(chunk)
        if raw and raw_content is None:
            raw_content = raw
        if error:
            # LM Studio/Qwen can occasionally produce malformed outer response
            # JSON for larger chunks. Split failed chunks and retry with the same
            # model before falling back, so a bad response does not poison the
            # rest of the digest.
            if len(chunk) > 1:
                midpoint = max(1, len(chunk) // 2)
                apply_chunk(chunk[:midpoint], len(chunk[:midpoint]))
                apply_chunk(chunk[midpoint:], len(chunk[midpoint:]))
                return
            if retry_single:
                retry_summaries, retry_error, retry_raw = summarize_story_batch_with_lm_studio(chunk)
                if retry_raw and raw_content is None:
                    raw_content = retry_raw
                if not retry_error:
                    chunk_summaries = retry_summaries
                    error = None
                else:
                    error = f"{error[:180]}; retryError={retry_error[:180]}"
            if error:
                reason = f"{error[:300]}; summaryBatchSize={requested_size}; chunkIndexes={chunk_indexes}"
                for index in chunk_indexes:
                    fallback_reasons_by_index[index] = reason[:500]
                return
        for index in chunk_indexes:
            summary = chunk_summaries.get(index)
            if summary:
                summaries_by_index[index] = summary
                fallback_reasons_by_index.pop(index, None)
            else:
                fallback_reasons_by_index[index] = (
                    f"lm-studio-summary-missing-index; summaryBatchSize={requested_size}; chunkIndexes={chunk_indexes}"
                )[:500]

    for start in range(0, len(articles), batch_size):
        apply_chunk(articles[start : start + batch_size], batch_size)
    return summaries_by_index, fallback_reasons_by_index, raw_content


def enrich_digest_story_summaries(digest: dict) -> dict:
    """Write story summaries via one local LM Studio batch call when enabled.

    A deterministic multi-source metadata summary remains the fallback on timeout,
    error, invalid JSON, or missing per-story model output. Summary provenance is
    always marked.
    """
    stories = list(iter_digest_stories(digest))
    if not stories:
        return digest

    for _section_index, _story_index, story in stories:
        story["summary"] = fallback_story_summary(story)
        story["summaryMethod"] = "deterministic-multi-source-mini-story-fallback-v1"

    mode = local_summary_mode()
    if mode != "local":
        for _section_index, _story_index, story in stories:
            story["summaryFallbackReason"] = f"local-summary-skipped: CROSSECT_SUMMARY_MODE={mode}"
        return digest

    summaries_by_index, fallback_reasons_by_index, _raw = summarize_digest_stories_with_lm_studio(digest)

    for idx, (_section_index, _story_index, story) in enumerate(stories):
        summary = summaries_by_index.get(idx)
        if summary:
            story["summary"] = summary
            story["summaryMethod"] = "lm-studio-local-multi-source-mini-story-v1"
            story.pop("summaryFallbackReason", None)
        else:
            story["summaryFallbackReason"] = fallback_reasons_by_index.get(idx, "lm-studio-summary-missing-index")
    return digest


def missing_required_link_metadata(digest: dict) -> list[dict]:
    missing = []
    for section_index, section in enumerate(digest.get("sections", [])):
        for story_index, story in enumerate(section.get("stories", [])):
            for link_index, link in enumerate(story.get("links", [])):
                if not isinstance(link, dict):
                    missing.append({"section": section_index, "story": story_index, "link": link_index, "field": "link-object"})
                    continue
                for field in ("outlet", "bias", "confidence", "alignmentBasis", "reliabilityBasis", "sourceBias", "sourceReliability"):
                    if not str(link.get(field) or "").strip():
                        missing.append({"section": section_index, "story": story_index, "link": link_index, "field": field})
                if link.get("bias") and link.get("bias") not in ALLOWED_BIASES:
                    missing.append({"section": section_index, "story": story_index, "link": link_index, "field": "bias", "value": link.get("bias")})
                if link.get("confidence") and str(link.get("confidence")).lower() not in ALLOWED_CONFIDENCES:
                    missing.append({"section": section_index, "story": story_index, "link": link_index, "field": "confidence", "value": link.get("confidence")})
    return missing
