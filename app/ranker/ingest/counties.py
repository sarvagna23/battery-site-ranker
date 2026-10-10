"""Load one state's county polygons from the Census cartographic boundary file."""
import io
import os
import zipfile

import shapefile  # pyshp
from shapely.geometry import MultiPolygon, shape

from ..config import Settings
from .common import download_first_available, normalize_county


def to_multipolygon(geometry) -> MultiPolygon:
    """Wrap a Polygon in a MultiPolygon so every row has the same geometry type."""
    return geometry if isinstance(geometry, MultiPolygon) else MultiPolygon([geometry])


def read_state_counties(zip_path: str, state_fips: str) -> list:
    """Return (geoid, name, wkt) for each county of the given state in the shapefile zip."""
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        shp_name = next(name for name in names if name.endswith(".shp"))
        stem = shp_name[:-4]
        reader = shapefile.Reader(
            shp=io.BytesIO(archive.read(stem + ".shp")),
            shx=io.BytesIO(archive.read(stem + ".shx")),
            dbf=io.BytesIO(archive.read(stem + ".dbf")),
        )
    field_names = [field[0] for field in reader.fields[1:]]
    counties = []
    for shape_record in reader.iterShapeRecords():
        attributes = dict(zip(field_names, shape_record.record))
        if attributes.get("STATEFP") != state_fips:
            continue
        geometry = to_multipolygon(shape(shape_record.shape.__geo_interface__))
        counties.append((attributes["GEOID"], attributes["NAME"], geometry.wkt))
    return counties


def ingest_counties(connection, settings: Settings) -> int:
    zip_path = download_first_available(
        settings.county_zip_urls, os.path.join(settings.data_dir, "counties.zip")
    )
    counties = read_state_counties(zip_path, settings.state_fips)
    if not counties:
        raise RuntimeError(f"No counties found for {settings.state} (FIPS {settings.state_fips}).")
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM counties WHERE state_fips = %s", (settings.state_fips,))
        for geoid, name, wkt in counties:
            cursor.execute(
                """
                INSERT INTO counties (geoid, name, name_norm, state_fips, geom)
                VALUES (%s, %s, %s, %s, ST_Multi(ST_GeomFromText(%s, 4326)))
                """,
                (geoid, name, normalize_county(name), settings.state_fips, wkt),
            )
    connection.commit()
    print(f"Loaded {len(counties)} counties for {settings.state}")
    return len(counties)
