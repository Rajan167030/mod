"""
Build the India data pack: real public data (OurAirports, AAI eAIP ENR 5.1, NOAA METAR/TAF, Open-Meteo)
plus clearly labelled synthetic data for what is not public (fleet state, crews, stores, threats, missions).
Writes CSVs in the AirOps import format. Inputs are files already downloaded into the dl folder.
"""
import csv
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

DL, OUT = Path(sys.argv[1]), Path(sys.argv[2])
REAL, IMPORT = OUT / "real", OUT / "import_northern_sector"
REAL.mkdir(parents=True, exist_ok=True)
IMPORT.mkdir(parents=True, exist_ok=True)
FT = 0.3048


def write(path, rows, fields=None):
    fields = fields or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{path.relative_to(OUT)}: {len(rows)} rows")


# ---------------------------------------------------------------------------
# 1. Real: every open Indian airfield and heliport (OurAirports, public domain)
# ---------------------------------------------------------------------------
airports = [r for r in csv.DictReader(open(DL / "airports.csv", encoding="utf-8")) if r["iso_country"] == "IN" and r["type"] != "closed"]
real_airfields = [{
    "ident": r["ident"], "icao": r["gps_code"] or r["icao_code"], "iata": r["iata_code"], "type": r["type"], "name": r["name"],
    "latitude": r["latitude_deg"], "longitude": r["longitude_deg"],
    "elevation_m": round(float(r["elevation_ft"]) * FT) if r["elevation_ft"] else "",
    "state": r["iso_region"], "municipality": r["municipality"], "scheduled_service": r["scheduled_service"],
} for r in airports]
write(REAL / "airfields_india_ourairports.csv", sorted(real_airfields, key=lambda r: (r["state"], r["name"])))

# ---------------------------------------------------------------------------
# 2. Real: prohibited, restricted and danger areas (AAI eAIP ENR 5.1, parsed earlier)
# ---------------------------------------------------------------------------
areas = list(csv.DictReader(open(DL / "enr51_areas.csv", encoding="utf-8")))
write(REAL / "airspace_enr51_india.csv", areas)

# ---------------------------------------------------------------------------
# 3. Real: METAR/TAF snapshot (NOAA AWC) for Indian stations
# ---------------------------------------------------------------------------
metar = list(csv.DictReader(open(DL / "metar_india.csv", encoding="utf-8")))
write(REAL / "metar_taf_india_snapshot.csv", metar)

# ---------------------------------------------------------------------------
# Northern sector: real sites (J&K, Ladakh, Himachal, Punjab, Chandigarh)
# ---------------------------------------------------------------------------
by_ident = {r["ident"]: r for r in airports}
SITES = [  # (OurAirports ident, AirOps site type, short label used by tasks)
    ("VICG", "LOGISTICS_HUB", "Chandigarh"),
    ("VIAX", "BASE", "Adampur"),
    ("VIPK", "BASE", "Pathankot"),
    ("VIJU", "LOGISTICS_HUB", "Jammu"),
    ("VIUX", "BASE", "Udhampur"),
    ("VISR", "BASE", "Srinagar"),
    ("VIAW", "BASE", "Awantipura"),
    ("VILH", "BASE", "Leh"),
    ("VI57", "BASE", "Thoise"),
    ("VI65", "WAYPOINT", "Kargil"),
    ("IN-0003", "POI", "Daulat Beg Oldi"),
    ("IN-0302", "POI", "Nyoma"),
    ("IN-0279", "POI", "Chushul"),
    ("VI66", "POI", "Fukche"),
    ("IN-0001", "POI", "Siachen Base Camp"),
    ("IN-0388", "POI", "Army Hospital Leh"),
    ("IN-0384", "WAYPOINT", "Sonamarg"),
    ("VIBR", "BASE", "Kullu Manali"),
    ("IN-0282", "POI", "Man"),
    ("IN-0331", "POI", "Khuldo"),
    ("IN-0280", "POI", "Tangtse"),
    ("IN-0330", "POI", "Kaurik"),
]
site_rows, site_name = [], {}
for ident, kind, label in SITES:
    r = by_ident[ident]
    name = r["name"]
    site_name[label] = name
    site_rows.append({
        "name": name, "latitude": r["latitude_deg"], "longitude": r["longitude_deg"], "type": kind,
        "elevation_m": round(float(r["elevation_ft"]) * FT) if r["elevation_ft"] else "",
    })
