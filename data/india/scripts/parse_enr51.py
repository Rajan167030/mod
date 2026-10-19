"""Parse AAI eAIP ENR 5.1 (prohibited, restricted and danger areas) into rows. Reads a saved HTML file."""
import csv
import html
import re
import sys
from collections import Counter

src, out = sys.argv[1], sys.argv[2]
raw = open(src, encoding="utf-8", errors="replace").read()
text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))).replace("﻿", "").replace("�", " ")

# Designators: V + FIR letter (A Mumbai, E Kolkata, I Delhi, O Chennai) + P/R/D + number (+ optional letter)
DESIG = re.compile(r"\b(V[AEIO][PRD])\s?-?\s?(\d{1,4})(?:\s?-?\s?\(?([A-Z])\)?(?![a-z]))?(?=[\s\[])")
COORD = re.compile(r"(\d{2})(\d{2})(\d{2}(?:\.\d+)?)\s?([NS])\s*(\d{3})(\d{2})(\d{2}(?:\.\d+)?)\s?([EW])")
RADIUS = re.compile(r"radius\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*(NM|KM|nm|km)", re.I)
FIRS = {"A": "Mumbai", "E": "Kolkata", "I": "Delhi", "O": "Chennai"}
KIND = {"P": "Prohibited", "R": "Restricted", "D": "Danger"}


def dms(d, m, s, h):
    v = int(d) + int(m) / 60 + float(s) / 3600
    return -v if h in "SW" else v


matches = list(DESIG.finditer(text))
rows = []
for i, m in enumerate(matches):
    body = text[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip()
    if len(body) < 15 or not COORD.search(body) or body.lower().startswith("intentionally left blank"):
        continue  # a cross-reference, not an area definition
    ident = f"{m.group(1)} {m.group(2)}{(' ' + m.group(3)) if m.group(3) else ''}"
    # Name: words before the geometry description
    name = re.split(r"\b(Area|Circular|Circle|A circle|Sector|1\.|bounded|\d{6})", body, maxsplit=1)[0].strip(" -:;,")[:80]
    pts = [(round(dms(*c.groups()[:3], c.group(4)), 5), round(dms(*c.groups()[4:7], c.group(8)), 5)) for c in COORD.finditer(body)]
    rad = RADIUS.search(body)
    geom_end = body.find(" FT") if " FT" in body else len(body)
    is_circle = bool(rad) and len([p for p in COORD.finditer(body[:geom_end])]) == 1
    limits = re.search(r"((?:\d[\d,]*\s*FT(?:\s*AMSL)?|FL\s*\d+|UNL)\s*/\s*(?:GND|MSL|SFC|\d[\d,]*\s*FT(?:\s*AMSL)?))", body)
    remarks = body[limits.end():] if limits else ""
    remarks = re.sub(r"^[\s\W]+", "", remarks)[:300].strip()
    row = {
        "designator": ident,
        "type": KIND[m.group(1)[2]],
        "fir": FIRS[m.group(1)[1]],
        "name": name or ident,
        "geometry": "circle" if is_circle else "polygon",
        "center_lat": pts[0][0] if is_circle else "",
        "center_lon": pts[0][1] if is_circle else "",
        "radius_km": round(float(rad.group(1)) * (1.852 if rad.group(2).upper() == "NM" else 1), 2) if is_circle else "",
        "polygon": "" if is_circle else ";".join(f"{a} {b}" for a, b in pts[:60]),
        "points": len(pts),
        "has_arcs": "yes" if (not is_circle and "arc" in body.lower()) else "",
        "vertical_limits": limits.group(1) if limits else "",
        "remarks": remarks,
    }
    if row["geometry"] == "polygon" and len(pts) < 3:
        continue
    rows.append(row)

with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print("areas:", len(rows), Counter((r["fir"], r["type"]) for r in rows))
print("arcs approximated by vertices:", sum(r["has_arcs"] == "yes" for r in rows))
for r in rows:
    if r["fir"] == "Delhi":
        print(r["designator"], "|", r["name"][:40], "|", r["geometry"], r["points"], "|", r["remarks"][:70])
