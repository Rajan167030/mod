"""Fetch current METAR/TAF for every Indian ICAO airfield listed by OurAirports (NOAA Aviation Weather Center API)."""
import csv
import json
import re
import sys
import time

import httpx

airports_csv, out_csv = sys.argv[1], sys.argv[2]
codes = sorted({
    (r["gps_code"] or r["ident"]).upper()
    for r in csv.DictReader(open(airports_csv, encoding="utf-8"))
    if r["iso_country"] == "IN" and r["type"] != "closed" and re.fullmatch(r"V[AEIO][A-Z]{2}", (r["gps_code"] or r["ident"]).upper())
})
print("Indian ICAO codes:", len(codes))

rows = []
with httpx.Client(timeout=30, headers={"User-Agent": "airops-sih-prototype/1.0"}) as c:
    for i in range(0, len(codes), 40):
        batch = codes[i:i + 40]
        r = c.get("https://aviationweather.gov/api/data/metar", params={"ids": ",".join(batch), "format": "json", "taf": "true"})
        if r.status_code == 200 and r.text.strip():
            rows.extend(r.json())
        time.sleep(1)

fields = ["icaoId", "name", "lat", "lon", "elev", "obsTime", "reportTime", "temp", "dewp", "wdir", "wspd", "wgst", "visib", "altim", "fltCat", "rawOb", "rawTaf"]
with open(out_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for row in sorted(rows, key=lambda x: x.get("icaoId", "")):
        w.writerow(row)
print("stations reporting:", len(rows))
for row in rows:
    if row.get("icaoId") in ("VILH", "VISR", "VIJU", "VIDP", "VIBR", "VIGG", "VIAR"):
        print(row.get("icaoId"), row.get("fltCat"), "|", row.get("rawOb"))
