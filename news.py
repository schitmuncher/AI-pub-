"""Local news feed for The Salt Ship.

Drop plain-text articles into ./news/ as .txt or .md files. The first line is
the headline; the rest is a short summary in your own words. Keep summaries
brief and don't paste full copyrighted articles: the sim only needs the gist.

Each item is read once (tracked in state["news_seen"]). The landlord brain
sees today's items and can react; customers can talk about them.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
NEWS_DIR = os.path.join(HERE, "news")


def load_items():
    if not os.path.isdir(NEWS_DIR):
        return []
    items = []
    for name in sorted(os.listdir(NEWS_DIR)):
        if not name.endswith((".txt", ".md")):
            continue
        with open(os.path.join(NEWS_DIR, name), encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        if not lines:
            continue
        items.append({"id": name, "headline": lines[0].lstrip("# ").strip(),
                      "summary": " ".join(lines[1:])[:400]})
    return items


def unseen_today(state, limit=2):
    """Pick up to `limit` unread items for today's paper."""
    seen = set(state.setdefault("news_seen", []))
    fresh = [i for i in load_items() if i["id"] not in seen]
    picked = fresh[:limit]
    for item in picked:
        seen.add(item["id"])
    state["news_seen"] = sorted(seen)
    return picked
