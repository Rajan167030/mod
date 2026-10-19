# India data pack

Real public Indian aviation data, plus synthetic data for what is not public, in the AirOps import format.

Downloaded on **19 Oct 2026**. The planning day in the import files is **20 Oct 2026, 0000Z–2400Z**.
To refresh before a demo, run the scripts in `scripts/` (see the last section).

## What is real and what is synthetic

| Data | Real or synthetic | Source |
|---|---|---|
| Airfields and heliports (623 in India, 18 used in the sector) | **Real** | OurAirports |
| Prohibited, restricted and danger areas (151 in India, 24 in the sector) | **Real** | AAI eAIP India, ENR 5.1 (edition v2-10-2026) |
| METAR and TAF (115 Indian stations) | **Real**, snapshot | NOAA Aviation Weather Center |
| Hourly forecast for the 22 sector sites, 2 days | **Real**, snapshot | Open-Meteo |
| Aircraft type specifications (13 types: service ceiling, range, cruise speed, crew) | **Real**, published figures | Wikipedia `{{Aircraft specs}}` (CC BY-SA 4.0) |
| Aircraft (27 tails) | Synthetic state, **real types and specs** (C-17, Il-76, C-130J, An-32, C-295, Do 228, Chinook, Mi-17V5, ALH Dhruv, Cheetah, LCH Prachand, Apache, ALH Rudra). Callsigns, numbers, availability and fit are invented. | — |
| Maintenance windows | Synthetic | — |
| Crews, duty limits, rest, shifts | Synthetic | — |
| Stores (flares, rockets, ATGM, nets, drop platforms) | Synthetic | — |
| Threats (SAM, MANPADS, radar) | Synthetic, named `SYNTHETIC …`, invented positions | — |
| Missions (34 tasks, NS-01 to NS-34) | Synthetic, flown to the real airfields and heliports | — |

The published service ceiling is used as a rule: an aircraft is never planned to a site higher than its ceiling, and sorties above 80% of it carry extra predicted risk. Daulat Beg Oldi (4,938 m) is 82% of the Mi-17V5's 6,000 m ceiling and 91% of the Cheetah's 5,400 m.

Fleet state, crew rosters, weapon stocks and threat intelligence are classified, so they are not available publicly. In a real deployment they would come from maintenance, rostering and intelligence systems through the same import.

## Folders

```
real/                      full national datasets, for reference and the map
  airfields_india_ourairports.csv
  airspace_enr51_india.csv          polygon = "lat lon; lat lon; …", radius in km for circles
  metar_taf_india_snapshot.csv
  openmeteo_forecast_northern_sites.csv
import_northern_sector/    ready to upload in AirOps → Data import, in this order
  1_sites.csv      → Sites
  2_aircraft.csv   → Aircraft
  3_maintenance.csv→ Maintenance
  4_crews.csv      → Crews
  5_stores.csv     → Stores
  6_tasks.csv      → Tasks
  7_threats_and_airspace.csv → Threats & airspace
scripts/                   the scraper and builder that produced all of the above
```

## Loading it into AirOps

Quickest: from the `backend` folder run `python ../data/india/scripts/load_northern_sector.py` (add `--replace` to rebuild it). It backs up the database, imports all seven files, optimises and approves the first plan.

By hand:

1. **Scenarios** → create a scenario, e.g. "Northern Sector (real airfields)".
2. **Data import** → choose that scenario, then upload the seven files **in the numbered order**. Tasks refer to sites and stores, so those go first. Each file previews first; press Import when there are no errors.
3. **Optimiser** → run with weather on. The plan respects real airspace, synthetic threats, crews and stores.
4. Look at **Ops map**, **Threats & airspace** and **Mission risk**.

This pack was checked by importing all seven files into an empty scenario: every row was valid, the solver assigned 34 of 34 missions, and the independent validator found no conflicts.

The **Theatre map** page shows the national files in `real/` (all airfields, every ENR 5.1 area, live METARs with a fallback to the snapshot) together with any scenario's plan.

## How the real airspace is mapped

| ENR 5.1 type | AirOps rule | Why |
|---|---|---|
| Prohibited (VxP) | No-fly, no entry | Flight is forbidden |
| Danger (VxD), mostly firing ranges | Restricted, no entry | Live firing when active |
| Restricted (VxR), mostly IAF local flying areas | Restricted, avoid | Deconflict from training traffic |

Activity times in ENR 5.1 are mostly "notified by NOTAM", so the zones are imported as always active; the original text is in `real/airspace_enr51_india.csv` under `remarks`. Boundaries that follow an arc are approximated by their listed points (40 of the 151 areas).

## Refreshing the data

From the `backend` folder (it has the Python packages):

```
python ../data/india/scripts/fetch_aircraft_types.py ../data/india/real/aircraft_types_wikipedia.csv
python ../data/india/scripts/fetch_metar.py <airports.csv> <metar_out.csv>
python ../data/india/scripts/parse_enr51.py <enr51.html> <areas_out.csv>
python ../data/india/scripts/build_india.py <download folder> ../data/india
```

`airports.csv` comes from https://davidmegginson.github.io/ourairports-data/airports.csv and the ENR 5.1 page from https://aim-india.aai.aero (current eAIP edition, ENR 5.1). `build_india.py` also calls Open-Meteo.

## Licences and use

- OurAirports: public domain.
- NOAA Aviation Weather Center: US government data, public domain.
- Open-Meteo: CC BY 4.0. Credit "Weather data by Open-Meteo.com".
- Wikipedia: aircraft specifications under CC BY-SA 4.0; each row links its article in `source_url`.
- AAI eAIP: published by the Airports Authority of India. Used here for a training prototype. **Not for navigation**; always use the current AIP and NOTAMs.
