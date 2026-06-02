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
DEFAULT_LM_STUDIO_SUMMARY_MODEL = "gemma-4-26b-a4b-it"
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


def matching_cues(text: str, patterns: list[str]) -> list[str]:
    matches = []
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            # Keep basis readable while not leaking regex syntax into every entry.
            matches.append(pattern.replace(r"\b", "").replace("?", "").replace("\\", ""))
    return matches


def judge_article_alignment(link: dict, metadata: dict) -> tuple[str, str]:
    """Judge alignment from article text first; source metadata is fallback only."""
    text = article_text(link)
    scores: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}

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

    for provenance in ("Official", "Company"):
        if scores.get(provenance):
            return provenance, f"article-text: {provenance.lower()} provenance cue(s): {', '.join(evidence[provenance])}"

    fallback = metadata.get("bias", DEFAULT_METADATA["bias"])
    return fallback, f"source-default-fallback: no article alignment cues; source prior={fallback}"


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

    Link alignment/reliability ratings intentionally keep lm_studio_config()'s
    Qwen hard-pin and deterministic fallback. Story summaries use a separate
    non-thinking local model because the Qwen MTP endpoint can emit reasoning-only
    content or time out on batch summary JSON.
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
            rating_method = "lm-studio-local-article-json-v1"
        else:
            alignment, alignment_basis = judge_article_alignment(enriched, metadata)
            confidence, reliability_basis = judge_article_reliability(enriched, metadata)
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
        "Use Official only for government/court/regulator/official-source dispatches; use Company only for company/product/earnings/startup items. "
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
        link["bias"] = judgement["bias"]
        link["alignment"] = judgement["bias"]
        link["confidence"] = judgement["confidence"]
        link["reliability"] = judgement["confidence"]
        link["alignmentBasis"] = "lm-studio-batch: " + judgement["alignmentBasis"]
        link["reliabilityBasis"] = "lm-studio-batch: " + judgement["reliabilityBasis"]
        link["ratingMethod"] = "lm-studio-local-digest-batch-json-v1"
    return digest


def iter_digest_stories(digest: dict):
    """Yield (section_index, story_index, story) for story dicts."""
    for section_index, section in enumerate(digest.get("sections", [])):
        for story_index, story in enumerate(section.get("stories", [])):
            if isinstance(story, dict):
                yield section_index, story_index, story


def validate_lm_summary(parsed: dict) -> str:
    summary = str(parsed.get("summary") or "").strip()
    if not summary:
        raise ValueError("missing summary")
    return re.sub(r"\s+", " ", summary)[:500]


def summarize_digest_stories_with_lm_studio(digest: dict) -> tuple[dict[int, str], str | None, str | None]:
    """Call local LM Studio once for all story summaries in a digest.

    Returns (summaries_by_index, error, raw_content). This deliberately uses a
    summary-specific LM Studio model and makes one request per digest, not one
    request per story.
    """
    base_url, model, _timeout = lm_studio_summary_config()
    timeout = max(
        _timeout,
        float(os.environ.get("CROSSECT_LM_STUDIO_BATCH_TIMEOUT") or 60),
    )
    url = f"{base_url}/chat/completions"
    articles = []
    for idx, (_section_index, _story_index, story) in enumerate(iter_digest_stories(digest)):
        first_link = next((link for link in story.get("links", []) if isinstance(link, dict)), {})
        articles.append({
            "index": idx,
            "title": story.get("title") or first_link.get("headline") or "",
            "rssSummary": story.get("summary") or first_link.get("excerpt") or "",
            "source": first_link.get("source") or first_link.get("outlet") or "",
            "url": first_link.get("url") or "",
        })
    if not articles:
        return {}, None, None

    system_prompt = (
        "You write concise news story summaries for Crossect. Return strict JSON only. "
        "Do not include markdown, prose outside JSON, comments, or reasoning. "
        "Use only the supplied title, RSS summary, source and URL. Do not invent facts. "
        "Return JSON object {\"summaries\":[...]} with one item per input article: index, summary. "
        "Each summary must be one neutral sentence, 18-35 words, and non-empty."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({"articles": articles}, ensure_ascii=False)},
        ],
        "temperature": 0,
        "max_tokens": max(1000, min(5000, 80 * len(articles))),
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
        return {}, f"lm-studio-summary-http-error: {exc.code}: {error_body}", None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        return {}, f"lm-studio-summary-error: {type(exc).__name__}: {exc}", None

    try:
        completion = json.loads(body)
        raw_content = completion["choices"][0]["message"]["content"]
        parsed = extract_json_object(raw_content)
        summaries = parsed.get("summaries")
        if not isinstance(summaries, list):
            raise ValueError("summaries was not a list")
        by_index: dict[int, str] = {}
        for item in summaries:
            if not isinstance(item, dict) or "index" not in item:
                continue
            by_index[int(item["index"])] = validate_lm_summary(item)
        return by_index, None, raw_content
    except Exception as exc:
        raw = body[:1000].replace("\n", " ")
        return {}, f"lm-studio-summary-invalid: {type(exc).__name__}: {exc}; raw={raw}", body[:1000]


def enrich_digest_story_summaries(digest: dict) -> dict:
    """Write story summaries via one local LM Studio batch call when enabled.

    Existing RSS/feed summaries remain the fallback on timeout, error, invalid JSON,
    or missing per-story model output. Summary provenance is always marked.
    """
    stories = list(iter_digest_stories(digest))
    if not stories:
        return digest

    for _section_index, _story_index, story in stories:
        if not str(story.get("summary") or "").strip():
            story["summary"] = str(story.get("title") or "").strip()
        story["summaryMethod"] = "rss-feed-fallback-v1"

    mode = local_rating_mode()
    if mode != "local":
        for _section_index, _story_index, story in stories:
            story["summaryFallbackReason"] = f"local-summary-skipped: CROSSECT_RATING_MODE={mode}"
        return digest

    summaries_by_index, error, _raw = summarize_digest_stories_with_lm_studio(digest)
    if error:
        for _section_index, _story_index, story in stories:
            story["summaryFallbackReason"] = error[:240]
        return digest

    for idx, (_section_index, _story_index, story) in enumerate(stories):
        summary = summaries_by_index.get(idx)
        if summary:
            story["summary"] = summary
            story["summaryMethod"] = "lm-studio-local-digest-batch-json-v1"
            story.pop("summaryFallbackReason", None)
        else:
            story["summaryFallbackReason"] = "lm-studio-summary-missing-index"
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
