"""
Fetch published specifications for aircraft types flown by the Indian Air Force and Army Aviation from
Wikipedia's {{Aircraft specs}} templates. Output: one row per type, metric units. Text is CC BY-SA 4.0.

Usage: python fetch_aircraft_types.py <out.csv>
"""
import csv
import re
import sys
import time

import httpx

# (AirOps resource type, Wikipedia article, display name, role)
TYPES = [
    ("HEAVY_AIRCRAFT", "Boeing C-17 Globemaster III", "C-17 Globemaster III", "Strategic airlift"),
    ("HEAVY_AIRCRAFT", "Ilyushin Il-76", "Il-76MD Gajraj", "Strategic airlift"),
    ("HEAVY_AIRCRAFT", "Lockheed Martin C-130J Super Hercules", "C-130J-30 Super Hercules", "Tactical airlift, special operations"),
    ("TRANSPORT_AIRCRAFT", "Antonov An-32", "An-32RE", "Tactical airlift"),
    ("TRANSPORT_AIRCRAFT", "Airbus C-295", "C-295MW", "Tactical airlift"),
    ("TRANSPORT_AIRCRAFT", "Dornier 228", "Do 228", "Light transport, maritime patrol"),
    ("HEAVY_HELICOPTER", "Boeing CH-47 Chinook", "CH-47F(I) Chinook", "Heavy-lift helicopter"),
    ("TACTICAL_HELICOPTER", "Mil Mi-17", "Mi-17V5", "Medium-lift utility helicopter"),
    ("LIGHT_HELICOPTER", "HAL Dhruv", "ALH Dhruv", "Utility helicopter"),
    ("LIGHT_HELICOPTER", "Aérospatiale SA 315B Lama", "Cheetah (SA 315B Lama)", "High-altitude light helicopter"),
    ("ATTACK_HELICOPTER", "HAL Prachand", "LCH Prachand", "Light combat helicopter"),
    ("ATTACK_HELICOPTER", "Boeing AH-64 Apache", "AH-64E Apache", "Attack helicopter"),
    ("ATTACK_HELICOPTER", "HAL Rudra", "ALH Rudra", "Armed utility helicopter"),
]

TEXT_FIELDS = {"crew": "crew", "capacity": "capacity"}
# output column -> [(template parameter, factor to metric)]; the first parameter with a value wins
NUM_FIELDS = {
    "max_takeoff_weight_kg": [("max takeoff weight kg", 1), ("max takeoff weight lb", 0.45359)],
    "max_speed_kmh": [("max speed kmh", 1), ("max speed kts", 1.852), ("max speed mph", 1.60934)],
    "cruise_speed_kmh": [("cruise speed kmh", 1), ("cruise speed kts", 1.852), ("cruise speed mph", 1.60934)],
    "range_km": [("range km", 1), ("range nmi", 1.852), ("range mi", 1.60934), ("range miles", 1.60934),
                 ("combat range km", 1), ("combat range nmi", 1.852), ("combat range mi", 1.60934), ("combat range miles", 1.60934)],
    "ferry_range_km": [("ferry range km", 1), ("ferry range nmi", 1.852), ("ferry range mi", 1.60934), ("ferry range miles", 1.60934)],
    "service_ceiling_m": [("ceiling m", 1), ("ceiling ft", 0.3048)],
}


def clean(v: str) -> str:
    v = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", v, flags=re.S)
    v = re.sub(r"\{\{(?:cvt|convert)\|([\d.,]+)\|[^}]*\}\}", r"\1", v)
    v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"\{\{[^}]*\}\}|<[^>]+>|'''|''", "", v)
    return re.sub(r"\s+", " ", v).strip(" ;,")


def number(v: str):
    m = re.search(r"\d[\d,]*(?:\.\d+)?", v or "")
    return float(m.group().replace(",", "")) if m else None


def specs(wikitext: str) -> dict:
    """The first {{Aircraft specs}} block's parameters."""
    start = wikitext.find("{{Aircraft specs")
    if start < 0:
        return {}
    depth, i = 0, start
    while i < len(wikitext):
        if wikitext.startswith("{{", i):
            depth += 1
            i += 2
        elif wikitext.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                break
        else:
            i += 1
    block = wikitext[start:i]
    out = {}
    for m in re.finditer(r"\n\|[ \t]*([a-z][a-z0-9 ]*?)[ \t]*=[ \t]*(.*?)(?=\n\||\n\}\}|$)", block, flags=re.S):
        out[m.group(1).strip()] = m.group(2)
    return out


rows = []
with httpx.Client(timeout=30, headers={"User-Agent": "airops-sih-prototype/1.0 (hackathon research)"}, follow_redirects=True) as c:
    for rtype, page, display, role in TYPES:
        for attempt in range(4):
            r = c.get("https://en.wikipedia.org/w/api.php", params={
                "action": "parse", "page": page, "prop": "wikitext", "format": "json", "redirects": 1, "formatversion": 2,
            })
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                break
            print(f"  {page}: HTTP {r.status_code}, retrying")
            time.sleep(8 * (attempt + 1))
        else:
            print("skipped:", page)
            continue
        data = r.json()
        if "error" in data:
            print("missing:", page, data["error"].get("info"))
            continue
        sp = specs(data["parse"]["wikitext"])
        row = {"type_name": display, "airops_type": rtype, "role": role, "wikipedia_article": data["parse"]["title"],
               "source_url": "https://en.wikipedia.org/wiki/" + data["parse"]["title"].replace(" ", "_")}
        for col, key in TEXT_FIELDS.items():
            row[col] = clean(sp.get(key, ""))
        for col, options in NUM_FIELDS.items():
            row[col] = ""
            for key, factor in options:
                n = number(clean(sp.get(key, "")))
                if n:
                    row[col] = round(n * factor)
                    break
        rows.append(row)
        print(f"{display:28} ceiling={row['service_ceiling_m']} range={row['range_km']} cruise={row['cruise_speed_kmh']} crew={row['crew'][:30]}")
        time.sleep(2)

with open(sys.argv[1], "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print("types:", len(rows))
