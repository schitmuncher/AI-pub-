#!/usr/bin/env python3
"""The Salt Ship: a text-based pub simulation run by an AI landlord.

Layers:
  World state  - cash, stock, prices, fixtures, people, notice board (state.json)
  Rules        - what is physically and financially possible (apply_action)
  Brain        - decides the landlord's moves. TemplateBrain is a stand-in;
                 an LLM brain only needs a decide(state) method that returns
                 a list of action dicts.
  Scenes       - people in the pub act and talk, using their own memories
  Write-up     - landlord log, customer diaries and a paper, one file per day
                 in ./days/

Usage: python3 world.py [days] [--seed N] [--reset]
"""
import json
import os
import random
import sys

from news import unseen_today
import memory as mem
import llm

USE_SCENES = False  # set in main() when a model is configured
SCENE_CAST_LIMIT = 6

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")
DAY_DIR = os.path.join(HERE, "days")

OPEN_HOURS = list(range(12, 24))
DECISION_HOURS = {12, 17, 22}  # landlord thinks at opening, early evening and last orders

# name: (price, cost per pint)
DRINKS = {
    "Cask Bitter":   (4.60, 1.60),
    "Lager":         (5.00, 1.40),
    "Premium Lager": (5.80, 1.90),
    "Guinness":      (5.50, 1.85),
    "Cider":         (5.20, 1.70),
}
WEATHER = ["clear", "cloudy", "rain", "heavy rain", "storm"]
PROJECTS = {"beer_garden": {"label": "a beer garden", "cost": 300, "days": 2}}

INCIDENTS = [
    ("fridge_fault", "The keg fridge has started making a noise like a dying walrus."),
    ("dog_in_pub", "A large wet dog has walked in and sat on someone's foot."),
    ("football_on", "Someone has put the football on and the snug has gone quiet."),
    ("stranger_room", "A soaked stranger asks whether there is a room upstairs for the night."),
    ("till_short", "The till is £12 short from last night and nobody wants to say so."),
    ("cellar_leak", "Water is coming through the cellar wall after the rain."),
]
TOPIC = {
    "fridge_fault": "the fridge", "dog_in_pub": "that dog", "football_on": "the football",
    "stranger_room": "that soaked stranger", "till_short": "the till", "cellar_leak": "the cellar leak",
}
STRANGER_POOL = [
    {"name": "Pete", "traits": ["sad", "chatty"], "drink": "Cider"},
    {"name": "Sophie", "traits": ["funny", "nosy"], "drink": "Premium Lager"},
    {"name": "Col", "traits": ["loud", "generous"], "drink": "Guinness"},
    {"name": "Denise", "traits": ["honest", "chatty"], "drink": "Cask Bitter"},
    {"name": "Tariq", "traits": ["nosy", "funny"], "drink": "Lager"},
    {"name": "Gran Val", "traits": ["gossipy", "sharp"], "drink": "Cider"},
]
NEG_LINES = [
    "I don't trust {n}. Don't forget: {gist}.",
    "Don't sit near {n}, love. {gist}, you know.",
    "{n} can get lost. {gist}, remember?",
]
POS_LINES = [
    "{n}'s all right, is {n}. Get them in.",
    "Ask {n}, they'll know. They're sound.",
]
TRAIT_LINES = {
    "gossipy": ["Did you hear about {topic}? I'm not saying who told me.", "Right, {topic}. Don't repeat that."],
    "kind": ["You look shattered, love. Sit down.", "Put that on my tab, I'm feeling generous."],
    "grumbly": ["{weather} again. I've had enough of it.", "This pint's flat. Take it back, Jade."],
    "honest": ["I'll be straight with you, I'm not sure what to make of {topic}.",
               "The bitter's better than it was. Don't tell anyone I said so."],
    "loud": ["Who's buying? Only joking. Well, maybe.", "Right, my shout, and I'll not hear otherwise!"],
    "generous": ["Round's on me, whatever you're having.", "I've had a good week, get the lads one."],
    "nerdy": ["I've worked out the quiz odds. They're bad.",
              "Did you know the dartboard numbers were ordered to stop neighbours adding up? I think."],
    "darts-mad": ["Who fancies a game after this?", "Treble twenty, that's the only number I need."],
    "sharp": ["Last orders in ten, lads. Don't make me say it twice.", "Pay for that, I'm not your mum."],
    "funny": ["{topic}. Brilliant. The weather clearly needed help.",
              "Staying for one more, are we? Fine, I'll put the kettle on."],
    "sad": ["Bus never came. Again.", "Nobody's expecting me home, so I'll stop here."],
    "chatty": ["I've had the strangest day, I'll tell you all about it.",
               "Have you been here before? It's a lovely old place."],
    "nosy": ["Who's the lad by the till? He's been looking at it all night.",
             "What's going on with {topic}? Go on, tell me."],
    "short-tempered": ["Don't start, I've had a day.", "Move your bag or I'll move it for you."],
}
KEYWORDS = ["row", "tab", "till", "Keith", "Mick", "notice", "fridge", "quiz", "delivery",
            "garden", "banned", "Pete", "Sophie", "Col", "Jade", "heard", "told", "cellar", "walrus"]

