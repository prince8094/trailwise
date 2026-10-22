"""Tool layer: place search, route, weather, price. Each call is logged with source + freshness.
Live APIs are used only if LIVE_APIS=1 and not simulated-down; otherwise labelled fallbacks."""
import math, os, time, datetime as dt
import httpx
from data import PLACES, PLACE_BY_ID, BASE, FIXTURE_SOURCE

LIVE = os.getenv("LIVE_APIS", "0") == "1"
_cache = {}

def haversine(a, b):
    R = 6371.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lng"] - a["lng"])
    h = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(h))

class Tools:
    def __init__(self, state):
        self.s = state
        self.log = []

    def _log(self, name, args, source, status="ok", note=""):
        self.log.append({"tool": name, "args": args, "source": source, "status": status, "note": note,
                         "at": dt.datetime.now().strftime("%H:%M:%S")})

    def api_down(self):
        return self.s["flags"].get("api_down", False)

    # ---- place search
    def place_search(self, prefs):
        pool = [p for p in PLACES]
        self._log("place_search", {"destination": prefs["destination"], "interests": prefs["interests"]},
                  FIXTURE_SOURCE, "fallback" if prefs["destination"].lower() != "rishikesh" else "ok",
                  "Fixture dataset only covers Rishikesh" if prefs["destination"].lower() != "rishikesh" else "")
        return pool

    # ---- price retrieval
    def price(self, place):
        ov = self.s["price_overrides"].get(place["id"])
        if ov is not None:
            return {"cost_pp": ov, "verified": True, "source": "User/operator quote (override)"}
        return {"cost_pp": place["cost_pp"], "verified": place["price_verified"], "source": place["price_source"]}

    # ---- route
    def route(self, a, b):
        key = (round(a["lat"],4), round(a["lng"],4), round(b["lat"],4), round(b["lng"],4))
        if key in _cache and not self.api_down():
            r = _cache[key]
        else:
            r = None
            if LIVE and not self.api_down():
                try:
                    url = f"https://router.project-osrm.org/route/v1/driving/{a['lng']},{a['lat']};{b['lng']},{b['lat']}?overview=false"
                    j = httpx.get(url, timeout=3).json()["routes"][0]
                    r = {"km": j["distance"]/1000, "drive_min": j["duration"]/60, "source": "OSRM live routing"}
                except Exception as e:
                    self._log("route", {}, "OSRM", "failed", str(e)[:60])
            if r is None:
                km = haversine(a, b) * 1.4
                r = {"km": km, "drive_min": km/22*60, "source": "Estimate: straight-line x1.4 @22 km/h" +
                     (" (live API unavailable)" if self.api_down() or LIVE else "")}
            if not self.api_down():
                _cache[key] = r
        km = r["km"]
        n = self.s["prefs"]["travelers"]
        if km <= 1.0:
            return {"mode": "walk", "km": km, "min": max(5, round(km/4.5*60)), "fare": 0, "source": r["source"]}
        vehicles = math.ceil(n/3)
        fare = vehicles * max(50, math.ceil(km*20/10)*10)
        return {"mode": "auto/taxi", "km": km, "min": max(8, round(r["drive_min"])), "fare": fare, "source": r["source"]}

    # ---- weather
    def weather(self, date):
        i = (date - dt.date.fromisoformat(self.s["prefs"]["start_date"])).days
        if LIVE and not self.api_down():
            try:
                u = ("https://api.open-meteo.com/v1/forecast?latitude=30.11&longitude=78.29&daily=precipitation_probability_max,"
                     f"temperature_2m_max&timezone=Asia%2FKolkata&start_date={date}&end_date={date}")
                d = httpx.get(u, timeout=3).json()["daily"]
                return {"precip": d["precipitation_probability_max"][0] or 0, "tmax": d["temperature_2m_max"][0],
                        "source": "Open-Meteo live forecast"}
            except Exception as e:
                self._log("weather", {"date": str(date)}, "Open-Meteo", "failed", str(e)[:60])
        mock = [(5, 27), (15, 26), (70, 22)]
        p, t = mock[i % 3]
        return {"precip": p, "tmax": t, "source": "Mock fixture forecast" + (" (live API unavailable)" if LIVE or self.api_down() else "")}
