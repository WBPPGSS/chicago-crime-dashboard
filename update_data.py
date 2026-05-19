#!/usr/bin/env python3
"""
Daily updater for the Chicago Crime Dashboard.
Queries Chicago Data Portal for Districts 001 and 018, rebuilds DATA and MAP_POINTS,
then writes the result back into index.html using marker comments.

Run manually:  python3 update_data.py
GitHub Actions runs this automatically every day at 06:00 UTC.
"""

import json, re, math, sys
from datetime import date, datetime
from urllib.request import urlopen
from urllib.error import URLError
from urllib.parse import urlencode
from collections import defaultdict

HTML_FILE = "index.html"
API_BASE  = "https://data.cityofchicago.org/resource/ijzp-q8t2.json"
DISTRICTS = ["001", "018"]
START_YEAR = 2020

# ---- helpers ----------------------------------------------------------------

def fetch_json(url):
    with urlopen(url, timeout=30) as r:
        return json.loads(r.read())

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

MART = (41.8884, -87.6355)

# ---- fetch DATA (aggregated by year / district / primary_type / iucr) ------

def build_data():
    data = {}
    current_year = date.today().year

    for year in range(START_YEAR, current_year + 1):
        data[str(year)] = {}
        for district in DISTRICTS:
            params = {
                "$select": "primary_type,iucr,description,count(case_number) as cnt",
                "$where": f"year={year} AND district='{district}'",
                "$group": "primary_type,iucr,description",
                "$limit": "5000",
            }
            url = API_BASE + "?" + urlencode(params)
            try:
                rows = fetch_json(url)
            except URLError as e:
                print(f"  WARN: fetch failed for {year}/{district}: {e}", file=sys.stderr)
                rows = []

            # Build structure: {offense: {total, iucrs:[{iucr,desc,count}]}}
            offenses = defaultdict(lambda: {"total": 0, "iucrs": []})
            for row in rows:
                ptype = row["primary_type"]
                cnt   = int(row["cnt"])
                offenses[ptype]["total"] += cnt
                offenses[ptype]["iucrs"].append({
                    "iucr":  row["iucr"],
                    "desc":  row["description"],
                    "count": cnt,
                })
            data[str(year)][district] = {k: v for k, v in offenses.items()}

    return data

# ---- fetch MAP_POINTS (violent crimes with lat/lon) -------------------------

VIOLENT_TYPES = {
    "HOMICIDE", "CRIMINAL SEXUAL ASSAULT", "ROBBERY", "ASSAULT",
    "BATTERY", "BURGLARY", "ARSON", "WEAPONS VIOLATION",
}

def build_map_points():
    pts = []
    current_year = date.today().year

    for year in range(2022, current_year + 1):
        for district in DISTRICTS:
            params = {
                "$where": (
                    f"year={year} AND district='{district}' "
                    "AND latitude IS NOT NULL "
                    "AND primary_type IN ("
                    + ",".join(f"'{t}'" for t in VIOLENT_TYPES)
                    + ")"
                ),
                "$select": "id,date,year,primary_type,district,latitude,longitude",
                "$limit": "5000",
                "$order": "date DESC",
            }
            url = API_BASE + "?" + urlencode(params)
            try:
                rows = fetch_json(url)
            except URLError as e:
                print(f"  WARN: fetch failed for MAP_POINTS {year}/{district}: {e}", file=sys.stderr)
                rows = []

            for row in rows:
                try:
                    lat = float(row["latitude"])
                    lon = float(row["longitude"])
                    dist_m = haversine(lat, lon, *MART)
                    pts.append({
                        "id":       row["id"],
                        "date":     row["date"],
                        "year":     str(row["year"]),
                        "offense":  row["primary_type"],
                        "district": row["district"],
                        "lat":      round(lat, 6),
                        "lon":      round(lon, 6),
                        "dist_m":   round(dist_m),
                    })
                except (KeyError, ValueError):
                    pass

    return pts

# ---- patch HTML -------------------------------------------------------------

def patch_html(data, pts):
    today = date.today().isoformat()

    html = open(HTML_FILE, encoding="utf-8").read()

    data_json = json.dumps(data, separators=(",", ":"))
    pts_json  = json.dumps(pts,  separators=(",", ":"))

    html = re.sub(
        r"/\*DATA_START\*/.+?/\*DATA_END\*/",
        f"/*DATA_START*/{data_json}/*DATA_END*/",
        html, flags=re.DOTALL,
    )
    html = re.sub(
        r"/\*POINTS_START\*/.+?/\*POINTS_END\*/",
        f"/*POINTS_START*/{pts_json}/*POINTS_END*/",
        html, flags=re.DOTALL,
    )
    html = re.sub(
        r"/\*DATE_START\*/.+?/\*DATE_END\*/",
        f'/*DATE_START*/"{today}"/*DATE_END*/',
        html,
    )

    open(HTML_FILE, "w", encoding="utf-8").write(html)
    print(f"Patched {HTML_FILE} — {len(data)} years · {len(pts)} map points · updated {today}")

# ---- main -------------------------------------------------------------------

if __name__ == "__main__":
    print("Fetching DATA …")
    data = build_data()
    print("Fetching MAP_POINTS …")
    pts  = build_map_points()
    patch_html(data, pts)
