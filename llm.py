"""Model access for The Salt Ship: the landlord brain and batched scenes.

Three backends, chosen by environment:
  SALT_LLM=anthropic   real calls to the Anthropic Messages API (needs ANTHROPIC_API_KEY)
  SALT_LLM=mock        canned replies, for testing the pipeline at no cost
  (unset)              no model; the sim uses its rules-based behaviour

Every call goes through a daily call cap (SALT_DAILY_CALLS, default 40),
kept in budget.json. A call that fails or returns unusable JSON falls back
to the rules-based behaviour, so the sim never stops.

Model output is treated as proposals. The rules engine in world.py still
checks every action, and every memory is clamped before it is stored.
"""
import datetime
import json
import os
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BUDGET_FILE = os.path.join(HERE, "budget.json")
MODEL = os.environ.get("SALT_MODEL", "claude-haiku-5-5")
DAILY_CAP = int(os.environ.get("SALT_DAILY_CALLS", "40"))
MAX_SCENE_CHARS = 140
ALLOWED_ACTIONS = {"order", "set_price", "start_project", "pay_repair", "ban", "run_event", "post_notice"}


class LLMError(Exception):
    pass


# ---------- budget ----------

def _load_budget():
    today = datetime.date.today().isoformat()
    try:
        with open(BUDGET_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if data.get("date") != today:
        data = {"date": today, "calls": 0}
    return data


def budget_left():
    return DAILY_CAP - _load_budget()["calls"]


def _spend_one():
    data = _load_budget()
    data["calls"] += 1
    with open(BUDGET_FILE, "w") as f:
        json.dump(data, f)


# ---------- backends ----------

def _anthropic(system, user, max_tokens):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY not set")
    body = json.dumps({
        "model": MODEL, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, ValueError) as e:
        raise LLMError(str(e))
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def _mock(system, user, max_tokens):
    """Deterministic stand-in reply, so the scene pipeline can be exercised for free."""
    if "Reply with JSON only, in this shape:\n{\"actions\"" in system:
        return '{"actions": []}'
    scene = json.loads(user)
    cast = scene["cast"]
    lines = [{"name": c["name"], "says": f"Mock line for {c['name']} about {scene['weather']}."} for c in cast[:2]]
    mems = [{"name": c["name"], "text": "had a mock conversation", "importance": 4,
             "about": [], "rel": 0} for c in cast[:1]]
    return json.dumps({"lines": lines, "memories": mems})


def call(system, user, max_tokens=400):
    """One budgeted call. Raises LLMError if unavailable or over budget."""
    mode = os.environ.get("SALT_LLM", "")
    if mode == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise LLMError("ANTHROPIC_API_KEY not set")
    if mode not in ("mock", "anthropic"):
        raise LLMError(f"no model configured (SALT_LLM={mode or 'unset'})")
    if budget_left() <= 0:
        raise LLMError("daily call cap reached")
    _spend_one()
    if mode == "mock":
        return _mock(system, user, max_tokens)
    return _anthropic(system, user, max_tokens)


def parse_json(text):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("no JSON in reply")
    try:
        return json.loads(text[start:end + 1])
    except ValueError as e:
        raise LLMError(f"bad JSON: {e}")


# ---------- landlord brain ----------

LANDLORD_SYSTEM = """You are the landlord of The Salt Ship, a small pub on Welsh Row in Nantwich, Cheshire.
You run the pub: stock, prices, repairs, projects, bans, events and the notice board.
Reply with JSON only, in this shape:
{"actions": [{"type": "...", ...}]}
ACTIONS you may use (at most 6):
  order {drink, qty}           drink: Cask Bitter, Lager, Premium Lager, Guinness, Cider
  set_price {drink, price}     price between 2.00 and 9.00
  start_project {name}         name: beer_garden
  pay_repair {}
  ban {name, days}             only for customers in the pub, 1-7 days
  run_event {name}             name: quiz
  post_notice {text}           under 200 characters, in the landlord's own voice
Money is limited: the rules engine rejects anything you cannot afford, and will tell you why next time.
Be a sensible, slightly flawed landlord. Do nothing if nothing needs doing."""


def landlord_prompt(state):
    recent_notices = state["notice_board"][-3:]
    return json.dumps({
        "day": state["day"], "hour": state["hour"], "weather": state["weather"],
        "cash": round(state["cash"], 2), "reputation": state["reputation"],
        "stock": state["stock"], "prices": state["prices"],
        "pending_orders": state["pending_orders"],
        "repairs_owed": state["repairs"], "projects": state["projects"],
        "reports_today": state["reports"], "news_today": state.get("news_today", []),
        "headline": state["headline"], "recent_notices": recent_notices,
        "your_recent_problems": state["landlord_memory"][-5:],
        "in_pub_now": [p["name"] for p in state["people"] if p["role"] != "staff"],
    }, ensure_ascii=False)


def clean_actions(raw):
    out = []
    for a in raw.get("actions", [])[:6]:
        if not isinstance(a, dict) or a.get("type") not in ALLOWED_ACTIONS:
            continue
        if a["type"] == "post_notice":
            a["text"] = str(a.get("text", ""))[:200]
        out.append(a)
    return out


# ---------- scenes ----------

SCENE_SYSTEM = """You write what the people in a British pub say and do this hour, in Nantwich, Cheshire.
Voice: natural, British, funny where it fits, not every line is a joke. People talk about what has actually happened (use the events and memories given), and may bring up old grudges or favours.
Each person has private motives. They are never stated aloud unless the character would plausibly let slip.
Reply with JSON only:
{"lines": [{"name": "...", "says": "..."}],
 "memories": [{"name": "...", "text": "...", "importance": 1-10, "about": ["..."], "rel": -2 to 2}]}
Rules: only use the names given. Each line under 140 characters. At most one line per person. Memories are short, first-person-ish phrases. Keep it to what happened."""


def scene_prompt(state, people, hour_events):
    cast = []
    for p in people:
        cast.append({
            "name": p["name"], "role": p["role"], "traits": p["traits"], "drink": p["drink"],
            "mood": p.get("mood", "content"),
            "feelings": {k: v for k, v in p["rel"].items() if abs(v) >= 2},
            "remembers": p.get("recalled", []),
            "private_motive": p.get("secret", ""),
        })
    return json.dumps({
        "time": f"day {state['day']} {state['hour']:02d}:00", "weather": state["weather"],
        "news_today": [n["headline"] for n in state.get("news_today", [])],
        "events_this_hour": hour_events,
        "cast": cast,
    }, ensure_ascii=False)


def clean_scene(raw, names):
    lines = []
    for ln in raw.get("lines", []):
        name, says = ln.get("name"), str(ln.get("says", "")).strip()
        if name in names and says:
            lines.append({"name": name, "says": says[:MAX_SCENE_CHARS]})
    mems = []
    for m in raw.get("memories", []):
        name, text = m.get("name"), str(m.get("text", "")).strip()
        if name not in names or not text:
            continue
        about = [a for a in m.get("about", []) if a in names][:2]
        mems.append({
            "name": name, "text": text[:120],
            "importance": max(1, min(10, int(m.get("importance", 3)))),
            "about": about,
            "rel": max(-2, min(2, int(m.get("rel", 0)))),
        })
    return {"lines": lines, "memories": mems}


def run_scene(state, people, hour_events):
    """Batched scene for everyone present. Returns cleaned output or raises LLMError."""
    names = {p["name"] for p in people}
    text = call(SCENE_SYSTEM, scene_prompt(state, people, hour_events), max_tokens=700)
    return clean_scene(parse_json(text), names)


def run_landlord(state):
    text = call(LANDLORD_SYSTEM, landlord_prompt(state), max_tokens=350)
    return clean_actions(parse_json(text))


class LLMBrain:
    """Drop-in for world.TemplateBrain. Falls back to rules on any failure."""

    def __init__(self, fallback):
        self.fallback = fallback
        self.failures = 0

    def decide(self, state):
        try:
            return run_landlord(state)
        except LLMError as e:
            self.failures += 1
            state["landlord_memory"] = (state["landlord_memory"] + [f"model unavailable: {e}"])[-20:]
            return self.fallback.decide(state)
