"""Memory, relationships and opinions for The Salt Ship characters.

Each character keeps a list of memories:
  {"day", "hour", "text", "importance" (1-10), "about": [names], "kind": event|heard|opinion}

Retrieval scores memories by importance, recency (fades per in-game day)
and word overlap with the current topic, so people bring up the right
things at the right time. Relationships (-10 to 10) are changed by what
people witness or hear, and reflect() turns strong feelings into opinions.
"""
import re

DECAY = 0.85          # how fast memories fade per in-game day
MAX_MEMORIES = 60     # per person; the least important old ones get dropped
REL_MIN, REL_MAX = -10, 10
WORD = re.compile(r"[a-z']+")


def _words(text):
    return set(WORD.findall(text.lower())) - {"the", "a", "to", "of", "and", "was", "is", "in", "at", "about"}


def hydrate(p):
    """Convert older string memories into structured ones."""
    p.setdefault("rel", {})
    fixed = []
    for m in p.get("memory", []):
        if isinstance(m, str):
            fixed.append({"day": 0, "hour": 0, "text": m, "importance": 2, "about": [], "kind": "event"})
        else:
            fixed.append(m)
    p["memory"] = fixed
    return p


def _clamp(v):
    return max(REL_MIN, min(REL_MAX, v))


def adjust(p, other, delta):
    p["rel"][other] = _clamp(p["rel"].get(other, 0) + delta)


def add(p, state, text, importance=3, about=(), rel=0, kind="event"):
    mem = {"day": state["day"], "hour": state["hour"], "text": text,
           "importance": importance, "about": list(about), "kind": kind}
    p["memory"].append(mem)
    if len(p["memory"]) > MAX_MEMORIES:
        p["memory"].sort(key=lambda m: _weight(m, state["day"]), reverse=True)
        p["memory"] = p["memory"][:MAX_MEMORIES]
    for name in about:
        adjust(p, name, rel)
    return mem


def _weight(m, today):
    return m["importance"] / 10 + DECAY ** max(0, today - m["day"])


def retrieve(p, day, query="", k=3, about=None):
    """Return the k most relevant memories for the current moment.

    If `about` is given, only memories mentioning that name are considered."""
    q = _words(query)
    scored = []
    for m in p["memory"]:
        if about and about not in m["about"]:
            continue
        overlap = len(q & _words(m["text"]))
        scored.append((_weight(m, day) + 0.5 * overlap, m))
    scored.sort(key=lambda s: s[0], reverse=True)
    return [m for _, m in scored[:k]]


def strongest_about(p, name, day):
    """The most salient memory this person has about someone, or None."""
    mems = retrieve(p, day, k=1, about=name)
    return mems[0] if mems else None


def reflect(p, state):
    """Turn strong relationships into lasting opinions (once a day)."""
    for other, score in p["rel"].items():
        if abs(score) < 4:
            continue
        label = "trust" if score > 0 else "don't trust"
        text = f"Decided I {label} {other} (feeling {score:+d})"
        already = any(m["kind"] == "opinion" and m["text"] == text for m in p["memory"][-10:])
        if not already:
            add(p, state, text, importance=6, about=[other], kind="opinion")


def mood(p):
    """Mood from today's memories and drinks."""
    today = [m for m in p["memory"] if m["day"] == p.get("_today")]
    if any("couldn't afford" in m["text"] or "row" in m["text"] for m in today):
        return "grumpy"
    if p.get("drinks_today", 0) >= 3:
        return "merry"
    return "content"