EVENTS = []  # (day, hour, text) for the day being played


# ---------- setup ----------

def hydrate(p):
    p.setdefault("memory", [])
    p.setdefault("today", [])
    p.setdefault("tab", 0.0)
    p.setdefault("spent", 0.0)
    p.setdefault("banned_until", 0)
    p.setdefault("drinks_today", 0)
    p.setdefault("base_budget", p["budget"])
    return mem.hydrate(p)


def fresh_people():
    return [
        {"name": "Brenda", "role": "regular", "traits": ["gossipy", "kind"], "drink": "Cask Bitter",
         "budget": 40, "secret": "pays off a loan to her sister", "good": True},
        {"name": "Ray", "role": "regular", "traits": ["grumbly", "honest"], "drink": "Lager",
         "budget": 25, "secret": "is skint until Friday and runs a tab", "good": True},
        {"name": "Keith", "role": "regular", "traits": ["loud", "generous"], "drink": "Guinness",
         "budget": 60, "secret": "takes money from the till", "good": False},
        {"name": "Dev", "role": "regular", "traits": ["nerdy", "darts-mad"], "drink": "Premium Lager",
         "budget": 35, "secret": "plans to propose in the beer garden", "good": True},
        {"name": "Mick", "role": "regular", "traits": ["loud", "short-tempered"], "drink": "Lager",
         "budget": 30, "secret": "starts rows on his fourth pint", "good": False},
        {"name": "Jade", "role": "staff", "traits": ["sharp", "funny"], "drink": "Cider",
         "budget": 0, "secret": "wants a better job", "good": True},
    ]


def new_state():
    people = [hydrate(p) for p in fresh_people()]
    return {
        "pub": "The Salt Ship",
        "location": "Welsh Row, Nantwich (fictional)",
        "day": 1, "hour": 12, "cash": 400.0, "reputation": 50, "weather": "clear",
        "stock": {"Cask Bitter": 24, "Lager": 36, "Premium Lager": 12, "Guinness": 18, "Cider": 18},
        "prices": {k: v[0] for k, v in DRINKS.items()},
        "fixtures": ["bar", "snug", "dartboard"],
        "projects": [], "pending_orders": [], "repairs": [], "reports": [],
        "notice_board": [], "landlord_memory": [], "quiz_day": 0,
        "headline": None, "topic": None,
        "takings": 0.0, "served": 0, "actions_today": [],
        "people": people,
    }


# ---------- helpers ----------

def say(state, text):
    EVENTS.append((state["day"], state["hour"], text))


def remember(p, state, text, importance=3, about=(), rel=0, kind="event"):
    """Give a person a memory of something. `about` names people it concerns;
    `rel` shifts how this person feels about each of them."""
    mem.add(p, state, text, importance=importance, about=about, rel=rel, kind=kind)
    p["today"].append(text)


