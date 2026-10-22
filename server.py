import uuid, copy, os
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from data import PLACE_BY_ID
from llm import TripPrefs, parse_prefs, interpret_revision, weights_from
from planner import plan_within_budget

app = FastAPI(title="TrailWise Budget Adventure Planner")
SESSIONS = {}

class PlanReq(BaseModel):
    session_id: str | None = None
    prefs: dict
class ChatReq(BaseModel):
    session_id: str
    message: str
class ScenarioReq(BaseModel):
    session_id: str
    name: str
class ParseReq(BaseModel):
    text: str

def activities(plan):
    return {b["place_id"] for d in plan["days"] for b in d["blocks"] if b["type"] == "activity"}

def replan(s, reason):
    prev = s.get("plan")
    plan = plan_within_budget(s)
    added = activities(plan) - (activities(prev) if prev else set())
    removed = (activities(prev) if prev else set()) - activities(plan)
    diff = []
    if prev:
        if removed: diff.append("Removed: " + ", ".join(PLACE_BY_ID[i]["name"] for i in removed))
        if added: diff.append("Added: " + ", ".join(PLACE_BY_ID[i]["name"] for i in added))
        if prev["cost"]["total"] != plan["cost"]["total"]:
            diff.append(f"Total ₹{prev['cost']['total']:,} → ₹{plan['cost']['total']:,}")
    plan["diff"] = diff
    s["plan"] = plan
    s["history"].append({"reason": reason, "diff": diff, "repairs": plan["repairs"], "status": plan["status"], "total": plan["cost"]["total"]})
    return plan

def payload(s, extra=None):
    d = {"session_id": s["id"], "prefs": s["prefs"], "plan": s["plan"], "history": s["history"], "excluded": s["excluded"],
         "closed": s["closed"], "price_overrides": s["price_overrides"], "flags": s["flags"], "base": {"lat": 30.1285, "lng": 78.3270}}
    d.update(extra or {}); return d

@app.post("/api/parse")
def parse(r: ParseReq):
    p, src = parse_prefs(r.text)
    return {"prefs": p, "source": src}

@app.post("/api/plan")
def plan(r: PlanReq):
    try:
        prefs = TripPrefs(**{k: v for k, v in r.prefs.items() if k in TripPrefs.model_fields}).model_dump()
    except Exception as e:
        raise HTTPException(422, f"Invalid trip requirements: {e}")
    prefs["weights"] = weights_from(prefs["interests"])
    if r.prefs.get("weights"):
        for k, v in r.prefs["weights"].items(): prefs["weights"].setdefault(k, v)
    sid = r.session_id if r.session_id in SESSIONS else uuid.uuid4().hex[:10]
    s = {"id": sid, "prefs": prefs, "excluded": [], "closed": {}, "price_overrides": {}, "flags": {}, "history": [], "plan": None}
    SESSIONS[sid] = s
    replan(s, "Initial plan")
    return payload(s)

def get(sid):
    if sid not in SESSIONS: raise HTTPException(404, "Unknown session; create a plan first")
    return SESSIONS[sid]

def apply(s, a):
    pr = s["prefs"]
    if a.type == "exclude" and a.target in PLACE_BY_ID:
        if a.target not in s["excluded"]: s["excluded"].append(a.target)
        return f"Excluded {PLACE_BY_ID[a.target]['name']}"
    if a.type == "include" and a.target in PLACE_BY_ID:
        if a.target in s["excluded"]: s["excluded"].remove(a.target)
        for t in PLACE_BY_ID[a.target]["tags"]: pr["weights"][t] = pr["weights"].get(t, 0) + 2
        return f"Prioritised {PLACE_BY_ID[a.target]['name']}"
    if a.type == "set_budget_pp" and a.value:
        pr["budget_pp"] = int(a.value); return f"Budget set to ₹{int(a.value):,} per person"
    if a.type == "set_price" and a.target in PLACE_BY_ID and a.value is not None:
        s["price_overrides"][a.target] = float(a.value); return f"{PLACE_BY_ID[a.target]['name']} price now ₹{int(a.value):,}/person (quote)"
    if a.type == "close" and a.target in PLACE_BY_ID:
        s["closed"][a.target] = a.text or "reported closed"; return f"Marked {PLACE_BY_ID[a.target]['name']} unavailable"
    if a.type == "reopen" and a.target in PLACE_BY_ID:
        s["closed"].pop(a.target, None); return f"Reopened {PLACE_BY_ID[a.target]['name']}"
    if a.type == "boost" and a.target:
        for t in {a.target, "nature" if a.target in ("hiking", "waterfall") else a.target}:
            pr["weights"][t] = pr["weights"].get(t, 0) + 4
        if a.target == "nature":
            pr["weights"]["hiking"] = pr["weights"].get("hiking", 0) + 2; pr["weights"]["waterfall"] = pr["weights"].get("waterfall", 0) + 2
            pr["weights"]["adventure"] = max(0, pr["weights"].get("adventure", 0) - 2); pr["weights"]["thrill"] = 0
        return f"Raised priority of '{a.target}' activities"
    if a.type == "set_stay" and a.text in ("hostel", "homestay", "hotel"):
        pr["stay"] = a.text; return f"Stay changed to {a.text}"
    if a.type == "set_pace" and a.text in ("relaxed", "balanced", "packed"):
        pr["pace"] = a.text; return f"Pace changed to {a.text}"
    return None

