"""Load substations and transmission lines from OpenStreetMap through the Overpass API.

The state is split into tiles so each request stays small enough for the public servers.
"""
import re
import time

import httpx

from ..config import Settings

SUBSTATION_QUERY = """
[out:json][timeout:90][maxsize:268435456];
nwr["power"="substation"]["voltage"~"^[0-9]{{5,}}"]({south},{west},{north},{east});
out center tags;
"""

# Voltage tags are in volts. Six or more leading digits means 100 kV and up.
LINE_QUERY = """
[out:json][timeout:90][maxsize:268435456];
way["power"="line"]["voltage"~"^[1-9][0-9]{{5}}"]({south},{west},{north},{east});
out geom tags;
"""


def parse_max_kv(voltage_tag: str | None) -> float | None:
    """Highest voltage in an OSM voltage tag, in kV.

    OSM stores volts, sometimes several separated by semicolons ("345000;138000").
    Values outside 1 kV to 1500 kV are treated as bad data.
    """
    if not voltage_tag:
        return None
    best = None
    for part in re.split(r"[;,]", voltage_tag):
        digits = re.sub(r"[^0-9.]", "", part)
        if not digits:
            continue
        try:
            volts = float(digits)
        except ValueError:
            continue
        kv = volts / 1000.0 if volts >= 1000 else volts  # tolerate tags already written in kV
        if 1 <= kv <= 1500 and (best is None or kv > best):
            best = kv
    return best


def make_tiles(south: float, west: float, north: float, east: float, count: int) -> list:
    """Split a bounding box into count x count tiles of (south, west, north, east)."""
    lat_step = (north - south) / count
    lon_step = (east - west) / count
    tiles = []
    for row in range(count):
        for column in range(count):
            tiles.append((
                south + row * lat_step, west + column * lon_step,
                south + (row + 1) * lat_step, west + (column + 1) * lon_step,
            ))
    return tiles


def element_to_substation(element: dict, min_kv: float) -> tuple | None:
    """(osm_id, name, operator, max_kv, lon, lat) or None if it does not qualify."""
    tags = element.get("tags", {})
    max_kv = parse_max_kv(tags.get("voltage"))
    if max_kv is None or max_kv < min_kv:
        return None
    # Nodes carry lat/lon directly; ways and relations carry a computed centre.
    point = element if "lat" in element else element.get("center")
    if not point:
        return None
    osm_id = f"{element['type']}/{element['id']}"
    return osm_id, tags.get("name"), tags.get("operator"), max_kv, point["lon"], point["lat"]


def element_to_line(element: dict, min_kv: float) -> tuple | None:
    """(osm_id, max_kv, wkt) or None if it does not qualify."""
    tags = element.get("tags", {})
    max_kv = parse_max_kv(tags.get("voltage"))
    geometry = element.get("geometry") or []
    if max_kv is None or max_kv < min_kv or len(geometry) < 2:
        return None
    coordinates = ", ".join(f"{node['lon']} {node['lat']}" for node in geometry)
    return f"way/{element['id']}", max_kv, f"LINESTRING({coordinates})"


# Overpass servers reject the default python client User-Agent with 406, so identify the project.
OVERPASS_HEADERS = {
    "User-Agent": "battery-site-ranker/0.1 (portfolio project; github.com/sarvagna23)",
    "Accept": "*/*",
}


def run_overpass(query: str, urls: tuple, attempts: int = 3) -> list:
    """Send a query, trying each server and backing off between failures."""
    last_error = None
    for attempt in range(attempts):
        for url in urls:
            try:
                response = httpx.post(url, data={"data": query}, headers=OVERPASS_HEADERS, timeout=240)
                response.raise_for_status()
                payload = response.json()
                # Overpass answers HTTP 200 with a "remark" when a query timed out or ran out of memory,
                # and the elements are then partial or empty. Treat that as a failure, not as an empty tile.
                remark = str(payload.get("remark", ""))
                if "runtime error" in remark.lower():
                    raise ValueError(remark)
                return payload.get("elements", [])
            except (httpx.HTTPError, ValueError) as error:
                last_error = error
                body = getattr(getattr(error, "response", None), "text", "")[:200]
                print(f"  Overpass problem at {url}: {error} {body}")
        time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Overpass failed after {attempts} rounds: {last_error}")