def find_person(state, name):
    return next((p for p in state["people"] if p["name"] == name), None)


# ---------- world dynamics ----------

def step_weather(state, rng):
    i = WEATHER.index(state["weather"])
    i = min(max(i + rng.choice([-1, 0, 0, 1]), 0), len(WEATHER) - 1)
    state["weather"] = WEATHER[i]


def deliveries(state, rng):
    for o in state["pending_orders"]:
        if o["arrive_day"] <= state["day"] and state["weather"] == "storm" and rng.random() < 0.4:
            o["arrive_day"] += 1
            say(state, f"The {o['drink']} delivery is held up by the storm.")
    arrived = [o for o in state["pending_orders"] if o["arrive_day"] <= state["day"]]
    for o in arrived:
        state["stock"][o["drink"]] += o["qty"]
        say(state, f"Delivery in: {o['qty']} x {o['drink']}.")
    state["pending_orders"] = [o for o in state["pending_orders"] if o["arrive_day"] > state["day"]]


def incident(state, rng):
    key, text = rng.choice(INCIDENTS)
    state["headline"] = text
    state["topic"] = TOPIC[key]
    say(state, text)
    if key == "fridge_fault":
        lost = min(state["stock"]["Lager"], rng.randint(2, 5))
        state["stock"]["Lager"] -= lost
        say(state, f"{lost} pints of lager have gone warm and been poured away.")
    elif key == "till_short":
        state["cash"] -= 12
    elif key == "cellar_leak" and not any(r["item"] == "cellar wall" for r in state["repairs"]):
        state["repairs"].append({"item": "cellar wall", "cost": 80})


def add_stranger(state, rng):
    taken = {p["name"] for p in state["people"]}
    free = [s for s in STRANGER_POOL if s["name"] not in taken]
    if not free:
        return None
    proto = rng.choice(free)
    p = hydrate({**proto, "role": "stranger", "budget": 20, "good": True, "secret": "",
                 "memory": [], "rel": {}})
    state["people"].append(p)
    return p


def is_present(state, p, rng):
    if p["role"] == "staff":
        return True
    if state["day"] <= p["banned_until"]:
        return False
    if p["role"] == "stranger":
        return True
    base = 0.5
    if state["hour"] < 14:
        base -= 0.15
    if state["weather"] in ("rain", "heavy rain", "storm"):
        base += 0.1
    if state["quiz_day"] == state["day"] and state["hour"] >= 19:
        base += 0.2
    return rng.random() < max(0.0, min(1.0, base))


def serve(state, p):
    drink = p["drink"]
    if state["stock"].get(drink, 0) <= 0:
        drink = next((d for d, n in state["stock"].items() if n > 0), None)
        if drink is None:
            say(state, f"{p['name']} asks what's on and is told nothing is.")
            return
        say(state, f"{p['name']} switches to {drink} as the {p['drink']} is off.")
    price = state["prices"][drink]
    if p["tab"] > 0 and p["budget"] >= price + p["tab"]:
        paid = round(p["tab"], 2)
        p["budget"] -= paid
        state["cash"] += paid
        state["takings"] += paid
        p["tab"] = 0.0
        say(state, f"{p['name']} settles up their tab (£{paid:.2f}).")
        remember(p, state, "settled up my tab", importance=3)
        for person in state["people"]:
            if person["role"] == "staff" and person is not p:
                remember(person, state, f"{p['name']} paid off their tab", importance=3, about=[p["name"]], rel=1)
    if p["budget"] >= price:
        p["budget"] -= price
    elif state["reputation"] >= 40 and p["role"] != "staff":
        p["tab"] += price
        say(state, f"{p['name']} runs a tab for a {drink}, again.")
    else:
        say(state, f"{p['name']} can't afford a {drink} and leaves a bit grumpy.")
        remember(p, state, "couldn't afford a drink", importance=2)
        return
    state["stock"][drink] -= 1
    state["cash"] += price
    state["takings"] += price
    state["served"] += 1
    p["drinks_today"] += 1
    p["spent"] += price


