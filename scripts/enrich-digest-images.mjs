import fs from "node:fs/promises";
import path from "node:path";

const digestPath = path.resolve(process.argv[2] || "data/digests/2026-05-16-expanded.json");
const htmlCache = new Map();

function decodeEntities(value = "") {
  return value
    .replace(/&#x([0-9a-f]+);/gi, (_, hex) => String.fromCodePoint(Number.parseInt(hex, 16)))
    .replace(/&#([0-9]+);/g, (_, decimal) => String.fromCodePoint(Number.parseInt(decimal, 10)))
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .trim();
}

function attrValue(tag, name) {
  const pattern = new RegExp(`${name}\\s*=\\s*([\"'])(.*?)\\1`, "i");
  return decodeEntities(tag.match(pattern)?.[2] || "");
}

function metaValue(html, names) {
  for (const tag of html.match(/<meta\b[^>]*>/gi) || []) {
    const property = attrValue(tag, "property") || attrValue(tag, "name");
    if (names.some((name) => property.toLowerCase() === name.toLowerCase())) {
      const content = attrValue(tag, "content");
      if (content) return content;
    }
  }
  return "";
}

function titleValue(html) {
  const title = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1] || "";
  return decodeEntities(title.replace(/\s+/g, " "));
}

function cleanText(value = "") {
  return decodeEntities(String(value).replace(/\s+/g, " ")).trim();
}

function cleanHeadline(value = "") {
  return cleanText(value)
    .replace(/\s+\|\s+.*$/, "")
    .replace(/\s+-\s+(ABC News|AP News|The Guardian|Reuters|TechCrunch|WIRED|Al Jazeera).*$/i, "");
}

function looksLikeGenericImage(url) {
  const lower = url.toLowerCase();
  return (
    !lower ||
    lower.startsWith("data:") ||
    lower.endsWith(".svg") ||
    lower.includes("logo") ||
    lower.includes("favicon") ||
    lower.includes("apple-touch-icon") ||
    lower.includes("placeholder") ||
    lower.includes("default-image") ||
    lower.includes("avatar")
  );
}

function absoluteUrl(value, base) {
  if (!value) return "";
  try {
    return new URL(value, base).href;
  } catch {
    return "";
  }
}

async function fetchHtml(url) {
  if (htmlCache.has(url)) return htmlCache.get(url);

  const response = await fetch(url, {
    headers: {
      "user-agent": "Mozilla/5.0 (compatible; CrossectNewsBot/1.0; +https://github.com/jeffreymead1977-ship-it/Crossect-)"
    },
    redirect: "follow",
    signal: AbortSignal.timeout(12000)
  });

  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  const html = await response.text();
  htmlCache.set(url, html);
  return html;
}

async function metadataFor(url) {
  const html = await fetchHtml(url);
  const image = absoluteUrl(metaValue(html, ["og:image:secure_url", "og:image", "twitter:image"]), url);

  return {
    title: cleanHeadline(metaValue(html, ["og:title", "twitter:title"]) || titleValue(html)),
    excerpt: cleanText(metaValue(html, ["og:description", "twitter:description", "description"])),
    imageUrl: looksLikeGenericImage(image) ? "" : image
  };
}

function allStories(digest) {
  return digest.sections.flatMap((section) =>
    section.stories.map((story) => ({
      section: section.name,
      story
    }))
  );
}

const digest = JSON.parse(await fs.readFile(digestPath, "utf8"));
let enrichedLinks = 0;
let enrichedImages = 0;

for (const { story } of allStories(digest)) {
  if (story.imageAlt) story.imageAlt = cleanText(story.imageAlt);
  if (story.imageCredit) story.imageCredit = cleanText(story.imageCredit);

  for (const link of story.links || []) {
    if (link.headline) link.headline = cleanHeadline(link.headline);
    if (link.excerpt) link.excerpt = cleanText(link.excerpt);
    if (link.imageAlt) link.imageAlt = cleanText(link.imageAlt);
    if (!link.url || link.url.toLowerCase().endsWith(".pdf")) continue;

    try {
      const metadata = await metadataFor(link.url);
      if (!link.headline && metadata.title) link.headline = metadata.title;
      if (!link.excerpt && metadata.excerpt) link.excerpt = metadata.excerpt;
      if (!link.imageUrl && metadata.imageUrl) {
        link.imageUrl = metadata.imageUrl;
        link.imageAlt = link.headline || story.title;
        enrichedImages += 1;
      }
      enrichedLinks += 1;
    } catch (error) {
      console.warn(`Could not enrich ${link.url}: ${error.message}`);
    }
  }

  const imageSource = (story.links || []).find((link) => link.imageUrl);
  if (imageSource && !story.imageUrl) {
    story.imageUrl = imageSource.imageUrl;
    story.imageAlt = imageSource.imageAlt || imageSource.headline || story.title;
    story.imageCredit = imageSource.outlet || "Article image";
  }
}

await fs.writeFile(digestPath, `${JSON.stringify(digest, null, 2)}\n`);
console.log(`Enriched ${enrichedLinks} links and ${enrichedImages} article images in ${digestPath}.`);
