"""Checks the PostGIS schema and feature SQL against a tiny hand-made dataset.

Run it inside the app container (make smoke). It creates a throwaway database, loads three
counties, four substations, three lines and a few queue rows, builds site_features, and
compares every value with an independent calculation made with shapely and pyproj.
"""
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from pyproj import Geod
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points

from ranker.config import load_settings

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
if not SQL_DIR.exists():
    SQL_DIR = Path("/app/sql")
SMOKE_DB = "ranker_smoke"
GEOD = Geod(ellps="WGS84")

COUNTIES = [  # geoid, name, name_norm, (west, south, east, north)
    ("99001", "Alpha", "alpha", (-112.2, 32.8, -111.8, 33.2)),
    ("99002", "Beta", "beta", (-111.8, 32.8, -111.4, 33.2)),
]
SUBSTATIONS = [  # id, kv, lon, lat. s4 sits outside both counties and must be dropped.
    ("s1", 345.0, -112.0, 33.0), ("s2", 138.0, -111.6, 33.0),
    ("s3", 69.0, -111.9, 33.1), ("s4", 500.0, -110.0, 33.0),
]
LINES = {  # id: (kv, [(lon, lat), ...])
    "l1": (345.0, [(-112.0, 33.02), (-111.9, 33.02)]),
    "l2": (230.0, [(-111.6, 33.05), (-111.5, 33.05)]),
    "l3": (138.0, [(-112.05, 32.98), (-112.0, 32.98)]),
}
QUEUE = [  # county_norm, status, tech, mw
    ("alpha", "active", "solar", 500), ("alpha", "active", "storage", 100), ("alpha", "withdrawn", "wind", 300),
    ("beta", "active", "solar", 50), ("beta", "active", "gas", 2000),
]


def geodesic_km(lon1, lat1, lon2, lat2) -> float:
    return GEOD.inv(lon1, lat1, lon2, lat2)[2] / 1000.0


def expected_features() -> dict:
    """Independent expected values for each substation that should survive the county join."""
    results = {}
    for site_id, kv, lon, lat in SUBSTATIONS:
        if site_id == "s4":
            continue
        point = Point(lon, lat)
        nearest_hv = None
        lines_nearby = 0
        for line_id, (line_kv, coords) in LINES.items():
            line = LineString(coords)
            on_line = nearest_points(point, line)[1]
            distance = geodesic_km(lon, lat, on_line.x, on_line.y)
            if line_kv >= 230 and (nearest_hv is None or distance < nearest_hv):
                nearest_hv = distance
            if line_kv >= 115 and distance <= 10.0:
                lines_nearby += 1
        results[site_id] = {"dist_hv_line_km": nearest_hv, "lines_within_10km": lines_nearby}
    return results


def main() -> int:
    settings = load_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {SMOKE_DB}")
        admin.execute(f"CREATE DATABASE {SMOKE_DB}")
    smoke_url = settings.database_url.rsplit("/", 1)[0] + f"/{SMOKE_DB}"

    failures = []
    with psycopg.connect(smoke_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute((SQL_DIR / "schema.sql").read_text())
            for geoid, name, name_norm, (west, south, east, north) in COUNTIES:
                wkt = f"MULTIPOLYGON((({west} {south}, {west} {north}, {east} {north}, {east} {south}, {west} {south})))"
                cursor.execute(
                    "INSERT INTO counties VALUES (%s, %s, %s, '99', ST_GeomFromText(%s, 4326))",
                    (geoid, name, name_norm, wkt))
            for site_id, kv, lon, lat in SUBSTATIONS:
                cursor.execute(
                    "INSERT INTO substations VALUES (%s, %s, 'test', %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
                    (site_id, site_id, kv, lon, lat))
            for line_id, (kv, coords) in LINES.items():
                text = ", ".join(f"{lon} {lat}" for lon, lat in coords)
                cursor.execute("INSERT INTO lines VALUES (%s, %s, ST_GeomFromText(%s, 4326))",
                               (line_id, kv, f"LINESTRING({text})"))
            cursor.executemany(
                "INSERT INTO queue_projects (county_norm, status, tech, mw) VALUES (%s, %s, %s, %s)", QUEUE)
            cursor.execute((SQL_DIR / "features.sql").read_text())
            cursor.execute("SELECT * FROM site_features ORDER BY id")
            rows = {row["id"]: row for row in cursor.fetchall()}

    def check(label, ok):
        print(("PASS " if ok else "FAIL ") + label)
        if not ok:
            failures.append(label)

    check("substation outside every county is dropped", set(rows) == {"s1", "s2", "s3"})
    for site_id, expected in expected_features().items():
        row = rows.get(site_id)
        if row is None:
            continue
        distance_ok = abs(row["dist_hv_line_km"] - expected["dist_hv_line_km"]) <= 0.03 * expected["dist_hv_line_km"]
        check(f"{site_id} distance to 230 kV+ line {row['dist_hv_line_km']:.2f} km "
              f"(expected {expected['dist_hv_line_km']:.2f})", distance_ok)
        check(f"{site_id} lines within 10 km = {row['lines_within_10km']} (expected {expected['lines_within_10km']})",
              row["lines_within_10km"] == expected["lines_within_10km"])
    if "s1" in rows:
        s1 = rows["s1"]
        check("alpha renewable queue MW is 500", s1["renewable_queue_mw"] == 500)
        check("alpha storage queue MW is 100", s1["storage_queue_mw"] == 100)
        check("alpha withdrawn share is 300/900", abs(s1["withdrawn_share"] - 300 / 900) < 1e-6)
        check("county name carried through", s1["county"] == "Alpha")
    if "s2" in rows:
        check("beta storage queue MW is 0", rows["s2"]["storage_queue_mw"] == 0)
        check("beta withdrawn share is 0", rows["s2"]["withdrawn_share"] == 0)

    with psycopg.connect(settings.database_url, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {SMOKE_DB}")
    print("\nAll checks passed." if not failures else f"\n{len(failures)} check(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