def speak(state, p, rng, present=()):
    """A line of talk. Sometimes it's about someone in the room, drawn from
    what this person remembers and how they feel about them."""
    day = state["day"]
    others = [q for q in present if q is not p and q["name"] in p["rel"]]
    if others and rng.random() < 0.4:
        target = rng.choice(others)
        score = p["rel"][target["name"]]
        m = mem.strongest_about(p, target["name"], day)
        gist = m["text"] if m else "the way they carry on"
        if score <= -3:
            line = rng.choice(NEG_LINES).format(n=target["name"], gist=gist)
            topic = target["name"]
            say(state, f'{p["name"]} to the bar about {target["name"]}: "{line}"')
            remember(p, state, f"had a go at {target['name']} about {gist}", importance=4,
                     about=[target["name"]], rel=-1)
            return
        if score >= 3:
            line = rng.choice(POS_LINES).format(n=target["name"])
            say(state, f'{p["name"]}: "{line}"')
            remember(p, state, f"stuck up for {target['name']}", importance=3,
                     about=[target["name"]], rel=1)
            return
    trait = rng.choice(p["traits"]) if p["traits"] else "chatty"
    template = rng.choice(TRAIT_LINES.get(trait, TRAIT_LINES["chatty"]))
    topic = state.get("topic") or "the football"
    line = template.format(topic=topic, weather=state["weather"])
    say(state, f'{p["name"]}: "{line}"')
    remember(p, state, f"talked about {topic}", importance=1)


def gossip(state, present, rng):
    """One person passes on something they remember about someone else.
    The listener's feelings shift towards that person in the same direction
    as the teller's, so rumours can spread a reputation around the room."""
    if len(present) < 2 or rng.random() > 0.5:
        return
    day = state["day"]
    tellers = [p for p in present if any(m["about"] and m["kind"] != "opinion" for m in p["memory"])]
    if not tellers:
        return
    teller = rng.choice(tellers)
    listener = rng.choice([p for p in present if p is not teller])
    shareable = [m for m in teller["memory"] if m["about"] and m["kind"] != "opinion"
                 and m["importance"] >= 3]
    if not shareable:
        return
    item = max(shareable, key=lambda m: mem._weight(m, day) * (1 + rng.random()))
    subject = item["about"][0]
    if subject == listener["name"]:
        return  # nobody tells people about themselves
    say(state, f"{teller['name']} tells {listener['name']} about {subject}: {item['text']}")
    feeling = teller["rel"].get(subject, 0)
    shift = 1 if feeling >= 3 else -1 if feeling <= -3 else 0
    remember(listener, state, f"heard about {subject} from {teller['name']}: {item['text']}",
             importance=max(2, item["importance"] - 2), about=[subject], rel=shift, kind="heard")


def secret_moves(state, present, rng):
    names = {p["name"]: p for p in present}
    if "Keith" in names and state["cash"] > 20 and rng.random() < 0.2:
        state["cash"] -= 15
        say(state, "The till comes up £15 light, and Keith is suddenly very interested in his pint.")
        if "Jade" in names and rng.random() < 0.5:
            state["reports"].append("Jade saw Keith near the till.")
            remember(names["Jade"], state, "Keith was hanging about by the till when it came up short",
                     importance=8, about=["Keith"], rel=-3)
    if "Mick" in names and names["Mick"]["drinks_today"] >= 4 and rng.random() < 0.3:
        state["reputation"] = max(0, state["reputation"] - 4)
        say(state, "Mick squares up to a stranger over a spilled pint, and the whole bar goes quiet.")
        for other in present:
            if other is not names["Mick"]:
                remember(other, state, "Mick started a row in here", importance=6,
                         about=["Mick"], rel=-2)
        state["reports"].append("Mick started a row in the bar.")


