const state = {
  digests: [],
  currentDigest: null,
  activeSection: "All",
  search: "",
  bias: "All",
  confidence: "All"
};

const els = {
  digestSelect: document.querySelector("#digestSelect"),
  refreshButton: document.querySelector("#refreshButton"),
  digestTitle: document.querySelector("#digestTitle"),
  digestDate: document.querySelector("#digestDate"),
  digestNote: document.querySelector("#digestNote"),
  storyCount: document.querySelector("#storyCount"),
  sourceCount: document.querySelector("#sourceCount"),
  sectionCount: document.querySelector("#sectionCount"),
  biasMix: document.querySelector("#biasMix"),
  searchInput: document.querySelector("#searchInput"),
  sectionFilter: document.querySelector("#sectionFilter"),
  biasFilter: document.querySelector("#biasFilter"),
  confidenceFilter: document.querySelector("#confidenceFilter"),
  sectionTabs: document.querySelector("#sectionTabs"),
  storyList: document.querySelector("#storyList")
};

const biasOrder = ["Left", "Lean Left", "Center", "Lean Right", "Right", "Unknown/Mixed", "Official", "Company"];

function slug(value) {
  return String(value || "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
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
    ...(story.links || []).flatMap((link) => [link.outlet, link.bias, link.quality])
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

async function fetchJson(candidates) {
  let lastError = null;
  for (const candidate of candidates) {
    try {
      const response = await fetch(candidate, { cache: "no-store" });
      if (response.ok) {
        return response.json();
      }
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
    els.digestSelect.append(option(digest.id, digest.date ? `${digest.date} - ${digest.title}` : digest.title));
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
  els.sectionFilter.value = state.activeSection;

  els.biasFilter.replaceChildren(...biases.map((bias) => option(bias)));
  els.biasFilter.value = state.bias;

  els.confidenceFilter.replaceChildren(...confidences.map((confidence) => option(confidence)));
  els.confidenceFilter.value = state.confidence;
}

function renderTabs() {
  const sections = ["All", ...(state.currentDigest?.sections || []).map((section) => section.name)];
  els.sectionTabs.replaceChildren();

  for (const section of sections) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `tab${section === state.activeSection ? " active" : ""}`;
    button.textContent = section;
    button.addEventListener("click", () => {
      state.activeSection = section;
      render();
    });
    els.sectionTabs.append(button);
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

function renderBalance(story) {
  const links = story.links || [];
  const counts = countBias(links);
  const total = Math.max(links.length, 1);

  const wrapper = document.createElement("div");
  wrapper.className = "source-balance";

  const bar = document.createElement("div");
  bar.className = "balance-bar";

  for (const bias of biasOrder) {
    if (!counts[bias]) continue;
    const segment = document.createElement("div");
    segment.className = `balance-segment bias-${slug(bias)}`;
    segment.style.width = `${(counts[bias] / total) * 100}%`;
    bar.append(segment);
  }

  const caption = document.createElement("div");
  caption.className = "balance-caption";
  caption.textContent = `${sourceCount(story)} sources`;

  wrapper.append(bar, caption);
  return wrapper;
}

function renderSourceRow(link) {
  const row = document.createElement("div");
  row.className = "source-row";

  const anchor = document.createElement("a");
  anchor.href = link.url;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  anchor.textContent = link.outlet || "Source";

  const bias = normalizeBias(link.bias);
  const chip = document.createElement("span");
  chip.className = `chip bias-${slug(bias)}`;
  chip.textContent = bias;

  const confidence = document.createElement("span");
  confidence.className = "confidence";
  confidence.textContent = confidenceValue(link.confidence);

  const quality = document.createElement("span");
  quality.className = "quality";
  quality.textContent = link.quality || "";

  row.append(anchor, chip, confidence, quality);
  return row;
}

function renderStory(story) {
  const card = document.createElement("article");
  card.className = "story-card";

  const main = document.createElement("div");
  main.className = "story-main";

  const copy = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = story.title;
  const summary = document.createElement("p");
  summary.textContent = story.summary;
  copy.append(title, summary);

  main.append(copy, renderBalance(story));

  const sourceList = document.createElement("div");
  sourceList.className = "source-list";
  for (const link of story.links || []) {
    sourceList.append(renderSourceRow(link));
  }

  card.append(main, sourceList);
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
  for (const story of stories) {
    if (story.section !== currentSection) {
      currentSection = story.section;
      const heading = document.createElement("div");
      heading.className = "section-heading";
      heading.textContent = currentSection;
      els.storyList.append(heading);
    }

    els.storyList.append(renderStory(story));
  }
}

function renderSummary() {
  const digest = state.currentDigest;
  const stories = allStories(digest);
  const links = allLinks(digest);

  els.digestTitle.textContent = digest?.title || "No digest";
  els.digestDate.textContent = digest?.date || "";
  els.digestNote.textContent = digest?.note || "";
  els.storyCount.textContent = stories.length;
  els.sourceCount.textContent = links.length;
  els.sectionCount.textContent = (digest?.sections || []).length;
}

function render() {
  renderSummary();
  renderFilters();
  renderTabs();
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
  const body = await fetchJson([
    "data/digests/index.json",
    "../data/digests/index.json",
    "api/digests"
  ]);
  state.digests = body.digests || [];
  renderDigestOptions();

  if (state.digests.length) {
    await loadDigest(state.digests[0].id);
    els.digestSelect.value = state.digests[0].id;
  } else {
    render();
  }
}

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
  els.digestNote.textContent = error.message;
});
