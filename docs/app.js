const state = {
  digests: [],
  currentDigest: null,
  activeSection: "All",
  search: "",
  bias: "All",
  confidence: "All"
};

const els = {
  dateline: document.querySelector("#dateline"),
  digestSelect: document.querySelector("#digestSelect"),
  refreshButton: document.querySelector("#refreshButton"),
  themeToggle: document.querySelector("#themeToggle"),
  sectionTabs: document.querySelector("#sectionTabs"),
  ticker: document.querySelector("#ticker"),
  hero: document.querySelector("#hero"),
  digestSummary: document.querySelector("#digestSummary"),
  digestTitle: document.querySelector("#digestTitle"),
  digestDate: document.querySelector("#digestDate"),
  storyCount: document.querySelector("#storyCount"),
  sourceCount: document.querySelector("#sourceCount"),
  sectionCount: document.querySelector("#sectionCount"),
  biasMix: document.querySelector("#biasMix"),
  searchInput: document.querySelector("#searchInput"),
  sectionFilter: document.querySelector("#sectionFilter"),
  biasFilter: document.querySelector("#biasFilter"),
  confidenceFilter: document.querySelector("#confidenceFilter"),
  storyList: document.querySelector("#storyList")
};

const biasOrder = ["Left", "Lean Left", "Center", "Lean Right", "Right", "Unknown/Mixed", "Official", "Company"];

const sunIcon = `
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <circle cx="12" cy="12" r="4"></circle>
    <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"></path>
  </svg>`;

const moonIcon = `
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
  </svg>`;

function setTheme(theme) {
  const next = theme === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("cn-theme", next);
  els.themeToggle.innerHTML = next === "dark" ? moonIcon : sunIcon;
  els.themeToggle.title = next === "dark" ? "Switch to light mode" : "Switch to dark mode";
  els.themeToggle.setAttribute("aria-label", els.themeToggle.title);
}

function initTheme() {
  setTheme(document.documentElement.getAttribute("data-theme") || "light");
  els.themeToggle.addEventListener("click", () => {
    setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
  });
}

function slug(value) {
  return String(value || "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

function textValue(value) {
  return String(value || "").trim();
}

function safeImageUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(value, window.location.href);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch (error) {
    return "";
  }
}

function normalizeBias(value) {
  const text = String(value || "Unknown/Mixed");
  if (/official/i.test(text)) return "Official";
  if (/company/i.test(text)) return "Company";
  if (/lean left/i.test(text)) return "Lean Left";
  if (/lean right/i.test(text)) return "Lean Right";
  if (/unknown|mixed/i.test(text)) return "Unknown/Mixed";
  if (/left/i.test(text)) return "Left";
  if (/right/i.test(text)) return "Right";
  if (/center|centre/i.test(text)) return "Center";
  return "Unknown/Mixed";
}

function segmentClass(value) {
  const bias = normalizeBias(value);
  if (bias === "Left" || bias === "Lean Left") return "l";
  if (bias === "Center") return "c";
  if (bias === "Right" || bias === "Lean Right") return "r";
  if (bias === "Official") return "o";
  if (bias === "Company") return "co";
  return "u";
}

function confidenceValue(value) {
  return String(value || "unknown").toLowerCase();
}

function allStories(digest = state.currentDigest) {
  if (!digest) return [];
  return (digest.sections || []).flatMap((section) =>
    (section.stories || []).map((story) => ({
      ...story,
      section: section.name
    }))
  );
}

function allLinks(digest = state.currentDigest) {
  return allStories(digest).flatMap((story) => story.links || []);
}

function countBias(links) {
  return links.reduce((counts, link) => {
    const key = normalizeBias(link.bias);
    counts[key] = (counts[key] || 0) + 1;
    return counts;
  }, {});
}

function sourceCount(story) {
  return (story.links || []).length;
}

function storyMatches(story) {
  const haystack = [
    story.title,
    story.summary,
    story.section,
    story.imageCredit,
    ...(story.links || []).flatMap((link) => [link.outlet, link.headline, link.excerpt, link.bias, link.quality])
  ]
    .join(" ")
    .toLowerCase();

  const hasSearch = !state.search || haystack.includes(state.search.toLowerCase());
  const hasSection = state.activeSection === "All" || story.section === state.activeSection;
  const hasBias =
    state.bias === "All" || (story.links || []).some((link) => normalizeBias(link.bias) === state.bias);
  const hasConfidence =
    state.confidence === "All" ||
    (story.links || []).some((link) => confidenceValue(link.confidence) === state.confidence);

  return hasSearch && hasSection && hasBias && hasConfidence;
}

function option(value, label = value) {
  const item = document.createElement("option");
  item.value = value;
  item.textContent = label;
  return item;
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric"
  }).format(date);
}

