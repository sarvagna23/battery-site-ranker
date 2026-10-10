import openpyxl
import pytest

from ranker.ingest.common import normalize_county
from ranker.ingest.counties import read_state_counties
from ranker.ingest.osm import element_to_line, element_to_substation, make_tiles, parse_max_kv
from ranker.ingest.queue import normalize_status, normalize_tech, parse_rows, split_counties


@pytest.mark.parametrize("tag,expected", [
    ("345000", 345.0), ("345000;138000", 345.0), ("138000;345000", 345.0),
    ("230 kV", 230.0), ("unknown", None), (None, None), ("", None), ("999999999", None),
])
def test_parse_max_kv(tag, expected):
    assert parse_max_kv(tag) == expected


def test_substation_from_way_uses_center_and_filters_voltage():
    way = {"type": "way", "id": 7, "center": {"lat": 31.5, "lon": -97.1},
           "tags": {"voltage": "138000", "name": "Waco North", "operator": "Oncor"}}
    assert element_to_substation(way, 69) == ("way/7", "Waco North", "Oncor", 138.0, -97.1, 31.5)
    low = {**way, "tags": {"voltage": "12000"}}
    assert element_to_substation(low, 69) is None


def test_substation_node_uses_own_coordinates():
    node = {"type": "node", "id": 3, "lat": 30.0, "lon": -95.0, "tags": {"voltage": "345000"}}
    assert element_to_substation(node, 69)[4:] == (-95.0, 30.0)


def test_line_builds_linestring_and_rejects_short_geometry():
    line = {"id": 9, "tags": {"voltage": "345000"},
            "geometry": [{"lat": 30.0, "lon": -97.0}, {"lat": 30.5, "lon": -97.5}]}
    assert element_to_line(line, 115) == ("way/9", 345.0, "LINESTRING(-97.0 30.0, -97.5 30.5)")
    assert element_to_line({**line, "geometry": [{"lat": 1, "lon": 1}]}, 115) is None
    assert element_to_line({**line, "tags": {"voltage": "69000"}}, 115) is None


def test_make_tiles_cover_the_box():
    tiles = make_tiles(25.0, -107.0, 37.0, -93.0, 4)
    assert len(tiles) == 16
    assert min(t[0] for t in tiles) == 25.0 and max(t[2] for t in tiles) == pytest.approx(37.0)
    assert min(t[1] for t in tiles) == -107.0 and max(t[3] for t in tiles) == pytest.approx(-93.0)


def test_normalize_county_variants_match():
    assert normalize_county("St. Louis County") == normalize_county("Saint Louis") == "st louis"
    assert normalize_county("Harris") == "harris"
    assert normalize_county("Orleans Parish") == "orleans"


def test_split_counties_and_labels():
    assert split_counties("Harris, Fort Bend") == ["harris", "fort bend"]
    assert split_counties("Pecos; Reeves and Ward") == ["pecos", "reeves", "ward"]
    assert normalize_status("Withdrawn") == "withdrawn"
    assert normalize_status("Active") == "active"
    assert normalize_tech("Battery Storage") == "storage"
    assert normalize_tech("Solar") == "solar"


def build_workbook(rows, junk_rows=2):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "03. Complete Queue Data"
    for _ in range(junk_rows):          # real workbooks have notes above the table
        sheet.append(["Source: LBNL", None])
    sheet.append(["q_id", "q_status", "state", "county", "type_clean", "mw1"])
    for row in rows:
        sheet.append(row)
    return workbook


def test_parse_rows_finds_header_filters_state_and_splits_mw():
    workbook = build_workbook([
        ["A1", "Active", "TX", "Harris", "Solar", 200],
        ["A2", "Withdrawn", "TX", "Harris, Fort Bend", "Wind", 300],
        ["A3", "Active", "CA", "Kern", "Solar", 999],
        ["A4", "Active", "TX", "Pecos", "Storage", None],
        ["A5", "Active", "TX", "Pecos", "Storage", 0],
    ])
    rows = parse_rows(workbook, "TX")
    assert ("A1", "harris", "active", "solar", 200.0) in rows
    assert ("A2", "harris", "withdrawn", "wind", 150.0) in rows
    assert ("A2", "fort bend", "withdrawn", "wind", 150.0) in rows
    assert len(rows) == 3


def test_missing_columns_raise_helpful_error():
    workbook = openpyxl.Workbook()
    workbook.active.append(["something", "else"])
    with pytest.raises(RuntimeError, match="inspect-queue"):
        parse_rows(workbook, "TX")


def test_read_state_counties_from_zip(tmp_path):
    shapefile = pytest.importorskip("shapefile")
    import zipfile
    base = tmp_path / "cb_test_us_county_20m"
    writer = shapefile.Writer(str(base), shapeType=shapefile.POLYGON)
    writer.field("STATEFP", "C", 2)
    writer.field("GEOID", "C", 5)
    writer.field("NAME", "C", 40)
    writer.poly([[[-97, 30], [-97, 31], [-96, 31], [-96, 30], [-97, 30]]])
    writer.record("48", "48453", "Travis")
    writer.poly([[[-120, 35], [-120, 36], [-119, 36], [-119, 35], [-120, 35]]])
    writer.record("06", "06029", "Kern")
    writer.close()
    zip_path = tmp_path / "counties.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for extension in ("shp", "shx", "dbf"):
            archive.write(f"{base}.{extension}", f"cb_test_us_county_20m.{extension}")
    counties = read_state_counties(str(zip_path), "48")
    assert len(counties) == 1
    assert counties[0][:2] == ("48453", "Travis")
    assert counties[0][2].startswith("MULTIPOLYGON")
