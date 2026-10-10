"""Settings read from environment variables, plus the state lookup table."""
import os
from dataclasses import dataclass

# USPS code -> Census state FIPS code (used to pick one state out of the national county file)
STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09",
    "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17",
    "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24",
    "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30", "NE": "31",
    "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56",
}

DEFAULT_OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

# Census cartographic boundary county files; the first one that downloads is used.
DEFAULT_COUNTY_ZIP_URLS = (
    "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_20m.zip",
    "https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_us_county_20m.zip",
    "https://www2.census.gov/geo/tiger/GENZ2021/shp/cb_2021_us_county_20m.zip",
)

DEFAULT_QUEUE_URL = "https://emp.lbl.gov/sites/default/files/2026-05/LBNL_Ix_Queue_Data_File_thru2025.xlsx"


@dataclass(frozen=True)
class Settings:
    database_url: str
    state: str
    data_dir: str
    min_substation_kv: float
    min_line_kv: float
    overpass_tiles: int
    overpass_urls: tuple
    county_zip_urls: tuple
    queue_url: str
    anthropic_api_key: str
    claude_model: str
    explain_mode: str  # "auto" (LLM if a key exists), "llm", or "template"

    @property
    def state_fips(self) -> str:
        if self.state not in STATE_FIPS:
            raise ValueError(f"Unknown STATE '{self.state}'. Use a two-letter USPS code such as TX.")
        return STATE_FIPS[self.state]


def load_settings() -> Settings:
    """Read settings from the environment at call time, so tests can override them."""
    county_override = os.environ.get("COUNTY_ZIP_URL")
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "postgresql://ranker:ranker@localhost:5433/ranker"),
        state=os.environ.get("STATE", "TX").upper(),
        data_dir=os.environ.get("DATA_DIR", "/data"),
        min_substation_kv=float(os.environ.get("MIN_SUBSTATION_KV", "69")),
        min_line_kv=float(os.environ.get("MIN_LINE_KV", "115")),
        overpass_tiles=int(os.environ.get("OVERPASS_TILES", "4")),
        overpass_urls=DEFAULT_OVERPASS_URLS,
        county_zip_urls=(county_override,) if county_override else DEFAULT_COUNTY_ZIP_URLS,
        queue_url=os.environ.get("QUEUE_URL", DEFAULT_QUEUE_URL),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        claude_model=os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
        explain_mode=os.environ.get("EXPLAIN_MODE", "auto").lower(),
    )