async function fetchJson(candidates) {
  let lastError = null;
  for (const candidate of candidates) {
    try {
      const response = await fetch(candidate, { cache: "no-store" });
      if (response.ok) return response.json();
      lastError = new Error(`${candidate} returned ${response.status}`);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("No data source available");
}

function renderDigestOptions() {
  els.digestSelect.replaceChildren();
  for (const digest of state.digests) {
    const label = digest.date ? `${digest.date} - ${digest.title}` : digest.title;
    els.digestSelect.append(option(digest.id, label));
  }
}

function renderFilters() {
  const digest = state.currentDigest;
  const sections = ["All", ...(digest?.sections || []).map((section) => section.name)];
  const links = allLinks(digest);
  const biases = ["All", ...biasOrder.filter((bias) => links.some((link) => normalizeBias(link.bias) === bias))];
  const confidences = [
    "All",
    ...Array.from(new Set(links.map((link) => confidenceValue(link.confidence)).filter(Boolean))).sort()
  ];

  els.sectionFilter.replaceChildren(...sections.map((section) => option(section)));
  els.sectionFilter.value = sections.includes(state.activeSection) ? state.activeSection : "All";

  els.biasFilter.replaceChildren(...biases.map((bias) => option(bias)));
  els.biasFilter.value = biases.includes(state.bias) ? state.bias : "All";

  els.confidenceFilter.replaceChildren(...confidences.map((confidence) => option(confidence)));
  els.confidenceFilter.value = confidences.includes(state.confidence) ? state.confidence : "All";
}

function renderTabs() {
  const sections = ["All", ...(state.currentDigest?.sections || []).map((section) => section.name)];
  els.sectionTabs.replaceChildren();

  for (const section of sections) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = section === state.activeSection ? "active" : "";
    button.textContent = section === "All" ? "Front Page" : section;
    button.addEventListener("click", () => {
      state.activeSection = section;
      render();
    });
    els.sectionTabs.append(button);
  }
}

function renderTicker() {
  const digest = state.currentDigest;
  const stories = allStories(digest);
  const links = allLinks(digest);
  const parts = [
    ["Stories", stories.length],
    ["Sources", links.length],
    ["Sections", (digest?.sections || []).length]
  ];

  for (const section of digest?.sections || []) {
    parts.push([section.name, (section.stories || []).length]);
  }

  els.ticker.replaceChildren();
  const doubled = [...parts, ...parts];
  for (const [label, value] of doubled) {
    const span = document.createElement("span");
    const strong = document.createElement("strong");
    strong.textContent = label;
    span.append(strong, ` ${value}`);
    els.ticker.append(span);
  }
}

function primaryStoryImage(story) {
  const storyImage = safeImageUrl(story.imageUrl);
  if (storyImage) {
    return {
      src: storyImage,
      alt: textValue(story.imageAlt) || story.title || "Story image",
      credit: textValue(story.imageCredit)
    };
  }

  const source = (story.links || []).find((link) => safeImageUrl(link.imageUrl));
  if (!source) return null;

  return {
    src: safeImageUrl(source.imageUrl),
    alt: textValue(source.imageAlt) || source.headline || source.outlet || "Article preview",
    credit: textValue(source.outlet)
  };
}

function renderImageFallback(story) {
  const fallback = document.createElement("div");
  fallback.className = "image-fallback";

  const label = document.createElement("span");
  label.textContent = story.section || "News";

  const title = document.createElement("strong");
  title.textContent = story.title || "Story";

  fallback.append(label, title);
  return fallback;
}

function renderStoryImage(story, className = "story-image") {
  const image = primaryStoryImage(story);
  const wrapper = document.createElement("div");
  wrapper.className = className;

  if (image?.src) {
    const img = document.createElement("img");
    img.src = image.src;
    img.alt = image.alt;
    img.loading = "lazy";
    img.addEventListener("error", () => {
      wrapper.classList.add("is-placeholder");
      wrapper.replaceChildren(renderImageFallback(story));
    });
    wrapper.append(img);

    if (image.credit) {
      const credit = document.createElement("span");
      credit.className = "image-credit";
      credit.textContent = image.credit;
      wrapper.append(credit);
    }
  } else {
    wrapper.classList.add("is-placeholder");
    wrapper.append(renderImageFallback(story));
  }

  return wrapper;
}

function renderCoverageStrip(story) {
  const links = story.links || [];
  const wrapper = document.createElement("div");
  wrapper.className = "coverage-strip";

  for (const link of links) {
    const segment = document.createElement("div");
    segment.className = `seg ${segmentClass(link.bias)}`;
    wrapper.append(segment);
  }

  const label = document.createElement("span");
  label.className = "coverage-label";
  label.textContent = `${sourceCount(story)} sources`;
  wrapper.append(label);
  return wrapper;
}

function renderSourceRow(link) {
  const row = document.createElement("div");
  row.className = "source-row";

  const thumbUrl = safeImageUrl(link.imageUrl);
  const sourceMain = document.createElement("div");
  sourceMain.className = `source-main${thumbUrl ? " has-thumb" : ""}`;

  if (thumbUrl) {
    const thumb = document.createElement("img");
    thumb.className = "source-thumb";
    thumb.src = thumbUrl;
    thumb.alt = textValue(link.imageAlt) || link.outlet || "Article preview";
    thumb.loading = "lazy";
    thumb.addEventListener("error", () => thumb.remove());
    sourceMain.append(thumb);
  }

  const sourceCopy = document.createElement("div");
  sourceCopy.className = "source-copy";

  const anchor = document.createElement("a");
  anchor.href = link.url;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  anchor.textContent = link.headline || link.outlet || "Source";

  const outlet = document.createElement("span");
  outlet.className = "source-outlet";
  outlet.textContent = link.headline && link.outlet ? link.outlet : "";

  const excerpt = document.createElement("span");
  excerpt.className = "source-excerpt";
  excerpt.textContent = link.excerpt || "";

  sourceCopy.append(anchor);
  if (outlet.textContent) sourceCopy.append(outlet);
  if (excerpt.textContent) sourceCopy.append(excerpt);
  sourceMain.append(sourceCopy);

  const chip = document.createElement("span");
  const bias = normalizeBias(link.bias);
  chip.className = `chip bias-${slug(bias)}`;
  chip.textContent = bias;

  const confidence = document.createElement("span");
  confidence.className = "confidence";
  confidence.textContent = confidenceValue(link.confidence);

  const quality = document.createElement("span");
  quality.className = "quality";
  quality.textContent = link.quality || "";

  row.append(sourceMain, chip, confidence);
  if (quality.textContent) row.append(quality);
  return row;
}

function storiesForActiveSection() {
  const stories = allStories();
  return stories.filter((story) => state.activeSection === "All" || story.section === state.activeSection);
}

function renderHero() {
  const stories = storiesForActiveSection();
  const lead = stories[0];
  els.hero.replaceChildren();

  if (!lead) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No stories available for this section.";
    els.hero.append(empty);
    return;
  }

  const article = document.createElement("article");
  article.className = "lead";
  article.append(renderStoryImage(lead, "lead-image"));

  const kicker = document.createElement("div");
  kicker.className = "kicker";
  const dot = document.createElement("span");
  dot.className = "live-dot";
  kicker.append(dot, `${lead.section} - ${sourceCount(lead)} sources`);

  const title = document.createElement("h2");
  title.textContent = lead.title;

  const summary = document.createElement("p");
  summary.className = "standfirst";
  summary.textContent = lead.summary;

  const byline = document.createElement("div");
  byline.className = "byline";
  byline.append(formatDate(state.currentDigest?.date), " - ", `${allLinks().length} source links indexed`);

  article.append(kicker, title, summary, renderCoverageStrip(lead), byline);

  const brief = document.createElement("aside");
  brief.className = "brief";

  const briefHead = document.createElement("div");
  briefHead.className = "brief-head";
  const label = document.createElement("span");
  label.className = "label";
  label.textContent = "Today's Brief";
  const count = document.createElement("span");
  count.className = "count";
  count.textContent = `${stories.length} stories`;
  briefHead.append(label, count);
  brief.append(briefHead);

  for (const [index, story] of stories.slice(1, 6).entries()) {
    brief.append(renderBriefItem(story, index + 1));
  }

  els.hero.append(article, brief);
}

