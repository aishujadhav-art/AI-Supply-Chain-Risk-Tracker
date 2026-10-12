# AI Supply Chain Risk Tracker

Maps the supply chain behind AI GPUs, tracks the rules that affect it, and estimates how each rule changes the cost of a GPU. Version one covers regulatory risk (US tariffs, US export controls, China's mineral controls). Environmental risk comes next.

## What's inside

| Part | File | What it does |
|---|---|---|
| Dashboard | `index.html` (built from `src/app.html`) | Supply chain map, rule tracker, cost impact model, method |
| Data | `data/rules.json` | Every tracked rule, with sources, stages hit, and review status |
| Scanner | `scanner/scan.py` | Pulls new Federal Register documents and news daily, tags them with Claude, adds them for review |
| Schedule | `.github/workflows/scan.yml` | Runs the scanner every weekday and saves the results |

## Publish on GitHub Pages

1. Create a new **public** repository, for example `ai-supply-chain-tracker`.
2. Upload all files in this folder, keeping the folder structure (including the hidden `.github` folder).
3. Go to **Settings, Pages**. Under "Build and deployment", choose **Deploy from a branch**, branch `main`, folder `/ (root)`. Save.
4. After a minute, your site is live at `https://YOUR-USERNAME.github.io/ai-supply-chain-tracker/`.

## Turn on the daily scanner

1. Get an API key from the Claude Console (console.anthropic.com). API use is billed.
2. In the repository: **Settings, Secrets and variables, Actions, New repository secret**. Name it `ANTHROPIC_API_KEY` and paste the key.
3. Go to **Actions**, open "Daily rule scan", and press **Run workflow** to test it.

Without the key, the scanner still runs with a simple keyword tagger, which is less accurate.

## Review new items

New items appear on the Rule tracker tab under "needs review". To approve one, open `data/rules.json` on GitHub, find the item, change `"review": "pending"` to `"review": "approved"`, and commit. To reject one, delete it and add its `id` to the `"dismissed"` list so it is not picked up again.

The LLM never changes the cost model by itself. Only approved items affect the map and the cost model.

## Edit the dashboard

Edit `src/app.html`, then run:

```
python scanner/build_index.py
```

This rebuilds `index.html`. To view it locally, run `python -m http.server` in this folder and open http://localhost:8000.

## Cost model, in short

Manufacturing cost = GPU price × (1 − gross margin). That cost is split into HBM, logic die, packaging, substrate, and other. A scenario changes component prices, a share of the increase passes to buyers, and any tariff is added on the import value. Default prices and cost splits are illustrative assumptions, marked on the page, to be replaced with sourced figures.

## Limits

Contract prices for chips, memory, and packaging are private, so results show direction and relative size, not exact amounts. Every rule links to its source; check it before relying on it.