def progress_projects(state, rng):
    for pr in list(state["projects"]):
        if rng.random() < 0.3:
            pr["days_left"] += 1  # contractor late
            say(state, f"The builders on {PROJECTS[pr['name']]['label']} are running late.")
        pr["days_left"] -= 1
        if pr["days_left"] <= 0:
            state["fixtures"].append(pr["name"])
            state["projects"].remove(pr)
            say(state, f"{PROJECTS[pr['name']]['label'].capitalize()} is finished.")


# ---------- the rules engine ----------

def apply_action(state, act):
    t = act.get("type")
    if t == "order":
        drink, qty = act["drink"], int(act["qty"])
        if drink not in DRINKS or qty <= 0:
            return False, f"bad order: {drink} x{qty}"
        cost = round(DRINKS[drink][1] * qty, 2)
        if cost > state["cash"]:
            return False, f"can't afford {qty} x {drink} (£{cost:.2f})"
        state["cash"] -= cost
        state["pending_orders"].append({"drink": drink, "qty": qty, "arrive_day": state["day"] + 1})
        return True, f"ordered {qty} x {drink} for £{cost:.2f}"
    if t == "set_price":
        drink, price = act["drink"], float(act["price"])
        if drink not in DRINKS:
            return False, "no such drink"
        if not 2.0 <= price <= 9.0:
            return False, "price outside a sensible range"
        state["prices"][drink] = round(price, 2)
        return True, f"{drink} now £{price:.2f}"
    if t == "start_project":
        key = act["name"]
        spec = PROJECTS.get(key)
        if not spec:
            return False, "unknown project"
        if key in state["fixtures"] or any(p["name"] == key for p in state["projects"]):
            return False, "already built or underway"
        if spec["cost"] > state["cash"]:
            return False, f"can't afford {spec['label']} (£{spec['cost']})"
        state["cash"] -= spec["cost"]
        state["projects"].append({"name": key, "days_left": spec["days"]})
        return True, f"started {spec['label']}, £{spec['cost']} paid up front"
    if t == "pay_repair":
        if not state["repairs"]:
            return False, "nothing to repair"
        r = state["repairs"][0]
        if r["cost"] > state["cash"]:
            return False, f"can't afford the {r['item']} repair (£{r['cost']})"
        state["cash"] -= r["cost"]
        state["repairs"].pop(0)
        return True, f"paid for the {r['item']} repair"
    if t == "ban":
        p = find_person(state, act["name"])
        if not p:
            return False, "no such customer"
        if p["role"] == "staff":
            return False, "can't ban staff"
        days = int(act.get("days", 1))
        p["banned_until"] = state["day"] + days
        remember(p, state, f"was banned for {days} day(s)", importance=7)
        for other in state["people"]:
            if other is not p and other["role"] != "stranger":
                remember(other, state, f"{p['name']} got barred, remember", importance=4,
                         about=[p["name"]], rel=-1)
        return True, f"banned {p['name']} for {days} day(s)"
    if t == "run_event":
        state["quiz_day"] = state["day"]
        return True, "quiz night tonight"
    if t == "post_notice":
        text = act["text"][:200]
        state["notice_board"].append(f"Day {state['day']}: {text}")
        say(state, f"Notice board: {text}")
        return True, "notice posted"
    return False, f"unknown action {t}"


# ---------- the brain ----------

class TemplateBrain:
    """Rule-of-thumb stand-in. Swap for an LLM brain with the same decide()."""

    def decide(self, state):
        acts = []
        for drink, qty in state["stock"].items():
            pending = any(o["drink"] == drink for o in state["pending_orders"])
            if qty < 6 and not pending:
                acts.append({"type": "order", "drink": drink, "qty": 12})
        for r in state["reports"]:
            for name in ("Keith", "Mick"):
                p = find_person(state, name)
                if name in r and p and state["day"] > p["banned_until"]:
                    acts.append({"type": "ban", "name": name, "days": 2})
        if state["repairs"]:
            acts.append({"type": "pay_repair"})
        if state["cash"] > 350 and "beer_garden" not in state["fixtures"] and not state["projects"]:
            acts.append({"type": "start_project", "name": "beer_garden"})
        if state["day"] % 7 == 4 and state["quiz_day"] != state["day"] and state["hour"] == 17:
            acts.append({"type": "run_event", "name": "quiz"})
        if state["hour"] == 22 and state["headline"]:
            acts.append({"type": "post_notice", "text": f"Pinned up: {state['headline']}"})
        return acts