function renderBriefItem(story, index) {
  const item = document.createElement("div");
  item.className = "brief-item";

  const num = document.createElement("span");
  num.className = "num";
  num.textContent = String(index).padStart(2, "0");

  const copy = document.createElement("div");
  const body = document.createElement("div");
  body.className = "body";
  body.textContent = story.title;
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = `${story.section} - ${sourceCount(story)} sources`;
  copy.append(body, meta);

  const conf = document.createElement("span");
  conf.className = "conf mono";
  const dot = document.createElement("span");
  dot.className = "conf-dot";
  conf.append(dot, "LIVE");

  item.append(num, copy, conf);
  return item;
}

function renderStory(story, index) {
  const card = document.createElement("article");
  card.className = `story-card${index % 3 === 2 ? " compact" : ""}`;

  card.append(renderStoryImage(story));

  const section = document.createElement("div");
  section.className = "story-section";
  section.textContent = story.section;

  const title = document.createElement("h3");
  title.textContent = story.title;

  const summary = document.createElement("p");
  summary.className = "dek";
  summary.textContent = story.summary;

  const sourceList = document.createElement("div");
  sourceList.className = "source-list";
  for (const link of story.links || []) {
    sourceList.append(renderSourceRow(link));
  }

  card.append(section, title, summary, renderCoverageStrip(story), sourceList);
  return card;
}

