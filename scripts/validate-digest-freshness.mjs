import fs from "node:fs/promises";
import path from "node:path";

const currentPath = path.resolve(process.argv[2] || "");
const digestsDir = path.resolve(process.argv[3] || path.dirname(currentPath));

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

const report = [
  `Freshness check ${current.id} vs ${previous.id}`,
  `Repeated URLs: ${repeatedUrls.length}/${currentUrls.size} (${Math.round(urlOverlap * 100)}%)`,
  `Similar story titles: ${repeatedStories.length}/${stories(current).length} (${Math.round(storyOverlap * 100)}%)`
];

console.log(report.join("\n"));

if (urlOverlap > 0.25 || storyOverlap > 0.45) {
  console.error("Digest appears stale. Regenerate with fresher current-day sources before publishing.");
  process.exit(1);
}
