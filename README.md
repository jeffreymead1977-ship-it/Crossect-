# Crossect News

Source Balance News is a dashboard for Codex-generated news digests. It does not use OpenAI API billing. Codex gathers and analyzes the news during the automation run, saves a JSON digest, and this app renders the saved digest files.

## Run

```powershell
npm start
```

Then open:

```text
http://localhost:4173
```

## GitHub Pages

This app can run as a static GitHub Pages site. Set GitHub Pages to publish from the `docs` folder on your main branch.

The dashboard reads:

```text
docs/data/digests/index.json
docs/data/digests/*.json
```

For daily external access, the automation needs to save the new JSON digest, update `docs/data/digests/index.json`, then commit and push those files to GitHub. GitHub Pages will serve the latest digest after the push.

The Codex automation runs `scripts/publish-digest.ps1` after each digest to stage only `docs/data/digests`, commit the new/updated digest files, rebase on `origin/main`, and push the update for GitHub Pages.

The publish script runs git in non-interactive mode. If GitHub credentials expire or the push cannot complete, it fails quickly so the automation can email the digest with a publish-failed note instead of waiting for input.

Before publishing, the automation runs `scripts/enrich-digest-images.mjs` to extract real Open Graph/Twitter card images from the linked articles. It skips generic placeholders and leaves the dashboard's clean fallback panel when an article does not expose a usable image.

Suggested Pages settings:

```text
Source: Deploy from a branch
Branch: main
Folder: /docs
```

## Digest Files

Save generated digests as JSON files in:

```text
docs/data/digests
```

Each file should follow the structure shown in `docs/data/digests/2026-05-16-expanded.json`.

Stories can include optional visual fields. Use actual article, official, or publisher Open Graph images only; omit these fields instead of substituting generic topic images.

```json
{
  "imageUrl": "https://stable-image-url.example/image.jpg",
  "imageAlt": "Short factual image description",
  "imageCredit": "Outlet, official source, or Wikimedia Commons"
}
```

Links can include optional preview fields. Link images should come from that article's own metadata or a directly related official source.

```json
{
  "headline": "Display headline",
  "excerpt": "Short paraphrased preview",
  "imageUrl": "https://optional-link-thumbnail.example/image.jpg",
  "imageAlt": "Optional thumbnail description"
}
```
