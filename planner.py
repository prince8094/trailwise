"""Deterministic planner + validators + budget repair loop."""
import math, datetime as dt
from data import *
from tools import Tools, haversine

BUFFER = 15
LUNCH_WIN = (12*60, 15*60)
DAY_END_DEFAULT = 21*60 + 30
RANK = {"morning": 0, "any": 1, "evening": 2}

def fm(m):
    return f"{m//60:02d}:{m%60:02d}"

def pace_slots(pace):
    return {"relaxed": 2, "balanced": 3, "packed": 4}.get(pace, 3)

def score(p, prefs, state):
    w = prefs["weights"]
    s = 0.5 + sum(w.get(t, 0) for t in p["tags"])
    return s - 3.0 * state["price_overrides"].get(p["id"], p["cost_pp"]) / max(prefs["budget_pp"], 1)

def open_on(p, date, state):
    if p["id"] in state["closed"]:
        return False
    return date.weekday() not in p["closed_weekdays"]

def day_windows(prefs):
    start = dt.date.fromisoformat(prefs["start_date"])
    out = []
    for i in range(prefs["days"]):
        s = hm(prefs["arrival_time"]) + 60 if i == 0 else 7*60 + 30
        e = hm(prefs["departure_time"]) - 90 if i == prefs["days"] - 1 else DAY_END_DEFAULT
        out.append((start + dt.timedelta(days=i), s, e))
    return out

def schedule_day(date, chosen, s_min, e_min, tools, prefs, state):
    """Simulate a day. Returns blocks, dropped[(place, reason)]."""
    order, pos = [], BASE
    for rank in (0, 1, 2):
        grp = [p for p in chosen if RANK[p["best"]] == rank]
        while grp:
            nxt = min(grp, key=lambda p: haversine(pos, p)); grp.remove(nxt); order.append(nxt); pos = nxt
    blocks, dropped = [], []
    t, pos, lunch = s_min, dict(BASE), False

    def add_lunch(at):
        nonlocal t, lunch
        st = max(at, LUNCH_WIN[0])
        blocks.append(dict(type="meal", title="Lunch (" + ("cafe)" if prefs["meal_style"] == "cafe" else "local thali/dhaba)"),
                           start=st, end=st+60, lat=pos["lat"], lng=pos["lng"], cost_total=0, source="Included in daily meal budget"))
        t, lunch = st + 60, True

    for p in order:
        if not lunch and t >= LUNCH_WIN[0]:
            add_lunch(t)
        leg = tools.route(pos, p)
        arrive = t + leg["min"] + BUFFER
        start = max(arrive, p["open"])
        end = start + p["dur"]
        if not lunch and start >= 11*60 and end > 14*60 + 30 and t <= 14*60 and p["best"] != "evening":
            add_lunch(t); arrive = t + leg["min"] + BUFFER; start = max(arrive, p["open"]); end = start + p["dur"]
        if start > p["max_start"]:
            dropped.append((p, f"would start {fm(start)}, too late for a {p['best']} activity")); continue
        if end > p["close"]:
            dropped.append((p, f"cannot finish before closing ({fm(p['close'])})")); continue
        if end > e_min:
            dropped.append((p, f"does not fit before day end ({fm(e_min)})")); continue
        if start - arrive > 120:
            dropped.append((p, f"would wait {start-arrive} min for opening")); continue
        pr = tools.price(p)
        if leg["fare"] or leg["min"]:
            blocks.append(dict(type="transfer", title=f"{leg['mode']} to {p['name']}", start=t, end=t+leg["min"],
                               km=round(leg["km"], 1), cost_total=leg["fare"], source=leg["source"], lat=p["lat"], lng=p["lng"],
                               for_place=p["id"]))
        blocks.append(dict(type="activity", place_id=p["id"], title=p["name"], start=start, end=end, lat=p["lat"], lng=p["lng"],
                           cost_pp=pr["cost_pp"], cost_total=pr["cost_pp"]*prefs["travelers"], verified=pr["verified"],
                           source=pr["source"], desc=p["desc"], tags=p["tags"], open=p["open"], close=p["close"], wait=start-arrive))
        t, pos = end, p
    if not lunch and t <= LUNCH_WIN[1] and e_min >= 14*60 and s_min <= 13*60:
        add_lunch(t)
    if blocks and haversine(pos, BASE) > 0.05:
        leg = tools.route(pos, BASE)
        if t + leg["min"] <= e_min:
            blocks.append(dict(type="transfer", title="Return to stay", start=t, end=t+leg["min"], km=round(leg["km"], 1),
                               cost_total=leg["fare"], source=leg["source"], lat=BASE["lat"], lng=BASE["lng"], for_place=None))
            t += leg["min"]
    if e_min >= 20*60 and t <= 20*60 + 30:
        st = max(t + 10, 19*60 + 30)
        if st + 60 <= e_min:
            blocks.append(dict(type="meal", title="Dinner", start=st, end=st+60, lat=BASE["lat"], lng=BASE["lng"], cost_total=0,
                               source="Included in daily meal budget"))
    return blocks, dropped

