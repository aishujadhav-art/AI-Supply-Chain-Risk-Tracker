"""Daily rule scanner for the AI Supply Chain Risk Tracker.

1. Pulls recent documents from the Federal Register API (official US rules)
   and recent news headlines (Google News RSS) about AI chip supply chain policy.
2. Tags each item with Claude (rule type, status, stages hit, countries,
   key numbers, summary, confidence). Without ANTHROPIC_API_KEY it falls back
   to a simple keyword tagger so the pipeline still runs.
3. Appends relevant, new items to data/rules.json with review set to "pending".
   A person approves them by changing "review" to "approved".

Usage:
    python scanner/scan.py                 # live run
    python scanner/scan.py --dry-run       # print results, do not save
    python scanner/scan.py --sample FILE   # tag items from a local JSON file (testing)

Environment variables:
    ANTHROPIC_API_KEY   enables LLM tagging
    CLAUDE_MODEL        default claude-sonnet-5-5
    LOOKBACK_DAYS       default 10
    MAX_ITEMS           default 40 (caps LLM calls per run)
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.parse
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, "data", "rules.json")
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "10"))
MAX_ITEMS = int(os.environ.get("MAX_ITEMS", "40"))
UA = {"User-Agent": "ai-supply-chain-risk-tracker/1.0 (personal research project)"}

# Stage ids match the supply chain map in src/app.html.
STAGES = {
    "si": "Silicon (quartz, polysilicon)",
    "ne": "Neon and noble gases",
    "gg": "Gallium, germanium",
    "w": "Tungsten",
    "re": "Rare earths",
    "ta": "Tantalum",
    "cu": "Copper",
    "wf": "Silicon wafers",
    "gs": "Specialty gases",
    "pr": "Photoresists",
    "ch": "Process chemicals and slurries",
    "tg": "Sputter targets",
    "tp": "Chipmaking tool components",
    "abf": "ABF film",
    "eda": "Chip design software and IP",
    "li": "Lithography tools",
    "de": "Deposition and etch tools",
    "in": "Inspection tools",
    "cl": "Cleaning tools",
    "ds": "Chip designers (NVIDIA, AMD)",
    "ld": "Logic die / foundry (TSMC)",
    "hb": "HBM memory",
    "sb": "Package substrate",
    "cw": "Advanced packaging (CoWoS)",
    "gpu": "Finished AI GPU",
}

FR_TERMS = [
    "semiconductor",
    '"advanced computing"',
    '"integrated circuits"',
    '"high bandwidth memory"',
    '"semiconductor manufacturing equipment"',
    "gallium",
    "germanium",
    '"rare earth"',
    "tungsten",
]
NEWS_QUERIES = [
    "semiconductor export controls",
    "AI chip tariff Section 232",
    "China gallium germanium export controls",
    "China rare earth export controls",
    "HBM export controls",
    "CoWoS packaging capacity",
]

# Keyword fallback rules: (regex, stages)
KEYWORD_STAGES = [
    (r"\bgallium|germanium\b", ["gg"]),
    (r"rare earth", ["re"]),
    (r"tungsten", ["w"]),
    (r"high bandwidth memory|\bHBM\b", ["hb"]),
    (r"advanced computing|\bGPU|AI chip|accelerator|3A090", ["gpu", "ds"]),
    (r"semiconductor manufacturing equipment|lithograph|\bEUV\b|etch|deposition", ["li", "de", "in", "tp"]),
    (r"foundr|wafer fabrication|integrated circuit|semiconductor", ["ld"]),
    (r"CoWoS|advanced packaging", ["cw"]),
    (r"substrate|\bABF\b", ["sb"]),
]

SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean", "description": "True only if this affects the cost, supply, or legal status of AI GPUs or their supply chain stages listed."},
        "title": {"type": "string", "description": "Short plain title for the rule or event."},
        "jurisdiction": {"type": "string", "description": "Government that issued it, e.g. United States, China, European Union."},
        "type": {"type": "string", "enum": ["tariff", "export_control", "mineral_control", "other"]},
        "status": {"type": "string", "enum": ["proposed", "final", "in_effect", "announced", "suspended", "unknown"]},
        "effective": {"type": ["string", "null"], "description": "Effective date YYYY-MM-DD if stated, else null."},
        "stages": {"type": "array", "items": {"type": "string", "enum": list(STAGES.keys())}},
        "countries": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string", "description": "Two plain sentences: what it does and why it matters for AI GPUs."},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1, "description": "How sure you are of the tagging, given the text available."},
        "model_effect": {
            "type": "object",
            "properties": {
                "input": {"type": "string", "enum": ["tariff", "hbm", "logic", "pack", "sub", "mineral", "none"]},
                "value": {"type": ["number", "null"], "description": "Percent change or tariff rate stated in the text; null if not stated."},
                "note": {"type": "string"},
            },
            "required": ["input", "value", "note"],
        },
    },
    "required": ["relevant", "title", "jurisdiction", "type", "status", "stages", "countries", "summary", "confidence", "model_effect"],
}

PROMPT = """You tag documents for a tracker of regulatory risk in the AI GPU supply chain.

