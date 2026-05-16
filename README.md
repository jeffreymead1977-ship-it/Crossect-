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