write(IMPORT / "1_sites.csv", site_rows)

# ---------------------------------------------------------------------------
# Real airspace in the sector, mapped to AirOps rules
# ---------------------------------------------------------------------------
lat0, lat1, lon0, lon1 = 29.8, 36.0, 73.5, 80.5


def inside_box(a):
    if a["geometry"] == "circle":
        pts = [(float(a["center_lat"]), float(a["center_lon"]))]
    else:
        pts = [tuple(map(float, p.split())) for p in a["polygon"].split(";")]
    return any(lat0 <= la <= lat1 and lon0 <= lo <= lon1 for la, lo in pts)


def rule_for(a):
    """Prohibited -> no-fly; danger (firing ranges) -> no entry; IAF local flying areas -> avoid (deconflict)."""
    if a["type"] == "Prohibited":
        return "NO_FLY", "BLOCK"
    if a["type"] == "Danger":
        return "RESTRICTED", "BLOCK"
    return "RESTRICTED", "AVOID"


threat_rows = []
for a in areas:
    if not inside_box(a):
        continue
    kind, effect = rule_for(a)
    name = f"{a['designator']} {a['name'].strip('[] ')}".strip()
    threat_rows.append({
        "name": name[:150], "kind": kind, "effect": effect,
        "latitude": a["center_lat"], "longitude": a["center_lon"], "radius_km": a["radius_km"],
        "polygon": a["polygon"] if a["geometry"] == "polygon" else "",
        "active_from": "", "active_until": "", "exempt_capability": "", "source": "AAI eAIP ENR 5.1", "confidence": 100,
    })
print("real airspace areas in the sector:", len(threat_rows))

# ---------------------------------------------------------------------------
# Synthetic layers (not public): fleet state, crews, stores, threats, missions
# Planning day: tomorrow 0000Z-2400Z, or PLAN_DATE=YYYY-MM-DD
# ---------------------------------------------------------------------------
import os  # noqa: E402

D0 = (datetime.strptime(os.environ["PLAN_DATE"], "%Y-%m-%d").replace(tzinfo=timezone.utc) if os.environ.get("PLAN_DATE")
      else (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))


