const http = require("http");
const fs = require("fs/promises");
const path = require("path");

const ROOT = __dirname;
const PUBLIC_DIR = path.join(ROOT, "docs");
const DATA_DIR = path.join(PUBLIC_DIR, "data", "digests");
const PORT = Number(process.env.PORT || 4173);

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".ico": "image/x-icon"
};

function send(res, status, body, type = "text/plain; charset=utf-8") {
  res.writeHead(status, {
    "Content-Type": type,
    "Cache-Control": "no-store"
  });
  res.end(body);
}

function json(res, status, body) {
  send(res, status, JSON.stringify(body), "application/json; charset=utf-8");
}

function safeDigestId(id) {
  return /^[a-zA-Z0-9._-]+$/.test(id) ? id : null;
}

async function readDigest(fileName) {
  const filePath = path.join(DATA_DIR, fileName);
  const raw = await fs.readFile(filePath, "utf8");
  return JSON.parse(raw);
}

function summarizeDigest(digest) {
  const sections = digest.sections || [];
  const stories = sections.flatMap((section) => section.stories || []);
  const sources = stories.flatMap((story) => story.links || []);

  return {
    id: digest.id,
    date: digest.date,
    title: digest.title,
    generatedAt: digest.generatedAt,
    note: digest.note,
    sectionCount: sections.length,
    storyCount: stories.length,
    sourceCount: sources.length,
    sections: sections.map((section) => ({
      name: section.name,
      storyCount: (section.stories || []).length
    }))
  };
}

async function handleApi(req, res, pathname) {
  if (pathname === "/api/digests") {
    const entries = await fs.readdir(DATA_DIR, { withFileTypes: true }).catch(() => []);
    const files = entries
      .filter((entry) => entry.isFile() && entry.name.endsWith(".json") && entry.name !== "index.json")
      .map((entry) => entry.name);

    const digests = [];
    for (const file of files) {
      try {
        digests.push(summarizeDigest(await readDigest(file)));
      } catch (error) {
        digests.push({
          id: file.replace(/\.json$/, ""),
          title: file,
          error: "Could not parse digest"
        });
      }
    }

    digests.sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
    json(res, 200, { digests });
    return;
  }

  const match = pathname.match(/^\/api\/digests\/(.+)$/);
  if (match) {
    const id = safeDigestId(match[1]);
    if (!id) {
      json(res, 400, { error: "Invalid digest id" });
      return;
    }

    const fileName = id.endsWith(".json") ? id : `${id}.json`;
    try {
      json(res, 200, await readDigest(fileName));
    } catch (error) {
      json(res, 404, { error: "Digest not found" });
    }
    return;
  }

  json(res, 404, { error: "Not found" });
}

async function handleStatic(req, res, pathname) {
  const requested = pathname === "/" ? "/index.html" : pathname;
  const decoded = decodeURIComponent(requested);
  const filePath = path.normalize(path.join(PUBLIC_DIR, decoded));

  if (!filePath.startsWith(PUBLIC_DIR)) {
    send(res, 403, "Forbidden");
    return;
  }

  try {
    const body = await fs.readFile(filePath);
    send(res, 200, body, MIME_TYPES[path.extname(filePath)] || "application/octet-stream");
  } catch (error) {
    const fallback = await fs.readFile(path.join(PUBLIC_DIR, "index.html"));
    send(res, 200, fallback, MIME_TYPES[".html"]);
  }
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
    if (url.pathname.startsWith("/api/")) {
      await handleApi(req, res, url.pathname);
      return;
    }

    await handleStatic(req, res, url.pathname);
  } catch (error) {
    json(res, 500, { error: "Server error" });
  }
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`Source Balance News running at http://localhost:${PORT}`);
});
