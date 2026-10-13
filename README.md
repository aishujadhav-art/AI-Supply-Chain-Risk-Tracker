# AI Supply Chain Risk Tracker

Maps the supply chain behind AI GPUs, tracks the rules that affect it, and estimates how each rule changes the cost of a GPU. Version one covers regulatory risk: US tariffs, US export controls, and China's critical mineral controls. Environmental risk comes next.

## How it works

1. **Daily scan.** Every weekday, GitHub runs `scanner/scan.py`. It collects recent documents from the Federal Register (official US rules) and news headlines about chip and mineral policy.
2. **AI tagging.** Claude reads each item and fills in a fixed form: is it relevant, what kind of rule, which supply chain stages it hits, any tariff rate or price change, a short summary, a confidence level, and a recommendation (approve or reject) with a reason.
3. **Review on the dashboard.** Relevant items appear on the Rule tracker tab with the AI's recommendation. You press Approve or Reject.
4. **Update.** Approved rules show on the map and can be loaded into the cost model. Rejected items are remembered so the scan skips them next time.

The AI never changes the tracker by itself; a person decides. The cost model is plain code, not the AI.

## Files

| File | Job |
|---|---|
| `index.html` | The dashboard web page (rebuilt automatically, do not edit by hand) |
| `src/app.html` | The dashboard's source: edit this one |
| `data/rules.json` | Every rule and every item awaiting review |
| `scanner/scan.py` | The daily scan |
| `scanner/review.py` | Applies approve or reject decisions |
| `scanner/build_index.py` | Rebuilds `index.html` from `src/app.html` and the data |
| `.github/workflows/scan.yml` | Runs the scan every weekday |
| `.github/workflows/review.yml` | Runs when you press Approve or Reject |

## Setup

1. Upload all files to a public GitHub repository, keeping the folders.
2. Settings, Pages: deploy from branch `main`, folder `/ (root)`.
3. Settings, Actions, General: Workflow permissions, Read and write.
4. Settings, Secrets and variables, Actions: add `ANTHROPIC_API_KEY` with your Claude API key.
5. Settings, General, Features: make sure Issues is ticked (the review buttons use it).
6. Actions tab: run "Daily rule scan" once to test.

## Reviewing

On the dashboard, open Rule tracker. Each item awaiting review shows the AI's suggestion and reason. Press Approve or Reject; a GitHub page opens with the request filled in; press Submit new issue. Within about two minutes the tracker updates and the request closes itself. Only the repository owner's requests are acted on.

## Limits

Contract prices for chips, memory, and packaging are private, so results show direction and relative size, not exact amounts. Default GPU prices and cost splits are assumptions marked on the page. Every rule links to its source.