function renderStories() {
  const stories = allStories().filter(storyMatches);
  els.storyList.replaceChildren();

  if (!stories.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No matching stories.";
    els.storyList.append(empty);
    return;
  }

  let currentSection = "";
  let visibleIndex = 0;
  for (const story of stories) {
    if (story.section !== currentSection) {
      currentSection = story.section;
      const heading = document.createElement("div");
      heading.className = "section-heading";
      heading.textContent = currentSection;
      els.storyList.append(heading);
    }

    els.storyList.append(renderStory(story, visibleIndex));
    visibleIndex += 1;
  }
}

function renderBiasMix() {
  const links = allLinks();
  const counts = countBias(links);
  const total = Math.max(links.length, 1);
  els.biasMix.replaceChildren();

  for (const bias of biasOrder) {
    if (!counts[bias]) continue;
    const row = document.createElement("div");
    row.className = "mix-row";

    const label = document.createElement("span");
    label.textContent = bias;

    const track = document.createElement("div");
    track.className = "mix-track";

    const fill = document.createElement("div");
    fill.className = `mix-fill bias-${slug(bias)}`;
    fill.style.width = `${Math.max((counts[bias] / total) * 100, 4)}%`;
    track.append(fill);

    const count = document.createElement("span");
    count.textContent = counts[bias];

    row.append(label, track, count);
    els.biasMix.append(row);
  }
}

function renderSummary() {
  const digest = state.currentDigest;
  const stories = allStories(digest);
  const links = allLinks(digest);
  const date = digest?.date || "";

  els.dateline.textContent = date ? `${formatDate(date)} - Daily Source Digest` : "Daily Source Digest";
  els.digestTitle.textContent = digest?.title || "No digest";
  els.digestDate.textContent = formatDate(date) || "";
  els.storyCount.textContent = stories.length;
  els.sourceCount.textContent = links.length;
  els.sectionCount.textContent = (digest?.sections || []).length;
  els.digestSummary.textContent = `${stories.length} stories - ${links.length} source links`;
}

function render() {
  renderSummary();
  renderFilters();
  renderTabs();
  renderTicker();
  renderHero();
  renderBiasMix();
  renderStories();
}

async function loadDigest(id) {
  const digestFile = `${encodeURIComponent(id)}.json`;
  state.currentDigest = await fetchJson([
    `data/digests/${digestFile}`,
    `../data/digests/${digestFile}`,
    `api/digests/${encodeURIComponent(id)}`
  ]);
  state.activeSection = "All";
  state.bias = "All";
  state.confidence = "All";
  state.search = "";
  els.searchInput.value = "";
  render();
}

async function loadDigests() {
  const body = await fetchJson(["data/digests/index.json", "../data/digests/index.json", "api/digests"]);
  state.digests = body.digests || [];
  renderDigestOptions();

  if (state.digests.length) {
    await loadDigest(state.digests[0].id);
    els.digestSelect.value = state.digests[0].id;
  } else {
    render();
  }
}

initTheme();

els.digestSelect.addEventListener("change", () => loadDigest(els.digestSelect.value));
els.refreshButton.addEventListener("click", loadDigests);
els.searchInput.addEventListener("input", (event) => {
  state.search = event.target.value;
  renderStories();
});
els.sectionFilter.addEventListener("change", (event) => {
  state.activeSection = event.target.value;
  render();
});
els.biasFilter.addEventListener("change", (event) => {
  state.bias = event.target.value;
  renderStories();
});
els.confidenceFilter.addEventListener("change", (event) => {
  state.confidence = event.target.value;
  renderStories();
});

loadDigests().catch((error) => {
  els.digestTitle.textContent = "Could not load digests";
  els.digestDate.textContent = error.message;
  els.dateline.textContent = "Digest unavailable";
});