def fetch_or_skip(query: str, urls: tuple, label: str, failed: list):
    """Run one tile query. Returns None (and records the label) if it keeps failing, so the run continues."""
    try:
        return run_overpass(query, urls)
    except RuntimeError as error:
        print(f"  SKIPPED {label}: {error}")
        failed.append(label)
        return None


def tile_done(connection, key: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM osm_tiles_done WHERE tile_key = %s", (key,))
        return cursor.fetchone() is not None


def mark_tile_done(connection, key: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO osm_tiles_done (tile_key) VALUES (%s) ON CONFLICT DO NOTHING", (key,))


def state_bbox(connection, state_fips: str) -> tuple:
    """Bounding box (south, west, north, east) of the state's counties."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ST_YMin(e) AS south, ST_XMin(e) AS west, ST_YMax(e) AS north, ST_XMax(e) AS east
            FROM (SELECT ST_Extent(geom) AS e FROM counties WHERE state_fips = %s) AS extent
            """,
            (state_fips,),
        )
        row = cursor.fetchone()
    if row is None or row["south"] is None:
        raise RuntimeError("Load counties first: python -m ranker.ingest counties")
    return row["south"], row["west"], row["north"], row["east"]


def load_tile(connection, settings: Settings, kind: str, number: int, query: str, failed: list) -> int:
    """Fetch one tile query and upsert its rows. Tiles that already succeeded are skipped.

    Returns the number of rows written. A failed fetch is recorded in `failed` and not marked done,
    so the next run retries exactly that tile.
    """
    key = f"{settings.state_fips}:{settings.overpass_tiles}:{kind}:{number}"
    if tile_done(connection, key):
        print(f"  {kind} already loaded, skipping")
        return 0
    elements = fetch_or_skip(query, settings.overpass_urls, f"tile {number} {kind}", failed)
    if elements is None:
        return 0
    written = 0
    with connection.cursor() as cursor:
        for element in elements:
            if kind == "substations":
                row = element_to_substation(element, settings.min_substation_kv)
                if row is None:
                    continue
                osm_id, name, operator, max_kv, lon, lat = row
                cursor.execute(
                    """
                    INSERT INTO substations (osm_id, name, operator, max_kv, geom)
                    VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
                    ON CONFLICT (osm_id) DO UPDATE
                    SET name = EXCLUDED.name, operator = EXCLUDED.operator,
                        max_kv = EXCLUDED.max_kv, geom = EXCLUDED.geom
                    """,
                    (osm_id, name, operator, max_kv, lon, lat),
                )
            else:
                row = element_to_line(element, settings.min_line_kv)
                if row is None:
                    continue
                osm_id, max_kv, wkt = row
                cursor.execute(
                    """
                    INSERT INTO lines (osm_id, max_kv, geom)
                    VALUES (%s, %s, ST_GeomFromText(%s, 4326))
                    ON CONFLICT (osm_id) DO UPDATE SET max_kv = EXCLUDED.max_kv, geom = EXCLUDED.geom
                    """,
                    (osm_id, max_kv, wkt),
                )
            written += 1
    mark_tile_done(connection, key)
    connection.commit()
    time.sleep(2)  # be polite to the public server
    return written


def ingest_osm(connection, settings: Settings) -> tuple:
    south, west, north, east = state_bbox(connection, settings.state_fips)
    tiles = make_tiles(south, west, north, east, settings.overpass_tiles)
    substation_total = 0
    line_total = 0
    failed = []
    for number, (t_south, t_west, t_north, t_east) in enumerate(tiles, start=1):
        print(f"Tile {number}/{len(tiles)}")
        bounds = dict(south=t_south, west=t_west, north=t_north, east=t_east)
        substation_total += load_tile(connection, settings, "substations", number,
                                      SUBSTATION_QUERY.format(**bounds), failed)
        line_total += load_tile(connection, settings, "lines", number, LINE_QUERY.format(**bounds), failed)
    print(f"OSM rows written this run: {substation_total} substations, {line_total} lines")
    if failed:
        print(f"WARNING: {len(failed)} tile queries failed and were skipped: {', '.join(failed)}")
        print("Re-run the same command: tiles that already succeeded are skipped, only these are retried.")
    else:
        print("All tile queries have succeeded.")
    return substation_total, line_total