def landlord_turn(state, brain):
    for act in brain.decide(state):
        ok, msg = apply_action(state, act)
        state["actions_today"].append(("OK: " if ok else "FAILED: ") + msg)
        if not ok:
            state["landlord_memory"] = (state["landlord_memory"] + [f"day {state['day']}: {msg}"])[-20:]


# ---------- the hour and the day ----------

def run_scene_hour(state, present):
    """One batched model call for the room. Returns False if it could not run,
    so the caller can fall back to the rules-based talk."""
    people = present[:SCENE_CAST_LIMIT]
    topic = state.get("topic") or "the football"
    for p in people:
        p["mood"] = mood_of(p)
        p["recalled"] = [m["text"] for m in mem.retrieve(p, state["day"], query=topic, k=3)]
    hour_events = [t for d, h, t in EVENTS if d == state["day"] and h == state["hour"]][-8:]
    try:
        out = llm.run_scene(state, people, hour_events)
    except llm.LLMError as e:
        state["landlord_memory"] = (state["landlord_memory"] + [f"scene skipped: {e}"])[-20:]
        return False
    if not out["lines"]:
        return False
    by_name = {p["name"]: p for p in people}
    for ln in out["lines"]:
        say(state, f'{ln["name"]}: "{ln["says"]}"')
        remember(by_name[ln["name"]], state, f"said something about {topic}", importance=1)
    for m in out["memories"]:
        remember(by_name[m["name"]], state, m["text"], importance=m["importance"],
                 about=m["about"], rel=m["rel"])
    return True


def run_hour(state, rng, hour, brain):
    state["hour"] = hour
    if hour == 12:
        deliveries(state, rng)
        state["news_today"] = unseen_today(state)
        for item in state["news_today"]:
            say(state, f"Paper: {item['headline']}")
            if state["headline"] is None:
                state["headline"] = item["headline"]
                state["topic"] = "the news"
    if hour % 2 == 0:
        step_weather(state, rng)
    if rng.random() < 0.15:
        incident(state, rng)
    if rng.random() < 0.2:
        add_stranger(state, rng)
    if state["quiz_day"] == state["day"] and hour == 19:
        say(state, "Quiz night has started and teams are fighting over the pencils.")

    present = [p for p in state["people"] if is_present(state, p, rng)]
    for p in present:
        if p["role"] != "staff" and rng.random() < 0.9:
            serve(state, p)
    spoke = USE_SCENES and len(present) >= 2 and run_scene_hour(state, present)
    if not spoke:
        for p in present:
            speak(state, p, rng, present)
    gossip(state, present, rng)
    secret_moves(state, present, rng)
    if hour in DECISION_HOURS:
        landlord_turn(state, brain)


def mood_of(p):
    if any("couldn't afford" in t or "row" in t for t in p["today"]):
        return "grumpy"
    if p["drinks_today"] >= 3:
        return "merry"
    return "content"