def z(h):
    return (D0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%MZ")


# Synthetic threats, clearly marked; positions are invented for the exercise
for name, kind, effect, la, lo, rad, h0, h1, exempt, src, conf in [
    ("SYNTHETIC SAM radar, east of Fukche", "SAM", "BLOCK", 32.95, 79.45, 30, 4, 16, "DASS", "ELINT (exercise)", 70),
    ("SYNTHETIC MANPADS teams, Chushul", "MANPADS", "AVOID", 33.56, 78.75, 12, None, None, "", "HUMINT (exercise)", 50),
    ("SYNTHETIC search radar, north of DBO", "RADAR", "AVOID", 35.55, 77.95, 25, 0, 24, "", "ELINT (exercise)", 60),
    ("SYNTHETIC mobile SAM, Nyoma east", "SAM", "BLOCK", 33.12, 78.95, 22, 9, 15, "DASS", "SIGINT (exercise)", 65),
    ("SYNTHETIC AAA belt, Tangtse ridge", "AAA", "AVOID", 34.09, 78.25, 10, 12, 20, "", "IMINT (exercise)", 55),
]:
    threat_rows.append({
        "name": name, "kind": kind, "effect": effect, "latitude": la, "longitude": lo, "radius_km": rad, "polygon": "",
        "active_from": z(h0) if h0 is not None else "", "active_until": z(h1) if h1 is not None else "",
        "exempt_capability": exempt, "source": src, "confidence": conf,
    })
write(IMPORT / "7_threats_and_airspace.csv", threat_rows)

# Published specifications per type, scraped from Wikipedia (fetch_aircraft_types.py)
SPECS = {r["type_name"]: r for r in csv.DictReader(open(OUT / "real" / "aircraft_types_wikipedia.csv", encoding="utf-8"))}

# Fleet: real types in Indian service; callsigns, numbers, fit and state are invented
FLEET = [
    # model (matches SPECS), callsign prefix, count, AirOps type, qualifications, store types
    ("C-17 Globemaster III", "Globemaster", 2, "HEAVY_AIRCRAFT", "SUPER_HEAVY_AIRLIFT;HEAVY_AIRLIFT;NIGHT_OPS;DASS", "FLARE_SET;AIRDROP_PLATFORM"),
    ("Il-76MD Gajraj", "Gajraj", 2, "HEAVY_AIRCRAFT", "SUPER_HEAVY_AIRLIFT;HEAVY_AIRLIFT", "FLARE_SET;AIRDROP_PLATFORM"),
    ("C-130J-30 Super Hercules", "Hercules", 3, "HEAVY_AIRCRAFT", "HEAVY_AIRLIFT;NIGHT_OPS;HIGH_ALTITUDE_STRIP;DASS", "FLARE_SET;AIRDROP_PLATFORM"),
    ("An-32RE", "Sutlej", 3, "TRANSPORT_AIRCRAFT", "MEDIUM_AIRLIFT;HIGH_ALTITUDE_STRIP", "FLARE_SET"),
    ("C-295MW", "Avro-NG", 1, "TRANSPORT_AIRCRAFT", "MEDIUM_AIRLIFT;NIGHT_OPS", "FLARE_SET"),
    ("Do 228", "Dornier", 1, "TRANSPORT_AIRCRAFT", "LIGHT_AIRLIFT;FORWARD_RECON", ""),
    ("CH-47F(I) Chinook", "Chinook", 2, "HEAVY_HELICOPTER", "HEAVY_LIFT_HELI;HIGH_ALTITUDE;NIGHT_OPS;DASS", "FLARE_SET;UNDERSLUNG_NET"),
    ("Mi-17V5", "Mi17V5", 4, "TACTICAL_HELICOPTER", "HIGH_ALTITUDE;MEDEVAC;SEARCH_RESCUE", "FLARE_SET;UNDERSLUNG_NET;MEDEVAC_KIT"),
    ("ALH Dhruv", "Dhruv", 3, "LIGHT_HELICOPTER", "FORWARD_RECON;QUICK_MEDEVAC;HIGH_ALTITUDE", "FLARE_SET;MEDEVAC_KIT"),
    ("Cheetah (SA 315B Lama)", "Cheetah", 2, "LIGHT_HELICOPTER", "EXTREME_ALTITUDE;QUICK_MEDEVAC", "MEDEVAC_KIT"),
    ("LCH Prachand", "Prachand", 2, "ATTACK_HELICOPTER", "ARMED_ESCORT;HIGH_ALTITUDE;DASS", "FLARE_SET;ROCKET_POD;ATGM"),
    ("AH-64E Apache", "Apache", 1, "ATTACK_HELICOPTER", "ARMED_ESCORT;NIGHT_OPS;DASS", "FLARE_SET;ROCKET_POD;ATGM"),
    ("ALH Rudra", "Rudra", 1, "ATTACK_HELICOPTER", "ARMED_ESCORT;HIGH_ALTITUDE", "FLARE_SET;ROCKET_POD"),
]
# Extra fit on single tails, so not every aircraft of a type is identical
EXTRA = {"Mi17V5-01": "NIGHT_OPS;DASS", "Mi17V5-02": "NIGHT_OPS", "Dhruv-01": "NIGHT_OPS"}
PAYLOAD = {"C-17 Globemaster III": 77500, "Il-76MD Gajraj": 47000, "C-130J-30 Super Hercules": 20000, "An-32RE": 6700,
           "C-295MW": 9250, "Do 228": 2340, "CH-47F(I) Chinook": 11000, "Mi-17V5": 4000, "ALH Dhruv": 1500,
           "Cheetah (SA 315B Lama)": 500, "LCH Prachand": 1200, "AH-64E Apache": 1500, "ALH Rudra": 1200}

aircraft_rows = []
for model, prefix, count, rtype, quals, stores in FLEET:
    s = SPECS.get(model, {})
    for n in range(1, count + 1):
        name = f"{prefix}-{n:02d}"
        q = ";".join(filter(None, [quals, EXTRA.get(name, "")]))
        aircraft_rows.append({
            "name": name, "type": rtype, "qualifications": q, "max_payload_kg": PAYLOAD[model], "status": "AVAILABLE",
            "store_types": stores, "model": model, "service_ceiling_m": s.get("service_ceiling_m", ""),
            "range_km": s.get("range_km", ""), "cruise_speed_kmh": s.get("cruise_speed_kmh", ""),
        })
write(IMPORT / "2_aircraft.csv", aircraft_rows)

write(IMPORT / "3_maintenance.csv", [
    {"aircraft": "Hercules-02", "start": z(6), "end": z(11)},
    {"aircraft": "Mi17V5-03", "start": z(13), "end": z(18)},
    {"aircraft": "Gajraj-01", "start": z(0), "end": z(3)},
    {"aircraft": "Sutlej-03", "start": z(8), "end": z(20)},
    {"aircraft": "Dhruv-03", "start": z(0), "end": z(6)},
    {"aircraft": "Chinook-02", "start": z(14), "end": z(19)},
])

CREWS = [
    # name, types, max duty, min rest, already flown, shift (start h, end h) or None
    ("Globemaster crew A", "HEAVY_AIRCRAFT", 600, 90, 0, None),
    ("Globemaster crew B", "HEAVY_AIRCRAFT", 600, 90, 0, (12, 26)),
    ("Gajraj crew A", "HEAVY_AIRCRAFT", 600, 90, 120, None),
    ("Hercules crew A", "HEAVY_AIRCRAFT", 480, 60, 0, None),
    ("Hercules crew B", "HEAVY_AIRCRAFT", 480, 60, 0, (12, 26)),
    ("Hercules crew C", "HEAVY_AIRCRAFT", 480, 60, 240, None),
    ("An-32 crew A", "TRANSPORT_AIRCRAFT", 480, 60, 0, None),
    ("An-32 crew B", "TRANSPORT_AIRCRAFT", 480, 60, 180, None),
    ("C-295 crew A", "TRANSPORT_AIRCRAFT", 480, 60, 0, None),
    ("Dornier crew A", "TRANSPORT_AIRCRAFT", 420, 45, 0, None),
    ("Chinook crew A", "HEAVY_HELICOPTER", 420, 60, 0, None),
    ("Chinook crew B", "HEAVY_HELICOPTER", 420, 60, 120, (6, 20)),
    ("Mi-17 crew A", "TACTICAL_HELICOPTER", 420, 45, 0, None),
    ("Mi-17 crew B", "TACTICAL_HELICOPTER", 420, 45, 0, None),
    ("Mi-17 crew C (night)", "TACTICAL_HELICOPTER", 420, 45, 0, (14, 26)),
    ("Mi-17 crew D", "TACTICAL_HELICOPTER", 420, 45, 300, None),
    ("ALH crew A", "LIGHT_HELICOPTER;ATTACK_HELICOPTER", 360, 45, 0, None),
    ("ALH crew B", "LIGHT_HELICOPTER", 360, 45, 60, None),
    ("ALH crew C", "LIGHT_HELICOPTER", 360, 45, 0, (10, 22)),
    ("Cheetah crew A", "LIGHT_HELICOPTER", 300, 45, 0, None),
    ("Cheetah crew B", "LIGHT_HELICOPTER", 300, 45, 120, None),
    ("Attack crew A", "ATTACK_HELICOPTER", 360, 45, 0, None),
    ("Attack crew B", "ATTACK_HELICOPTER", 360, 45, 0, (8, 22)),
    ("Apache crew A", "ATTACK_HELICOPTER", 360, 45, 0, None),
]
write(IMPORT / "4_crews.csv", [
    {"name": n, "aircraft_types": t, "status": "AVAILABLE", "max_duty_minutes": d, "min_rest_minutes": r,
     "duty_used_minutes": u, "duty_start": z(s[0]) if s else "", "duty_end": z(s[1]) if s else ""}
    for n, t, d, r, u, s in CREWS
])

write(IMPORT / "5_stores.csv", [
    {"store_type": "FLARE_SET", "name": "Flare/chaff dispenser load", "category": "COUNTERMEASURE", "quantity": 14, "unit": "sets"},
    {"store_type": "ROCKET_POD", "name": "70 mm rocket pod", "category": "WEAPON", "quantity": 8, "unit": "pods"},
    {"store_type": "ATGM", "name": "Anti-tank guided missile (Helina class)", "category": "WEAPON", "quantity": 6, "unit": "missiles"},
    {"store_type": "UNDERSLUNG_NET", "name": "Underslung cargo net", "category": "MISSION_KIT", "quantity": 4, "unit": "nets"},
    {"store_type": "AIRDROP_PLATFORM", "name": "Heavy drop platform", "category": "MISSION_KIT", "quantity": 5, "unit": "platforms"},
    {"store_type": "MEDEVAC_KIT", "name": "Stretcher and oxygen kit", "category": "MISSION_KIT", "quantity": 6, "unit": "kits"},
])

TASKS = [
    # code, title, site label, priority, minutes, open h, close h, qualification, stores
    ("NS-01", "Troop rotation Chandigarh to Leh", "Leh", "HIGH", 180, 1, 8, "SUPER_HEAVY_AIRLIFT", ""),
    ("NS-02", "Winter stocking lift to Thoise", "Thoise", "HIGH", 210, 2, 12, "SUPER_HEAVY_AIRLIFT", ""),
    ("NS-03", "Ammunition resupply, Daulat Beg Oldi", "Daulat Beg Oldi", "CRITICAL", 150, 3, 9, "HIGH_ALTITUDE_STRIP", "FLARE_SET"),
    ("NS-04", "Fuel lift to Nyoma", "Nyoma", "HIGH", 150, 4, 12, "HIGH_ALTITUDE_STRIP", "FLARE_SET"),
    ("NS-05", "Casualty evacuation, Siachen Base Camp", "Siachen Base Camp", "CRITICAL", 90, 2, 6, "EXTREME_ALTITUDE", "MEDEVAC_KIT"),
    ("NS-06", "Casualty transfer Kargil to Army Hospital Leh", "Army Hospital Leh", "CRITICAL", 90, 5, 9, "MEDEVAC", "MEDEVAC_KIT"),
    ("NS-07", "Bridge sections underslung to Chushul", "Chushul", "HIGH", 120, 6, 14, "HEAVY_LIFT_HELI", "UNDERSLUNG_NET;FLARE_SET"),
    ("NS-08", "Armed escort, Chushul convoy", "Chushul", "HIGH", 90, 7, 13, "ARMED_ESCORT", "ROCKET_POD:2;FLARE_SET"),
    ("NS-09", "Overwatch, Fukche ALG", "Fukche", "MEDIUM", 120, 8, 18, "ARMED_ESCORT", "ATGM:2;FLARE_SET"),
    ("NS-10", "Route recce, Zoji La approach", "Sonamarg", "MEDIUM", 90, 4, 10, "FORWARD_RECON", ""),
    ("NS-11", "Night resupply, Leh", "Leh", "HIGH", 150, 15, 22, "NIGHT_OPS", ""),
    ("NS-12", "Search and rescue sweep, Zoji La", "Sonamarg", "HIGH", 120, 6, 12, "SEARCH_RESCUE", ""),
    ("NS-13", "Medical stores airdrop, Kargil", "Kargil", "HIGH", 120, 9, 16, "HEAVY_AIRLIFT", "AIRDROP_PLATFORM"),
    ("NS-14", "Engineer plant to Srinagar", "Srinagar", "MEDIUM", 150, 8, 18, "HEAVY_AIRLIFT", ""),
    ("NS-15", "Spares shuttle Jammu to Udhampur", "Udhampur", "LOW", 90, 6, 20, "MEDIUM_AIRLIFT", ""),
    ("NS-16", "Mail and rations to Kargil", "Kargil", "LOW", 120, 10, 20, "MEDIUM_AIRLIFT", ""),
    ("NS-17", "Doctor insertion, Nyoma", "Nyoma", "CRITICAL", 60, 3, 7, "QUICK_MEDEVAC", "MEDEVAC_KIT"),
    ("NS-18", "Night casualty standby, Thoise", "Thoise", "HIGH", 90, 16, 23, "NIGHT_OPS", ""),
    ("NS-19", "Avalanche survey, Kullu valley", "Kullu Manali", "LOW", 90, 7, 15, "FORWARD_RECON", ""),
    ("NS-20", "Heavy drop, Daulat Beg Oldi", "Daulat Beg Oldi", "HIGH", 180, 10, 20, "SUPER_HEAVY_AIRLIFT", "AIRDROP_PLATFORM;FLARE_SET"),
    ("NS-21", "Generator lift to Fukche", "Fukche", "MEDIUM", 120, 12, 22, "HEAVY_LIFT_HELI", "UNDERSLUNG_NET;FLARE_SET"),
    ("NS-22", "Re-supply Awantipura", "Awantipura", "LOW", 120, 4, 20, "HEAVY_AIRLIFT", ""),
    ("NS-23", "Snow clearance team to Man", "Man", "HIGH", 90, 5, 12, "HIGH_ALTITUDE", "FLARE_SET"),
    ("NS-24", "Casualty evacuation, Khuldo", "Khuldo", "CRITICAL", 75, 8, 12, "MEDEVAC", "MEDEVAC_KIT;FLARE_SET"),
    ("NS-25", "Signal relay install, Tangtse", "Tangtse", "MEDIUM", 120, 6, 16, "HIGH_ALTITUDE", ""),
    ("NS-26", "Border road survey, Kaurik", "Kaurik", "LOW", 90, 7, 17, "FORWARD_RECON", ""),
    ("NS-27", "Armed overwatch, Tangtse convoy", "Tangtse", "HIGH", 90, 13, 19, "ARMED_ESCORT", "ROCKET_POD:2;FLARE_SET"),
    ("NS-28", "Personnel shuttle Chandigarh to Kullu", "Kullu Manali", "LOW", 60, 9, 18, "LIGHT_AIRLIFT", ""),
    ("NS-29", "Fuel bowser lift to Thoise", "Thoise", "MEDIUM", 150, 12, 22, "HEAVY_AIRLIFT", ""),
    ("NS-30", "Night insertion, Chushul", "Chushul", "HIGH", 90, 17, 23, "NIGHT_OPS", "FLARE_SET"),
    ("NS-31", "Ration airdrop, Man", "Man", "MEDIUM", 120, 10, 18, "HEAVY_AIRLIFT", "AIRDROP_PLATFORM;FLARE_SET"),
    ("NS-32", "Spares to Pathankot", "Pathankot", "LOW", 90, 2, 14, "MEDIUM_AIRLIFT", ""),
    ("NS-33", "Anti-armour standby, Fukche", "Fukche", "HIGH", 120, 16, 23, "ARMED_ESCORT", "ATGM:2;FLARE_SET"),
    ("NS-34", "Recce of Siachen approaches", "Siachen Base Camp", "MEDIUM", 90, 9, 15, "EXTREME_ALTITUDE", ""),
]
write(IMPORT / "6_tasks.csv", [
    {"name": f"{c} {t}", "priority": p, "duration_minutes": m, "earliest_start": z(a), "latest_finish": z(b),
     "qualification": q, "site": site_name[s], "stores": st}
    for c, t, s, p, m, a, b, q, st in TASKS
])

# ---------------------------------------------------------------------------
# 4. Real: Open-Meteo hourly forecast snapshot for the sector sites (CC BY 4.0)
# ---------------------------------------------------------------------------
lats = ",".join(str(r["latitude"]) for r in site_rows)
lons = ",".join(str(r["longitude"]) for r in site_rows)
resp = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=60, params={
    "latitude": lats, "longitude": lons, "forecast_days": 2, "timezone": "UTC",
    "hourly": "temperature_2m,wind_speed_10m,wind_gusts_10m,visibility,cloud_cover,precipitation,weather_code",
})
resp.raise_for_status()
wx = []
for site, block in zip(site_rows, resp.json()):
    h = block["hourly"]
    for i, t in enumerate(h["time"]):
        wx.append({"site": site["name"], "time_utc": t + "Z", **{k: h[k][i] for k in h if k != "time"}})
write(REAL / "openmeteo_forecast_northern_sites.csv", wx)
print("planning day:", D0.date())