Supply chain stages (use these ids only):
{stages}

Model inputs: "tariff" (tariff rate on imported GPUs), "hbm", "logic", "pack", "sub" (percent price change of HBM, logic die, packaging, substrate), "mineral" (percent price change of critical minerals), or "none".

Rules for tagging:
- Mark relevant=false for documents that do not affect AI GPUs or the stages above (for example anti dumping cases on unrelated products, or routine notices).
- Only state numbers that appear in the text. Never guess a tariff rate.
- News items are reports, not rules: set status to "announced" or "unknown" unless the text clearly says a rule took effect.
- Lower confidence when the text is short or vague.

Document:
Source: {source}
Title: {title}
Date: {date}
Agencies: {agencies}
Text: {text}
"""


def since_date():
    return (dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()


def fetch_federal_register(since):
    items = {}
    fields = ["title", "abstract", "html_url", "publication_date", "type", "document_number", "agencies", "effective_on"]
    for term in FR_TERMS:
        params = [("conditions[term]", term), ("conditions[publication_date][gte]", since), ("per_page", "50"), ("order", "newest")]
        params += [("fields[]", f) for f in fields]
        try:
            r = requests.get("https://www.federalregister.gov/api/v1/documents.json", params=params, headers=UA, timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"Federal Register request failed for {term}: {e}", file=sys.stderr)
            continue
        for d in r.json().get("results", []):
            iid = "FR-" + d["document_number"]
            items[iid] = {
                "id": iid,
                "source": "Federal Register",
                "official": True,
                "title": d.get("title") or "",
                "text": d.get("abstract") or "",
                "url": d.get("html_url"),
                "date": d.get("publication_date"),
                "effective": d.get("effective_on"),
                "agencies": [a.get("name") for a in (d.get("agencies") or []) if a.get("name")],
            }
    return list(items.values())


def fetch_news():
    items = {}
    for q in NEWS_QUERIES:
        url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{q} when:{LOOKBACK_DAYS}d") + "&hl=en-US&gl=US&ceid=US:en"
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            root = ElementTree.fromstring(r.content)
        except (requests.RequestException, ElementTree.ParseError) as e:
            print(f"News request failed for {q}: {e}", file=sys.stderr)
            continue
        for it in list(root.iter("item"))[:10]:
            link = (it.findtext("link") or "").strip()
            title = (it.findtext("title") or "").strip()
            if not link or not title:
                continue
            iid = "NEWS-" + hashlib.sha1(link.encode()).hexdigest()[:12]
            pub = it.findtext("pubDate")
            try:
                date = parsedate_to_datetime(pub).date().isoformat() if pub else None
            except (TypeError, ValueError):
                date = None
            desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or "")
            items[iid] = {
                "id": iid,
                "source": (it.findtext("source") or "News").strip(),
                "official": False,
                "title": title,
                "text": desc.strip(),
                "url": link,
                "date": date,
                "effective": None,
                "agencies": [],
            }
    return list(items.values())


def tag_with_claude(item):
    import anthropic

    client = anthropic.Anthropic()
    stages_txt = "\n".join(f"- {k}: {v}" for k, v in STAGES.items())
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        tools=[{"name": "record_rule", "description": "Record how this document affects the AI GPU supply chain.", "input_schema": SCHEMA}],
        tool_choice={"type": "tool", "name": "record_rule"},
        messages=[{
            "role": "user",
            "content": PROMPT.format(
                stages=stages_txt,
                source=item["source"],
                title=item["title"],
                date=item.get("date"),
                agencies=", ".join(item.get("agencies") or []) or "n/a",
                text=(item.get("text") or "")[:6000] or "(no abstract available)",
            ),
        }],
    )
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use":
            return block.input
    return None


def tag_with_keywords(item):
    blob = f"{item['title']} {item.get('text', '')}"
    stages = []
    for pattern, ids in KEYWORD_STAGES:
        if re.search(pattern, blob, re.I):
            stages += [s for s in ids if s not in stages]
    if not stages:
        return {"relevant": False}
    low = blob.lower()
    if "tariff" in low or "section 232" in low or "duty" in low:
        rtype = "tariff"
    elif any(w in low for w in ["gallium", "germanium", "rare earth", "tungsten"]) and "china" in low:
        rtype = "mineral_control"
    elif "export" in low or "entity list" in low or "license" in low:
        rtype = "export_control"
    else:
        rtype = "other"
    rate = re.search(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)", blob)
    return {
        "relevant": rtype != "other",
        "title": item["title"],
        "jurisdiction": "United States" if item["official"] else "Unclear",
        "type": rtype,
        "status": "unknown",
        "effective": item.get("effective"),
        "stages": stages,
        "countries": [],
        "summary": (item.get("text") or item["title"])[:300],
        "confidence": 0.3,
        "model_effect": {
            "input": "tariff" if rtype == "tariff" and rate else "none",
            "value": float(rate.group(1)) if rtype == "tariff" and rate else None,
            "note": "Keyword tagger: check the source before modeling.",
        },
    }


def conf_label(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "low"
    return "high" if x >= 0.75 else "medium" if x >= 0.5 else "low"


def to_entry(item, tag, tagger):
    me = tag.get("model_effect") or {"input": "none", "value": None, "note": ""}
    return {
        "id": item["id"],
        "title": tag.get("title") or item["title"],
        "jurisdiction": tag.get("jurisdiction") or "Unclear",
        "type": tag.get("type") or "other",
        "status": tag.get("status") or "unknown",
        "review": "pending",
        "date": item.get("date"),
        "effective": tag.get("effective") or item.get("effective"),
        "stages": [s for s in (tag.get("stages") or []) if s in STAGES],
        "countries": tag.get("countries") or [],
        "summary": tag.get("summary") or "",
        "source_name": item["source"],
        "source_url": item.get("url"),
        "confidence": conf_label(tag.get("confidence")),
        "official": item["official"],
        "tagged_by": tagger,
        "found_on": dt.date.today().isoformat(),
        "model_effect": me,
    }


def load_data():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def run(items, dry_run=False):
    data = load_data()
    seen = {r["id"] for r in data["rules"]}
    seen |= set(data.get("dismissed", []))
    new_items = [i for i in items if i["id"] not in seen]
    # Official documents first, newest first within each group.
    new_items.sort(key=lambda i: i.get("date") or "", reverse=True)
    new_items.sort(key=lambda i: not i["official"])
    new_items = new_items[:MAX_ITEMS]
    use_llm = bool(os.environ.get("ANTHROPIC_API_KEY"))
    tagger = f"claude:{MODEL}" if use_llm else "keywords"
    added = []
    skipped = []
    for it in new_items:
        tag = None
        if use_llm:
            try:
                tag = tag_with_claude(it)
            except Exception as e:  # keep the daily run alive if one call fails
                print(f"LLM tagging failed for {it['id']}: {e}", file=sys.stderr)
        if tag is None:
            tag = tag_with_keywords(it)
            this_tagger = "keywords"
        else:
            this_tagger = tagger
        if tag.get("relevant"):
            added.append(to_entry(it, tag, this_tagger))
        else:
            skipped.append(it["id"])
    data["rules"].extend(added)
    # Remember irrelevant items so they are not re-tagged tomorrow (keep the list bounded).
    data["dismissed"] = (data.get("dismissed", []) + skipped)[-2000:]
    data["last_scan"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    data["last_scan_note"] = f"Checked {len(new_items)} new items with {tagger}; added {len(added)} for review."
    print(data["last_scan_note"])
    for a in added:
        print(f"  + [{a['type']}] {a['title']} ({a['source_name']}, {a['confidence']})")
    if not dry_run:
        save_data(data)
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sample", help="JSON file with a list of items to tag instead of fetching")
    ap.add_argument("--no-news", action="store_true")
    args = ap.parse_args()
    if args.sample:
        with open(args.sample, encoding="utf-8") as f:
            items = json.load(f)
    else:
        since = since_date()
        items = fetch_federal_register(since)
        if not args.no_news:
            items += fetch_news()
        print(f"Fetched {len(items)} items since {since}")
    run(items, dry_run=args.dry_run)
    # Refresh the fallback copy inside index.html.
    if not args.dry_run:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from build_index import build
        build()


if __name__ == "__main__":
    main()
