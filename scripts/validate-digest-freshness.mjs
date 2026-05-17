import fs from "node:fs/promises";
import path from "node:path";

const currentPath = path.resolve(process.argv[2] || "");
const digestsDir = path.resolve(process.argv[3] || path.dirname(currentPath));
const maxRepeatedUrlRatio = 0.25;
const maxSimilarStoryRatio = 0.45;
const maxAustraliaStoryRatio = 0.35;
const maxSingleJournalismFamilyRatio = 0.3;

if (!currentPath) {
  console.error("Usage: node scripts/validate-digest-freshness.mjs <current-digest.json> [digests-dir]");
  process.exit(2);
}

function normalizeUrl(value = "") {
  try {
    const url = new URL(value);
    for (const key of [...url.searchParams.keys()]) {
      if (/^(utm_|fbclid|gclid|mc_cid|mc_eid)/i.test(key)) url.searchParams.delete(key);
    }
    url.hash = "";
    return url.href.replace(/\/$/, "");
  } catch {
    return String(value || "").trim();
  }
}

function words(value = "") {
  return new Set(
    String(value)
      .toLowerCase()
      .replace(/[^a-z0-9\s'-]/g, " ")
      .split(/\s+/)
      .filter((word) => word.length > 3)
  );
}

function titleSimilarity(left = "", right = "") {
  const a = words(left);
  const b = words(right);
  if (!a.size || !b.size) return 0;
  const intersection = [...a].filter((word) => b.has(word)).length;
  const union = new Set([...a, ...b]).size;
  return intersection / union;
}

function stories(digest) {
  return (digest.sections || []).flatMap((section) => section.stories || []);
}

function links(digest) {
  return stories(digest).flatMap((story) => story.links || []);
}

function isOfficialOrPrimary(link) {
  const bias = String(link.bias || "").toLowerCase();
  const quality = String(link.quality || "").toLowerCase();
  return (
    bias === "official" ||
    bias === "company" ||
    /\b(government|court|regulator|official|company|primary source)\b/.test(quality)
  );
}

function hostname(value = "") {
  try {
    return new URL(value).hostname.replace(/^www\./i, "").toLowerCase();
  } catch {
    return "";
  }
}

function sourceFamily(link) {
  const host = hostname(link.url);
  if (host.endsWith("abc.net.au")) return "ABC Australia";
  if (host.endsWith("sbs.com.au")) return "SBS";
  if (host.endsWith("bbc.com") || host.endsWith("bbc.co.uk")) return "BBC";
  if (host.endsWith("apnews.com")) return "AP";
  if (host.endsWith("reuters.com")) return "Reuters";
  if (host.endsWith("aljazeera.com")) return "Al Jazeera";
  if (host.endsWith("theguardian.com")) return "The Guardian";
  if (host.endsWith("news.com.au")) return "News.com.au";
  if (host.endsWith("abcnews.go.com")) return "ABC News US";

  return String(link.outlet || host || "Unknown")
    .replace(/\s*\/.*$/, "")
    .trim();
}

function journalismLinks(digest) {
  return links(digest).filter((link) => !isOfficialOrPrimary(link));
}

function australiaStories(digest) {
  return (digest.sections || [])
    .filter((section) => /australia/i.test(section.name || ""))
    .flatMap((section) => section.stories || []);
}

async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

async function findPreviousDigest(current) {
  const indexPath = path.join(digestsDir, "index.json");
  const index = await readJson(indexPath).catch(() => ({ digests: [] }));
  const previousEntry = (index.digests || [])
    .filter((entry) => entry.id !== current.id && entry.date < current.date)
    .sort((a, b) => b.date.localeCompare(a.date))[0];

  if (previousEntry?.id) {
    return readJson(path.join(digestsDir, `${previousEntry.id}.json`));
  }

  const files = await fs.readdir(digestsDir);
  const candidates = [];
  for (const file of files) {
    if (!file.endsWith(".json") || file === "index.json") continue;
    const digest = await readJson(path.join(digestsDir, file)).catch(() => null);
    if (digest?.id !== current.id && digest?.date < current.date) candidates.push(digest);
  }
  return candidates.sort((a, b) => b.date.localeCompare(a.date))[0] || null;
}

const current = await readJson(currentPath);
const previous = await findPreviousDigest(current);

if (!previous) {
  console.log("No previous digest found; freshness check skipped.");
  process.exit(0);
}

const currentUrls = new Set(links(current).map((link) => normalizeUrl(link.url)).filter(Boolean));
const previousUrls = new Set(links(previous).map((link) => normalizeUrl(link.url)).filter(Boolean));
const repeatedUrls = [...currentUrls].filter((url) => previousUrls.has(url));
const urlOverlap = repeatedUrls.length / Math.max(currentUrls.size, 1);

const previousTitles = stories(previous).map((story) => story.title || "");
const repeatedStories = stories(current).filter((story) =>
  previousTitles.some((title) => titleSimilarity(story.title, title) >= 0.45)
);
const storyOverlap = repeatedStories.length / Math.max(stories(current).length, 1);

const currentStories = stories(current);
const ausStories = australiaStories(current);
const australiaStoryRatio = ausStories.length / Math.max(currentStories.length, 1);
const familyCounts = new Map();
for (const link of journalismLinks(current)) {
  const family = sourceFamily(link);
  familyCounts.set(family, (familyCounts.get(family) || 0) + 1);
}
const journalismLinkCount = [...familyCounts.values()].reduce((sum, count) => sum + count, 0);
const topFamily = [...familyCounts.entries()].sort((a, b) => b[1] - a[1])[0] || ["None", 0];
const topFamilyRatio = topFamily[1] / Math.max(journalismLinkCount, 1);

const report = [
  `Freshness check ${current.id} vs ${previous.id}`,
  `Repeated URLs: ${repeatedUrls.length}/${currentUrls.size} (${Math.round(urlOverlap * 100)}%)`,
  `Similar story titles: ${repeatedStories.length}/${currentStories.length} (${Math.round(storyOverlap * 100)}%)`,
  `Australia stories: ${ausStories.length}/${currentStories.length} (${Math.round(australiaStoryRatio * 100)}%)`,
  `Largest journalism source family: ${topFamily[0]} ${topFamily[1]}/${journalismLinkCount} (${Math.round(topFamilyRatio * 100)}%)`
];

console.log(report.join("\n"));

if (urlOverlap > maxRepeatedUrlRatio || storyOverlap > maxSimilarStoryRatio) {
  console.error("Digest appears stale. Regenerate with fresher current-day sources before publishing.");
  process.exit(1);
}

if (australiaStoryRatio > maxAustraliaStoryRatio) {
  console.error(
    `Digest is too Australia-heavy. Keep Australian stories to ${Math.round(maxAustraliaStoryRatio * 100)}% or less unless the user explicitly overrides it.`
  );
  process.exit(1);
}

if (topFamilyRatio > maxSingleJournalismFamilyRatio) {
  console.error(
    `Digest is too dependent on ${topFamily[0]}. Keep any one journalism source family to ${Math.round(maxSingleJournalismFamilyRatio * 100)}% or less.`
  );
  process.exit(1);
}
