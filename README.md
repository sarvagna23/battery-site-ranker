# Battery Storage Site Ranker

Ranks candidate battery storage sites in one US state. PostGIS computes grid and interconnection features for every substation, a weighted scoring model ranks them, a LangGraph agent writes a "why this site" explanation that is checked against the data, and a map lets you change the weights live.

![Map screenshot](docs/screenshot.png)
<!-- Add docs/screenshot.png after the first real run -->

## Data (all public, no API keys)

| Data | Source | Used for |
|---|---|---|
| Substations (69 kV and up) and transmission lines (115 kV and up) | OpenStreetMap, through the Overpass API | Candidate sites, grid proximity and density |
| Interconnection queue | LBNL "Queued Up" workbook (2026 edition, data through 2025) | County level queue pressure |
| County boundaries | US Census cartographic boundary files | Joining sites to queue data |

Candidates are existing substations. Parcel data is not included, because it is published county by county with no common format.

## How it works

```
Overpass (OSM) ----> substations, lines ----+
Census zip --------> counties --------------+--> PostGIS --> site_features view --> scoring --> FastAPI --> map
LBNL workbook -----> queue_projects --------+                                         |
                                                                   LangGraph explainer (draft, verify, retry, fallback)
```

**Features per substation (computed in SQL, `sql/features.sql`)**

| Feature | Better when | Default weight |
|---|---|---|
| Substation voltage (kV) | higher | 0.20 |
| Distance to nearest 230 kV+ line (km) | lower | 0.25 |
| 115 kV+ lines within 10 km | higher | 0.15 |
| Active solar and wind queue in the county (MW) | higher (storage firming demand) | 0.20 |
| Active storage queue in the county (MW) | lower (competition) | 0.10 |
| Share of county queue withdrawn | lower (interconnection risk) | 0.10 |

**Scoring (`app/ranker/scoring.py`).** Each feature becomes a percentile among the candidates, flipped when lower is better. The score is the weighted average scaled to 0 to 100. Weights are relative, and a site with no queue data for its county gets a neutral value for those features and is flagged.

**Explainer (`app/ranker/explain/agent.py`).** The agent builds a fact sheet for the site, asks Claude for a short assessment, then rejects any draft containing a number that is not in the fact sheet. It retries once with the bad numbers named, then falls back to a deterministic template. With no API key it runs in template mode.

## Run it

You need Docker Desktop and, optionally, a Claude API key for the explanations.

```bash
make build
make up
make smoke        # checks the PostGIS SQL against a tiny hand-made dataset
make test         # unit tests
OVERPASS_TILES=8 STATE=NM make ingest   # downloads and loads real data; re-run until it says all tile queries succeeded
open http://localhost:8000
```

The public Overpass servers are often overloaded, so the OpenStreetMap step splits the state into tiles, detects timeouts that come back as HTTP 200, and records each successful tile in an `osm_tiles_done` table. A re-run skips finished tiles and retries only the failed ones.

Change the state with `STATE=AZ make ingest` (and `STATE=AZ make up`). Set `ANTHROPIC_API_KEY` in your shell to enable Claude explanations. If the queue step fails on column names, run `docker compose run --rm app python -m ranker.ingest inspect-queue` and adjust `COLUMN_ALIASES` in `app/ranker/ingest/queue.py`.

After the data is loaded, `make eval-explain` measures how often the first draft passes the number check.

## Status

**Built and verified**
- PostGIS feature SQL, checked by `make smoke` against a hand-made dataset with geodesic distances computed independently (all checks pass; it caught a real NULL bug in the withdrawn-share view).
- 39 unit tests for scoring, ingest parsing, the explainer's number check and the API.
- Real-data ingest for New Mexico: 33 counties from Census files and 626 queue rows from the LBNL workbook.

**In progress**
- OpenStreetMap coverage. Overpass tile queries still fail intermittently, so the substation and line counts are partial until a run prints that all tile queries succeeded.
- Measuring the explainer (`make eval-explain`) and the ranking time.

**Next**
- Screenshot of the map, final README numbers, and a second state to show the pipeline is not hard-coded to one.

## Results (filled in only with measured numbers)

| Measure | Value |
|---|---|
| State | New Mexico |
| Counties loaded | 33 |
| Queue rows loaded | 626 |
| Substations ranked | TBD, ingest incomplete (568 loaded so far) |
| Transmission lines loaded | TBD |
| Ranking time for all candidates (API `rank_ms`) | TBD |
| Explanations passing the number check on first draft (25 sites) | TBD |

## Limits

- OpenStreetMap power data is community maintained, so coverage and voltage tags vary by area.
- The queue data is joined by county name, and projects listed in several counties have their MW split evenly.
- The score ranks grid position and queue context only. It does not model land, slope, permitting, flood risk or cost.
- The OpenStreetMap basemap tiles are for light demo use only.
- The database password in `docker-compose.yml` is a throwaway local value.