@app.post("/api/chat")
def chat(r: ChatReq):
    s = get(r.session_id)
    p = s["plan"]
    summary = f"{s['prefs']['days']} days, {s['prefs']['travelers']} travelers, budget ₹{s['prefs']['budget_pp']}pp, total ₹{p['cost']['total']}, activities: {sorted(activities(p))}"
    rev, src = interpret_revision(r.message, summary)
    applied = [x for x in (apply(s, a) for a in rev.actions) if x]
    if not applied:
        return payload(s, {"reply": "I couldn't map that to a change. Try: 'remove rafting', 'rafting now costs ₹1400', 'rafting is closed', 'more nature-focused', 'budget ₹4500'.", "applied": [], "interpreter": src})
    plan = replan(s, r.message)
    return payload(s, {"reply": explain(s, plan, applied, rev.reply), "applied": applied, "interpreter": src})

def explain(s, plan, applied, llm_reply):
    parts = ["Applied: " + "; ".join(applied) + "."] if applied else []
    parts += [d + "." for d in plan["diff"]]
    parts += plan["repairs"]
    if plan["status"] == "ok":
        c = plan["cost"]
        parts.append(f"Validated: ₹{c['total']:,} total vs ₹{c['budget_total']:,} budget (₹{c['remaining']:,} spare, includes ₹{c['contingency']:,} contingency).")
    else:
        parts.append("⚠ No fully valid plan within the constraints: " + " ".join(plan["tradeoffs"][:2]))
    return " ".join(parts)

@app.post("/api/scenario")
def scenario(r: ScenarioReq):
    s = get(r.session_id)
    n = r.name
    if n == "price_spike":
        s["price_overrides"]["rafting"] = 1800; msg = "Scenario: rafting operator quote rose from ₹600 to ₹1,800 per person"
    elif n == "closure":
        s["closed"]["rafting"] = "river closed by authorities (simulated)"; msg = "Scenario: rafting closed (simulated closure)"
    elif n == "nature":
        apply(s, interpret_revision("make it a more nature-focused trip", "")[0].actions[0]); msg = "Scenario: preference changed to more nature-focused"
    elif n == "api_down":
        s["flags"]["api_down"] = True; msg = "Scenario: live routing/weather APIs down, using labelled fallbacks"
    elif n == "api_up":
        s["flags"]["api_down"] = False; msg = "Scenario: APIs restored"
    elif n == "tight_budget":
        s["prefs"]["budget_pp"] = 2500; msg = "Scenario: budget cut to ₹2,500 per person"
    else:
        raise HTTPException(400, "unknown scenario")
    plan = replan(s, msg)
    return payload(s, {"reply": msg + ". " + explain(s, plan, [], ""), "applied": [msg]})

@app.get("/api/state/{sid}")
def state(sid: str): return payload(get(sid))

@app.get("/api/health")
def health():
    return {"llm": bool(os.getenv("ANTHROPIC_API_KEY")), "live_apis": os.getenv("LIVE_APIS", "0") == "1"}

app.mount("/static", StaticFiles(directory="static"), name="static")
@app.get("/")
def index(): return FileResponse("static/index.html")
