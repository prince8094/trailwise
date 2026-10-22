"""LLM layer (Anthropic) with schema-validated JSON output and a deterministic heuristic fallback."""
import os, re, json, datetime as dt
from typing import Literal, Optional, List
import httpx
from pydantic import BaseModel, Field, ValidationError
from data import ALIASES, TAG_WORDS, PLACE_BY_ID

API_KEY = lambda: os.getenv("ANTHROPIC_API_KEY", "")
MODEL = lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

class TripPrefs(BaseModel):
    destination: str = "Rishikesh"
    start_date: str = Field(default_factory=lambda: (dt.date.today() + dt.timedelta(days=14)).isoformat())
    days: int = Field(3, ge=1, le=7)
    travelers: int = Field(2, ge=1, le=12)
    budget_pp: int = Field(5500, ge=500, le=200000)
    arrival_time: str = "08:00"
    departure_time: str = "18:00"
    pace: Literal["relaxed", "balanced", "packed"] = "balanced"
    stay: Literal["hostel", "homestay", "hotel"] = "homestay"
    meal_style: Literal["street", "local", "cafe"] = "local"
    include_intercity: bool = True
    interests: List[str] = ["hiking", "rafting", "food", "culture"]
    weights: dict = {}

class Action(BaseModel):
    type: Literal["exclude", "include", "set_budget_pp", "set_price", "close", "reopen", "boost", "set_stay", "set_pace"]
    target: Optional[str] = None      # place id or tag
    value: Optional[float] = None
    text: Optional[str] = None

class Revision(BaseModel):
    actions: List[Action]
    reply: str = ""

def weights_from(interests):
    w = {"sightseeing": 1, "culture": 1}
    for i in interests:
        t = i.lower()
        for k, tag in TAG_WORDS.items():
            if k in t:
                w[tag] = w.get(tag, 0) + 3
                if tag == "hiking": w["nature"] = w.get("nature", 0) + 2
                if tag == "adventure": w["water"] = w.get("water", 0) + 1
                if tag == "rafting": w["water"] = w.get("water", 0) + 2; w["adventure"] = w.get("adventure", 0) + 1
                if tag == "food": w["local"] = w.get("local", 0) + 2
    return w

NUM = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7}
def _num(s):
    s = s.lower().replace(",", "")
    return NUM.get(s) or int(s)

def heuristic_parse(text):
    t = text.lower(); out = {}
    m = re.search(r"(?:₹|rs\.?|inr)\s*([\d,]+)\s*(?:k\b)?\s*(per person|pp|each|/person|total)?", t) or re.search(r"([\d,]+)\s*(?:rupees|rs)\s*(per person|pp|each|total)?", t)
    ppl = re.search(r"(?:for|group of|with)\s+(\d+|one|two|three|four|five|six)\s*(?:people|persons|travell?ers|friends|of us|adults)?", t) or re.search(r"(\d+|two|three|four|five|six)\s*(?:people|persons|travell?ers|friends)", t)
    if ppl:
        try: out["travelers"] = _num(ppl.group(1))
        except Exception: pass
    if m:
        v = int(m.group(1).replace(",", ""))
        if re.search(r"₹\s*[\d,]+\s*k", t): v *= 1000
        out["budget_pp"] = v // out.get("travelers", 2) if (m.group(2) or "") == "total" else v
    d = re.search(r"(\d+|one|two|three|four|five)[\s-]*(?:day|days)", t)
    if d: out["days"] = _num(d.group(1))
    for dest in ["rishikesh", "manali", "goa", "jaipur", "munnar", "kasol"]:
        if dest in t: out["destination"] = dest.title()
    ints = [w for w in ["hiking","trekking","adventure","rafting","food","culture","nature","sightseeing","waterfall","spiritual","wellness","relax","photography"] if w in t]
    if ints: out["interests"] = ints
    if "hostel" in t: out["stay"] = "hostel"
    elif "hotel" in t: out["stay"] = "hotel"
    elif "homestay" in t: out["stay"] = "homestay"
    for k in ("relaxed", "packed"):
        if k in t: out["pace"] = k
    dm = re.search(r"(\d{4}-\d{2}-\d{2})", t)
    if dm: out["start_date"] = dm.group(1)
    return out

def _call(system, user, max_tokens=800):
    r = httpx.post("https://api.anthropic.com/v1/messages", timeout=40,
        headers={"x-api-key": API_KEY(), "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": MODEL(), "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user}]})
    r.raise_for_status()
    txt = r.json()["content"][0]["text"]
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0))

