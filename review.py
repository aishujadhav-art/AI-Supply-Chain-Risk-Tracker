"""Approve or reject items the scanner added for review.

Usage:
    python scanner/review.py --ids NEWS-3f9a1c2b7d10 --decision approve
    python scanner/review.py --ids "NEWS-aaa, FR-2026-123" --decision reject

Approve: sets "review" to "approved", so the item shows on the map and can
feed the cost model.
Reject: removes the item and adds its id to "dismissed", so the scanner does
not pick it up again.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, "data", "rules.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="One id, or several separated by commas")
    ap.add_argument("--decision", choices=["approve", "reject"])
    ap.add_argument("--from-title", help='Request title from the dashboard, e.g. "approve NEWS-3f9a1c2b7d10"')
    args = ap.parse_args()
    if args.from_title:
        m = re.match(r"^\s*(approve|reject)\s+([A-Za-z0-9_.,\- ]+?)\s*$", args.from_title, re.I)
        if not m:
            print('Title must look like "approve ITEM-ID" or "reject ITEM-ID".')
            sys.exit(1)
        args.decision, args.ids = m.group(1).lower(), m.group(2)
    if not args.ids or not args.decision:
        ap.error("give --ids and --decision, or --from-title")
    ids = [i.strip().strip('"').strip("'") for i in args.ids.split(",") if i.strip()]

    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    by_id = {r["id"]: r for r in data["rules"]}
    missing = [i for i in ids if i not in by_id]
    if missing:
        print("These ids were not found: " + ", ".join(missing))
        print("Copy the id exactly as shown on the dashboard's Rule tracker tab.")
        sys.exit(1)

    today = dt.date.today().isoformat()
    if args.decision == "approve":
        for i in ids:
            by_id[i]["review"] = "approved"
            by_id[i]["reviewed_on"] = today
            print(f"Approved: {by_id[i]['title']}")
    else:
        data["rules"] = [r for r in data["rules"] if r["id"] not in ids]
        dismissed = data.setdefault("dismissed", [])
        for i in ids:
            if i not in dismissed:
                dismissed.append(i)
            print(f"Rejected: {by_id[i]['title']}")

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from build_index import build
    build()


if __name__ == "__main__":
    main()
