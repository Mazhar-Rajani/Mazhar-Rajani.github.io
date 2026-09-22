"""Tag the project tiles in index.html with filter categories using TypeSafe's Jev model.

Each tile's title, description and contribution bullets go to Jev as state, with one
yes/no (Noul) question per category. Tiles whose probability clears THRESHOLD get that
category written into a `data-tags` attribute, which assets/js/project-filter.js reads.

Results are cached in assets/data/project-tags.json keyed by a hash of the tile's text,
so re-running only queries tiles that were added or edited; editing a question in
QUESTIONS re-asks every tile. The API key stays local: the published site only ever
sees the finished data-tags.

Usage:
    python tools/tag_projects.py            # tag new/changed tiles
    python tools/tag_projects.py --force    # re-ask Jev about every tile
    python tools/tag_projects.py --dry-run  # show results without writing files

Needs TYPESAFE_API_KEY in the environment.
"""

import argparse
import hashlib
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
CACHE = ROOT / "assets" / "data" / "project-tags.json"
API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
THRESHOLD = 0.55

# Filter id -> Noul. The filter bar in index.html uses the same ids.
QUESTIONS = {
    "game": {
        "instructions": "Is the project described in `description` and `contributions` a game made for players to play for entertainment?",
        "criteria": {
            "true": "An entertainment game or game prototype, including casual, kids, puzzle, sports and multiplayer games.",
            "false": "A training simulation, enterprise or educational app, visualization, tool, plugin, shader study or 3D art.",
        },
    },
    "vr": {
        "instructions": "Is the project described in `description` and `contributions` a virtual reality (VR) application?",
    },
    "ar": {
        "instructions": "Is the project described in `description` and `contributions` an augmented reality (AR) application?",
    },
    "training": {
        "instructions": "Is the project described in `description` and `contributions` a training, simulation, educational or enterprise application?",
        "criteria": {
            "true": "Built to teach, train, simulate real equipment or procedures, or visualize real-world data for a business or learners.",
            "false": "Built mainly for entertainment, or a developer tool, shader study or art piece.",
        },
    },
    "tool": {
        "instructions": "Is the project described in `description` and `contributions` a developer tool, editor extension, plugin or reusable system for other developers?",
    },
    "graphics": {
        "instructions": "Is the project described in `description` and `contributions` primarily about graphics: shaders, rendering, visual effects, procedural visuals or 3D modeling?",
        "criteria": {
            "true": "The visuals themselves are the main point of the project.",
            "false": "Graphics work is incidental; the project is mainly about gameplay, training, tooling or other functionality.",
        },
    },
}

TILE_RE = re.compile(
    r"<!-- Project Tile template \((?P<name>[^)]*)\)\s*-->\s*"
    r"<article class=\"project\"(?P<attrs>[^>]*)>"
    r"(?P<body>.*?)<!-- Project Tile template End-->",
    re.S,
)


def text_of(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_tiles(source):
    tiles = []
    for m in TILE_RE.finditer(source):
        body = m.group("body")
        title = re.search(r'<h3 class="project-title">(.*?)</h3>', body, re.S)
        section = re.search(r'data-section="([^"]*)"', m.group("attrs"))
        desc = re.search(r'<p class="project-desc">(.*?)</p>', body, re.S)
        link = re.search(r'<a [^>]*?href="([^"]*)"', body)
        state = {
            "title": text_of(title.group(1)) if title else m.group("name"),
            "section": section.group(1) if section else "",
            "description": text_of(desc.group(1)) if desc else "",
            "contributions": [text_of(c) for c in re.findall(r'<li class="contrib-item">(.*?)</li>', body, re.S)],
            "link": link.group(1) if link else "",
        }
        digest = hashlib.sha256(json.dumps([MODEL, QUESTIONS, state], sort_keys=True).encode()).hexdigest()[:16]
        tiles.append({"key": m.group("name"), "state": state, "hash": digest})
    return tiles


def ask_jev(state, api_key):
    payload = {
        "state": state,
        "model": MODEL,
        "questions": {qid: {"type": "noul", **q} for qid, q in QUESTIONS.items()},
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{state['title']}: HTTP {e.code} {e.read().decode(errors='replace')[:300]}") from e
    return result["model"], {qid: round(a["noul"], 3) for qid, a in result["answers"].items()}


def apply_tags(source, tags_by_key):
    def replace(m):
        tags = tags_by_key.get(m.group("name"))
        if tags is None:
            return m.group(0)
        attrs = re.sub(r'\s*data-tags="[^"]*"', "", m.group("attrs")) + f' data-tags="{" ".join(tags)}"'
        return m.string[m.start() : m.start("attrs")] + attrs + m.string[m.end("attrs") : m.end()]

    return TILE_RE.sub(replace, source)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="re-ask Jev about every tile")
    parser.add_argument("--dry-run", action="store_true", help="print results without writing files")
    args = parser.parse_args()

    with INDEX.open(encoding="utf-8", newline="") as f:
        source = f.read()
    tiles = parse_tiles(source)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    stale = [t for t in tiles if args.force or cache.get(t["key"], {}).get("hash") != t["hash"]]

    if stale:
        api_key = os.environ.get("TYPESAFE_API_KEY")
        if not api_key:
            sys.exit("TYPESAFE_API_KEY is not set.")
        print(f"Asking Jev about {len(stale)} of {len(tiles)} tiles...")
        with ThreadPoolExecutor(max_workers=6) as pool:
            for tile, (model, probs) in zip(stale, pool.map(lambda t: ask_jev(t["state"], api_key), stale)):
                cache[tile["key"]] = {"hash": tile["hash"], "model": model, "probabilities": probs}
    else:
        print(f"All {len(tiles)} tiles are up to date.")

    # Drop entries for tiles that no longer exist.
    cache = {t["key"]: cache[t["key"]] for t in tiles}
    tags_by_key = {}
    for t in tiles:
        probs = cache[t["key"]]["probabilities"]
        tags_by_key[t["key"]] = [qid for qid in QUESTIONS if probs.get(qid, 0) >= THRESHOLD]
        cache[t["key"]]["tags"] = tags_by_key[t["key"]]

    width = max(len(t["key"]) for t in tiles)
    for t in tiles:
        probs = cache[t["key"]]["probabilities"]
        detail = "  ".join(f"{qid}={probs[qid]:.2f}" for qid in QUESTIONS)
        print(f"{t['key']:<{width}}  {' '.join(tags_by_key[t['key']]) or '(none)':<28} {detail}")

    if args.dry_run:
        return
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")
    with INDEX.open("w", encoding="utf-8", newline="") as f:
        f.write(apply_tags(source, tags_by_key))
    print(f"Wrote {CACHE.relative_to(ROOT)} and data-tags in {INDEX.relative_to(ROOT)}.")


if __name__ == "__main__":
    main()
