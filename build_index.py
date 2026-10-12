"""Build index.html from src/app.html.

Wraps the app in a full HTML page for GitHub Pages and embeds a copy of
data/rules.json as a fallback, so the page still works when opened
straight from disk. Run after editing src/app.html or data/rules.json:

    python scanner/build_index.py
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEAD_OPEN = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="Maps the AI GPU supply chain, tracks rules that affect it, and estimates their cost impact.">
"""
TAIL = "\n</body>\n</html>\n"
SPLIT = '<div class="wrap">'


def build(wrap=True, out_name="index.html"):
    with open(os.path.join(ROOT, "src", "app.html"), encoding="utf-8") as f:
        app = f.read()
    with open(os.path.join(ROOT, "data", "rules.json"), encoding="utf-8") as f:
        data = json.load(f)
    seed = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    app = app.replace("/*SEED*/null", seed, 1)
    if wrap:
        # Move title, font link and styles into <head>; the rest goes in <body>.
        head_part, body_part = app.split(SPLIT, 1)
        page = HEAD_OPEN + head_part + "</head>\n<body>\n" + SPLIT + body_part + TAIL
    else:
        page = app
    with open(os.path.join(ROOT, out_name), "w", encoding="utf-8") as f:
        f.write(page)
    return out_name


if __name__ == "__main__":
    print("Wrote", build())