def parse_prefs(text):
    """Natural language -> validated TripPrefs dict. Returns (prefs, source)."""
    partial, source = {}, "heuristic parser"
    if API_KEY():
        try:
            sys = ("Extract trip constraints as JSON only. Keys (omit unknown): destination, days(int), travelers(int), budget_pp(int INR per person; "
                   "divide totals by travelers), interests(list of lowercase words), stay(hostel|homestay|hotel), pace(relaxed|balanced|packed), start_date(YYYY-MM-DD).")
            partial = _call(sys, text, 400); source = f"LLM ({MODEL()}) + schema validation"
        except Exception as e:
            partial, source = heuristic_parse(text), f"heuristic parser (LLM failed: {str(e)[:50]})"
    else:
        partial = heuristic_parse(text)
    try:
        p = TripPrefs(**{k: v for k, v in partial.items() if k in TripPrefs.model_fields}).model_dump()
    except ValidationError:
        p = TripPrefs(**heuristic_parse(text)).model_dump()
    p["weights"] = weights_from(p["interests"])
    return p, source

def find_place(text):
    t = text.lower()
    for k in sorted(ALIASES, key=len, reverse=True):
        if k in t: return ALIASES[k]
    for pid, p in PLACE_BY_ID.items():
        if p["name"].lower() in t: return pid
    return None

def heuristic_revise(msg):
    t = msg.lower(); acts = []
    pid = find_place(t)
    price = re.search(r"(?:₹|rs\.?)\s*([\d,]+)", t)
    if re.search(r"\b(closed|unavailable|cancel+ed|shut)\b", t) and pid:
        acts.append(Action(type="close", target=pid, text=msg))
    elif re.search(r"\b(reopen|re-open|available again|open again)\b", t) and pid:
        acts.append(Action(type="reopen", target=pid))
    elif re.search(r"\b(remove|skip|drop|exclude|no more|don'?t want|without)\b", t) and pid:
        acts.append(Action(type="exclude", target=pid))
    elif re.search(r"\b(add|include|i want|must)\b", t) and pid:
        acts.append(Action(type="include", target=pid))
    elif price and pid and re.search(r"cost|price|quote|now|rate|charge|increase|hike", t):
        acts.append(Action(type="set_price", target=pid, value=float(price.group(1).replace(",", ""))))
    if re.search(r"budget", t) and price and not pid:
        v = float(price.group(1).replace(",", ""))
        acts.append(Action(type="set_budget_pp", value=v))
    for k, tag in [("nature", "nature"), ("hik", "hiking"), ("trek", "hiking"), ("adventure", "adventure"), ("food", "food"), ("cultur", "culture"), ("spiritual", "spiritual"), ("relax", "relax"), ("waterfall", "waterfall"), ("photo", "photography")]:
        if re.search(r"more|focus|prefer|instead|rather|nature-focused", t) and k in t and not pid:
            acts.append(Action(type="boost", target=tag))
    for s in ("hostel", "hotel", "homestay"):
        if s in t and re.search(r"stay|switch|use|prefer|change", t): acts.append(Action(type="set_stay", text=s))
    for s in ("relaxed", "packed"):
        if s in t: acts.append(Action(type="set_pace", text=s))
    return Revision(actions=acts, reply="")

def interpret_revision(msg, summary):
    if API_KEY():
        try:
            ids = ", ".join(PLACE_BY_ID)
            sys = ("You are a travel-replanning agent. Convert the user's message to JSON only: "
                   '{"actions":[{"type":"exclude|include|set_budget_pp|set_price|close|reopen|boost|set_stay|set_pace","target":"<place id or tag>","value":number,"text":"stay/pace value or reason"}],"reply":"one short sentence"}. '
                   f"Valid place ids: {ids}. Tags for boost: nature, hiking, adventure, food, culture, spiritual, relax, waterfall, photography. "
                   "set_price value = INR per person. set_budget_pp value = INR per person. Never claim the budget is met; the validator decides.")
            data = _call(sys, f"Current plan summary: {summary}\nUser message: {msg}", 500)
            rev = Revision(**data)
            ok = [a for a in rev.actions if a.type in ("set_budget_pp", "boost", "set_stay", "set_pace") or (a.target in PLACE_BY_ID)]
            if ok or rev.actions == []:
                return Revision(actions=ok, reply=rev.reply), f"LLM ({MODEL()}) + schema validation"
        except Exception as e:
            r = heuristic_revise(msg); return r, f"heuristic parser (LLM failed: {str(e)[:50]})"
    return heuristic_revise(msg), "heuristic parser (no ANTHROPIC_API_KEY set)"