def build(state, tools, agent_ex):
    prefs = state["prefs"]
    pool = [p for p in tools.place_search(prefs) if p["id"] not in state["excluded"] and p["id"] not in agent_ex]
    wins = day_windows(prefs)
    weather = {d: tools.weather(d) for d, _, _ in wins}
    for d, w in weather.items():
        tools._log("weather", {"date": str(d)}, w["source"], "ok", f"{w['precip']}% rain, {w['tmax']}°C")
    used, days, notes = set(), [], []
    for idx, (date, s, e) in enumerate(wins):
        slots = max(1, min(pace_slots(prefs["pace"]), (e - s) // 170))
        rain = weather[date]["precip"] >= 60
        base = [p for p in pool if p["id"] not in used and open_on(p, date, state) and score(p, prefs, state) > 1.0]
        avail = [p for p in base if not (rain and p["weather_sensitive"])]
        for p in base:
            if rain and p["weather_sensitive"] and score(p, prefs, state) > 2.5:
                notes.append(f"{p['name']} kept off {date:%a %d %b} ({weather[date]['precip']}% rain forecast).")
        chosen = []
        if avail:
            anchor = max(avail, key=lambda p: score(p, prefs, state)); chosen = [anchor]
            while len(chosen) < slots:
                rest = [p for p in avail if p not in chosen]
                if not rest: break
                chosen.append(max(rest, key=lambda p: score(p, prefs, state) - 0.12*haversine(anchor, p)))
        blocks, dropped = schedule_day(date, chosen, s, e, tools, prefs, state)
        placed = {b["place_id"] for b in blocks if b["type"] == "activity"}
        if len(placed) < slots:
            tried = {p["id"] for p, _ in dropped}
            extra = sorted([p for p in avail if p["id"] not in placed and p["id"] not in tried], key=lambda p: -score(p, prefs, state))
            for p in extra:
                if len(placed) >= slots: break
                trial = [q for q in avail if q["id"] in placed] + [p]
                b2, d2 = schedule_day(date, trial, s, e, tools, prefs, state)
                pl2 = {b["place_id"] for b in b2 if b["type"] == "activity"}
                if len(pl2) > len(placed):
                    blocks, placed = b2, pl2
        used |= placed
        days.append(dict(date=str(date), label=f"Day {idx+1}", window=[fm(s), fm(e)], weather=weather[date], blocks=blocks))
    return days, sorted(set(notes))

def meals_for_day(prefs, window):
    s, e = hm(window[0]), hm(window[1])
    share = 0.0
    if s <= 9*60 + 30: share += 0.25
    if s <= 13*60 and e >= 14*60: share += 0.35
    if e >= 20*60: share += 0.40
    return share * MEALS[prefs["meal_style"]] * prefs["travelers"]

def cost_model(state, days):
    prefs = state["prefs"]; n = prefs["travelers"]; nights = prefs["days"] - 1
    lines = []
    for d in days:
        for b in d["blocks"]:
            if b["type"] == "activity":
                lines.append(dict(category="Activities", item=f"{b['title']} ({d['label']})", amount=b["cost_total"], verified=b["verified"], source=b["source"]))
            elif b["type"] == "transfer" and b["cost_total"]:
                lines.append(dict(category="Local transport", item=f"{b['title']} ({d['label']})", amount=b["cost_total"], verified=False, source=b["source"]))
        m = round(meals_for_day(prefs, d["window"]))
        lines.append(dict(category="Meals", item=f"{prefs['meal_style']} meals ({d['label']})", amount=m, verified=False, source="Estimate: fixture per-person daily meal cost"))
    if nights > 0:
        lines.append(dict(category="Accommodation", item=f"{STAYS[prefs['stay']]['label']} x {nights} night(s)", amount=_stay_cost(prefs, prefs["stay"], nights), verified=False, source="Estimate: fixture typical nightly rate"))
    if prefs["include_intercity"]:
        lines.append(dict(category="Intercity transport", item=INTERCITY["label"] + f" x {n}", amount=INTERCITY["price_pp"] * n, verified=False, source="Estimate: fixture typical bus fare"))
    sub = sum(l["amount"] for l in lines)
    cont = round(sub * CONTINGENCY_PCT)
    total = sub + cont
    budget = prefs["budget_pp"] * n
    ver = sum(l["amount"] for l in lines if l["verified"])
    cats = {}
    for l in lines: cats[l["category"]] = cats.get(l["category"], 0) + l["amount"]
    cats["Contingency (10%)"] = cont
    return dict(lines=lines, by_category=cats, subtotal=sub, contingency=cont, total=total, per_person=round(total/n),
                budget_total=budget, budget_pp=prefs["budget_pp"], remaining=budget - total, within_budget=total <= budget,
                verified_amount=ver, estimated_amount=sub - ver)

def validate(state, days, cost):
    checks = []
    def add(name, ok, detail, hard=True): checks.append(dict(name=name, ok=ok, detail=detail, hard=hard))
    add("Total within budget", cost["within_budget"],
        f"₹{cost['total']:,} vs budget ₹{cost['budget_total']:,}" + ("" if cost["within_budget"] else f" (over by ₹{-cost['remaining']:,})"))
    for d in days:
        acts = [b for b in d["blocks"] if b["type"] == "activity"]
        s, e = hm(d["window"][0]), hm(d["window"][1])
        bad = [a["title"] for a in acts if a["start"] < a["open"] or a["end"] > a["close"]]
        add(f"{d['label']}: inside opening hours", not bad, "All stops open during visit" if not bad else "Violations: " + ", ".join(bad))
        over = [b for b in d["blocks"] if b["end"] > e or b["start"] < s]
        add(f"{d['label']}: within day window {d['window'][0]}-{d['window'][1]}", not over, "OK" if not over else "Block outside window")
        bl = sorted(d["blocks"], key=lambda b: (b["start"], b["end"]))
        ov = [(a["title"], b["title"]) for a, b in zip(bl, bl[1:]) if b["start"] < a["end"]]
        add(f"{d['label']}: no overlaps", not ov, "OK" if not ov else f"{ov[0][0]} overlaps {ov[0][1]}")
        add(f"{d['label']}: ≥{BUFFER} min buffer included", True, f"{BUFFER} min added to every transfer")
        if s <= 12*60 and e >= 14*60:
            lunch = any(b["type"] == "meal" and "Lunch" in b["title"] for b in d["blocks"])
            add(f"{d['label']}: lunch scheduled", lunch, "Lunch block present" if lunch else "No lunch slot fit", hard=False)
        if not acts:
            add(f"{d['label']}: has activities", False, "No feasible activity fit this day", hard=False)
    present = {b["place_id"] for d in days for b in d["blocks"] if b["type"] == "activity"}
    add("Excluded/closed items absent", not (present & (set(state["excluded"]) | set(state["closed"]))), "OK")
    return checks

def cheaper_alternatives(place, state, tools):
    out = []
    mine = tools.price(place)["cost_pp"]
    for p in PLACES:
        if p["id"] == place["id"] or p["id"] in state["excluded"] or p["id"] in state["closed"]: continue
        c = tools.price(p)["cost_pp"]
        if set(p["tags"]) & set(place["tags"]) and c < mine:
            out.append(dict(id=p["id"], name=p["name"], cost_pp=c, saves_pp=mine - c))
    return sorted(out, key=lambda x: x["cost_pp"])[:3]

def attributable(day, block):
    c = block["cost_total"]
    for b in day["blocks"]:
        if b["type"] == "transfer" and b.get("for_place") == block["place_id"]:
            c += b["cost_total"]
    return c

def _stay_cost(prefs, key, nights):
    st = STAYS[key]; n = prefs["travelers"]
    return st["price"] * n * nights if st["unit"] == "person" else st["price"] * math.ceil(n/2) * nights

def plan_within_budget(state):
    tools = Tools(state); prefs = state["prefs"]; n = prefs["travelers"]
    agent_ex, repairs = {}, []
    days, notes = build(state, tools, agent_ex)
    cost = cost_model(state, days)
    for _ in range(20):
        if cost["within_budget"]: break
        cands = [(attributable(d, b), b) for d in days for b in d["blocks"] if b["type"] == "activity" and attributable(d, b) > 0]
        if not cands: break
        amt, b = max(cands, key=lambda x: x[0])
        over, prev_total = -cost["remaining"], cost["total"]
        old = {x["place_id"] for d in days for x in d["blocks"] if x["type"] == "activity"}
        agent_ex[b["place_id"]] = True
        days, notes = build(state, tools, agent_ex); cost = cost_model(state, days)
        new = {x["place_id"] for d in days for x in d["blocks"] if x["type"] == "activity"}
        for _try in range(4):  # a substitute must not make the plan more expensive
            if cost["total"] < prev_total: break
            pricey = [i for i in new - old if tools.price(PLACE_BY_ID[i])["cost_pp"] > 0]
            if not pricey: break
            for i in pricey: agent_ex[i] = True
            days, notes = build(state, tools, agent_ex); cost = cost_model(state, days)
            new = {x["place_id"] for d in days for x in d["blocks"] if x["type"] == "activity"}
        added = [PLACE_BY_ID[i]["name"] for i in new - old]
        repairs.append(f"Over budget by ₹{over:,}: removed '{b['title']}' (₹{amt:,} incl. transfers)" +
                       (f", substituted '{added[0]}'" if added else ", no costlier substitute accepted") + f". New total ₹{cost['total']:,}.")
        tools._log("repair", {"remove": b["place_id"], "over_by": over}, "Deterministic budget engine")
    checks = validate(state, days, cost)
    hard_ok = all(c["ok"] for c in checks if c["hard"])
    tradeoffs = []
    if not cost["within_budget"]:
        short = -cost["remaining"]
        tradeoffs.append(f"Cheapest plan found still costs ₹{cost['total']:,}; budget short by ₹{short:,}. Not claiming success.")
        tradeoffs.append(f"Option: raise budget to ≥ ₹{math.ceil(cost['total']/n/50)*50:,} per person.")
        if prefs["stay"] != "hostel":
            tradeoffs.append(f"Option: switch to hostel beds (saves ≈ ₹{_stay_cost(prefs, prefs['stay'], prefs['days']-1) - _stay_cost(prefs, 'hostel', prefs['days']-1):,}).")
        if prefs["include_intercity"]:
            tradeoffs.append(f"Option: drop intercity bus if you arrive separately (saves ₹{INTERCITY['price_pp']*n:,}).")
        if prefs["meal_style"] != "street":
            tradeoffs.append("Option: street-food meals (≈ ₹250/person/day).")
        if prefs["days"] > 1: tradeoffs.append("Option: shorten the trip by one day.")
    for d in days:
        for b in d["blocks"]:
            if b["type"] == "activity":
                b["alternatives"] = cheaper_alternatives(PLACE_BY_ID[b["place_id"]], state, tools) if b["cost_pp"] > 0 else []
    assumptions = [
        "Distances are straight-line ×1.4 estimates unless a live routing API answered (see source labels).",
        "Local transport = shared auto/taxi, ₹20/km per vehicle (min ₹50), 1 vehicle per 3 travelers; walking under 1 km is free.",
        "Contingency is a flat 10% of the subtotal.",
        "Accommodation, meals and intercity fares are estimates, not live quotes.",
    ]
    unresolved = []
    if prefs["destination"].strip().lower() != "rishikesh":
        unresolved.append(f"No fixture data for '{prefs['destination']}': showing Rishikesh sample data. Connect a places API for other destinations.")
    if cost["estimated_amount"] > 0:
        unresolved.append(f"₹{cost['estimated_amount']:,} of the subtotal is estimated, not verified.")
    for pid, why in state["closed"].items():
        unresolved.append(f"{PLACE_BY_ID[pid]['name']} marked unavailable: {why}")
    status = "ok" if (hard_ok and cost["within_budget"]) else "infeasible"
    return dict(status=status, days=days, cost=cost, checks=checks, hard_ok=hard_ok, repairs=repairs, notes=notes,
                tradeoffs=tradeoffs, assumptions=assumptions, unresolved=unresolved, toolcalls=tools.log,
                agent_removed=list(agent_ex.keys()))
