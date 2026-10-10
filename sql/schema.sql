-- Tables for the ranker. Safe to run repeatedly.
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS counties (
    geoid      text PRIMARY KEY,
    name       text NOT NULL,
    name_norm  text NOT NULL,
    state_fips text NOT NULL,
    geom       geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS counties_geom_idx ON counties USING gist (geom);

CREATE TABLE IF NOT EXISTS substations (
    osm_id   text PRIMARY KEY,
    name     text,
    operator text,
    max_kv   double precision NOT NULL,
    geom     geometry(Point, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS substations_geom_idx ON substations USING gist (geom);

CREATE TABLE IF NOT EXISTS lines (
    osm_id text PRIMARY KEY,
    max_kv double precision NOT NULL,
    geom   geometry(LineString, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS lines_geom_idx ON lines USING gist (geom);
-- Expression index so ST_DWithin on geography can use an index.
CREATE INDEX IF NOT EXISTS lines_geog_idx ON lines USING gist ((geom::geography));

CREATE TABLE IF NOT EXISTS queue_projects (
    row_id      bigserial PRIMARY KEY,
    queue_id    text,
    county_norm text NOT NULL,
    status      text NOT NULL,   -- active | withdrawn | operational | other
    tech        text NOT NULL,   -- solar | wind | storage | gas | other
    mw          double precision NOT NULL
);
CREATE INDEX IF NOT EXISTS queue_county_idx ON queue_projects (county_norm);

-- Queue totals per county. withdrawn_share is withdrawn MW divided by all queued MW.
CREATE OR REPLACE VIEW county_queue AS
SELECT
    county_norm,
    COALESCE(SUM(mw) FILTER (WHERE status = 'active' AND tech IN ('solar', 'wind')), 0) AS renewable_queue_mw,
    COALESCE(SUM(mw) FILTER (WHERE status = 'active' AND tech = 'storage'), 0)          AS storage_queue_mw,
    COALESCE(SUM(mw) FILTER (WHERE status = 'withdrawn'), 0) / NULLIF(SUM(mw), 0)       AS withdrawn_share
FROM queue_projects
GROUP BY county_norm;
