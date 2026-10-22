"""Fallback fixture dataset (Rishikesh). Every record carries a source + freshness label."""
FIXTURE_SOURCE = "Fallback fixture (curated estimates, 2026-10)"

def hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)

BASE = {"name": "Stay area (Tapovan/Laxman Jhula)", "lat": 30.1285, "lng": 78.3270}

# best: morning | any | evening ; verified = price taken from an official/operator rate card in the fixture
_P = [
 ("laxman_jhula","Laxman Jhula & riverside market walk",30.1269,78.3297,["sightseeing","culture","shopping"],0,True,60,"06:00","21:00","any","Iconic suspension bridge, cafes and street shopping.",False),
 ("ram_jhula","Ram Jhula & Swarg Ashram ghats",30.1215,78.3150,["sightseeing","culture","spiritual"],0,True,75,"06:00","21:00","any","Walk the ghats and ashram lanes.",False),
 ("triveni_aarti","Triveni Ghat Ganga Aarti",30.1000,78.2970,["culture","spiritual","sightseeing"],0,True,60,"17:00","20:00","evening","Evening river aarti, free.",False),
 ("sunset_beach","Ganga beach sunset & chill",30.1380,78.3350,["nature","relax","sightseeing"],0,True,90,"15:30","19:30","evening","Sand beach on the Ganga, great for sunset.",False),
 ("neer_garh","Neer Garh waterfall trek",30.1352,78.3338,["hiking","nature","waterfall"],30,True,150,"08:00","17:00","morning","Easy forest trail to a tiered waterfall.",False),
 ("patna_falls","Patna waterfall trail",30.1650,78.3420,["hiking","nature","waterfall"],40,False,150,"08:00","16:30","morning","Quieter forest hike, uneven path.",False),
 ("kunjapuri","Kunjapuri temple morning trek (sunrise views)",30.1860,78.2880,["hiking","nature","sunrise","culture"],100,False,180,"05:30","18:00","morning","Himalayan sunrise viewpoint at a hilltop temple.",False),
 ("neelkanth","Neelkanth Mahadev temple trail",30.0990,78.3990,["culture","spiritual","nature","hiking"],0,True,180,"06:00","19:00","any","Forest temple reached by a scenic trail/road.",False),
 ("rafting","White-water rafting, Shivpuri (16 km)",30.1470,78.4030,["adventure","water","rafting"],600,True,180,"08:00","16:00","morning","Grade II-III rapids, the Rishikesh classic.",True),
 ("kayaking","Kayaking lesson on the Ganga",30.1400,78.4050,["adventure","water"],900,False,150,"08:00","16:00","morning","Beginner kayak session with instructor.",True),
 ("bungee","Bungee jump, Mohan Chatti",30.0720,78.4440,["adventure","thrill"],3700,True,90,"09:00","16:00","any","India's highest fixed-platform bungee. Premium price.",False),
 ("zipline","Flying fox / zipline, Mohan Chatti",30.0725,78.4435,["adventure","thrill"],1400,False,60,"09:00","16:00","any","Zipline over the valley.",False),
 ("beatles","Beatles Ashram (Chaurasi Kutia)",30.1224,78.3282,["culture","history","photography","sightseeing"],150,True,90,"09:00","17:00","any","Graffiti-covered ruins where the Beatles stayed in 1968.",False),
 ("yoga","Morning yoga & meditation class",30.1300,78.3260,["wellness","culture","relax"],300,False,90,"06:00","09:00","morning","Drop-in ashram class.",False),
 ("food_walk","Cafe hopping & local street-food trail",30.1262,78.3290,["food","local","culture"],300,False,120,"10:00","21:00","any","Chaat, aloo puri, kachori, thali and riverside cafes.",False),
]
MAXSTART = {'kunjapuri': hm('10:00'), 'yoga': hm('07:30')}
PLACES = []
for (i,n,la,lo,tg,c,v,d,o,cl,b,ds,ws) in _P:
    PLACES.append(dict(id=i,name=n,lat=la,lng=lo,tags=tg,cost_pp=c,price_verified=v,
        price_source=("Operator/official rate card (fixture)" if v else "Estimate from typical market range (fixture)"),
        dur=d,open=hm(o),close=hm(cl),best=b,desc=ds,weather_sensitive=ws,closed_weekdays=[],max_start=MAXSTART.get(i, hm('12:00') if b=='morning' else 24*60)))
PLACE_BY_ID = {p["id"]: p for p in PLACES}

ALIASES = {
 "rafting":"rafting","raft":"rafting","kayak":"kayaking","bungee":"bungee","zip":"zipline","flying fox":"zipline",
 "kunjapuri":"kunjapuri","sunrise":"kunjapuri","neelkanth":"neelkanth","beatles":"beatles","ashram":"beatles",
 "aarti":"triveni_aarti","triveni":"triveni_aarti","neer garh":"neer_garh","waterfall":"neer_garh","patna":"patna_falls",
 "yoga":"yoga","cafe":"food_walk","food":"food_walk","laxman":"laxman_jhula","ram jhula":"ram_jhula","sunset":"sunset_beach","beach":"sunset_beach",
}

STAYS = {  # unit: person | room
 "hostel":   {"label":"Hostel dorm bed","price":550,"unit":"person"},
 "homestay": {"label":"Homestay room","price":1100,"unit":"room"},
 "hotel":    {"label":"Budget hotel room","price":1600,"unit":"room"},
}
MEALS = {"street":250,"local":400,"cafe":650}  # per person per full day
INTERCITY = {"label":"Delhi <-> Rishikesh bus (return)","price_pp":900,"verified":False}
CONTINGENCY_PCT = 0.10

TAG_WORDS = {
 "hik":"hiking","trek":"hiking","nature":"nature","adventure":"adventure","raft":"rafting","water":"water",
 "food":"food","culture":"culture","spiritual":"spiritual","sightsee":"sightseeing","relax":"relax","wellness":"wellness",
 "history":"history","photo":"photography","thrill":"thrill","local":"local","waterfall":"waterfall",
}