def write_up(state):
    day = state["day"]
    evs = [e for e in EVENTS if e[0] == day]
    busy = "Busy one." if state["served"] >= 25 else "Quiet one."
    out = [f"# {state['pub']}: day {day}", "",
           f"{state['location']}. Weather: {state['weather']}.", "",
           "## The landlord's log", "",
           f"{busy} Took £{state['takings']:.2f} from {state['served']} drinks. "
           f"Cash at close £{state['cash']:.2f}, reputation {state['reputation']}.", ""]
    if state["actions_today"]:
        out += [f"- {a}" for a in state["actions_today"]] + [""]
    if state["repairs"]:
        out += [f"Still owed: {state['repairs'][0]['item']} repair, £{state['repairs'][0]['cost']}.", ""]
    out += ["## Notice board", ""]
    notices = [n for n in state["notice_board"] if n.startswith(f"Day {day}:")]
    out += [f"- {n}" for n in notices] or ["Nothing pinned up today."]
    out += ["", "## Customers' diaries", ""]
    came = [p for p in state["people"] if p["role"] != "staff" and (p["today"] or p["drinks_today"])]
    for p in came:
        noticed = "; ".join(dict.fromkeys(p["today"][-3:])) or "nothing much"
        line = (f"**{p['name']}** ({p['role']}): had {p['drinks_today']} drink(s), spent £{p['spent']:.2f}. "
                f"Feeling {mood_of(p)}. Noticed: {noticed}.")
        recalled = list(dict.fromkeys(m["text"] for m in mem.retrieve(p, day, k=2) if m["day"] < day))
        if recalled:
            line += f" Still thinking about: {'; '.join(recalled)}."
        opinions = [m["text"] for m in p["memory"] if m["kind"] == "opinion" and m["day"] == day]
        if opinions:
            line += f" Opinions: {'; '.join(opinions)}"
        out.append(line)
    if not came:
        out.append("Nobody came in.")
    out += ["", "## The paper", ""]
    picks = [(h, t) for d, h, t in evs if any(k.lower() in t.lower() for k in KEYWORDS)][:8]
    out += [f"- {h:02d}:00 {t}" for h, t in picks] or ["A quiet day, nothing worth printing."]
    out += ["", "## Full scene log", ""]
    out += [f"{h:02d}:00 {t}" for d, h, t in evs]
    os.makedirs(DAY_DIR, exist_ok=True)
    path = os.path.join(DAY_DIR, f"day_{day:03d}.md")
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")
    return path


def end_of_day(state, rng):
    if state["repairs"]:
        state["reputation"] = max(0, state["reputation"] - 2)
    path = write_up(state)
    progress_projects(state, rng)
    for p in state["people"]:
        if p["role"] != "stranger":
            mem.reflect(p, state)
    state["people"] = [p for p in state["people"] if p["role"] != "stranger"]
    for p in state["people"]:
        p["today"] = []
        p["drinks_today"] = 0
        p["budget"] = p["base_budget"]
    state["takings"] = 0.0
    state["served"] = 0
    state["actions_today"] = []
    state["reports"] = []
    state["headline"] = None
    state["topic"] = None
    state["day"] += 1
    state["hour"] = 12
    return path


def main():
    args = sys.argv[1:]
    reset = "--reset" in args
    seed = None
    days = 1
    if "--seed" in args:
        seed = int(args[args.index("--seed") + 1])
    skip = {args.index("--seed") + 1} if "--seed" in args else set()
    numbers = [a for i, a in enumerate(args) if a.isdigit() and i not in skip]
    if numbers:
        days = int(numbers[0])
    if seed is None:
        seed = random.randrange(10**6)

    if not reset and os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            state = json.load(f)
        state["people"] = [hydrate(p) for p in state["people"]]
    else:
        state = new_state()

    global USE_SCENES
    model_on = bool(os.environ.get("SALT_LLM"))
    USE_SCENES = model_on
    brain = llm.LLMBrain(TemplateBrain()) if model_on else TemplateBrain()
    print(f"Mode: {'model (' + os.environ['SALT_LLM'] + ')' if model_on else 'rules only'}; "
          f"model calls left today: {llm.budget_left() if model_on else 'n/a'}")
    last_path = None
    for _ in range(days):
        EVENTS.clear()
        rng = random.Random(seed + state["day"])
        for h in OPEN_HOURS:
            run_hour(state, rng, h, brain)
        last_path = end_of_day(state, rng)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    print(f"Played {days} day(s). Next day: {state['day']}. Cash £{state['cash']:.2f}.")
    print(f"Last write-up: {last_path}")


if __name__ == "__main__":
    main()
