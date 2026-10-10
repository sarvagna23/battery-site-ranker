-- One row per candidate substation (69 kV and up) inside the loaded state, with every ranking feature.
-- Rebuilt after each ingest with REFRESH MATERIALIZED VIEW site_features.
DROP MATERIALIZED VIEW IF EXISTS site_features;

CREATE MATERIALIZED VIEW site_features AS
SELECT
    s.osm_id                      AS id,
    s.name                        AS name,
    s.operator                    AS operator,
    s.max_kv                      AS max_kv,
    ST_Y(s.geom)                  AS lat,
    ST_X(s.geom)                  AS lon,
    c.geoid                       AS county_geoid,
    c.name                        AS county,
    hv.dist_km                    AS dist_hv_line_km,
    dens.line_count               AS lines_within_10km,
    q.renewable_queue_mw          AS renewable_queue_mw,
    q.storage_queue_mw            AS storage_queue_mw,
    q.withdrawn_share             AS withdrawn_share
FROM substations s
-- The inner join also drops substations that were fetched from neighbouring states.
JOIN counties c ON ST_Covers(c.geom, s.geom)
-- Nearest 230 kV+ line: KNN on the geometry index, then an exact geodesic distance on that one line.
LEFT JOIN LATERAL (
    SELECT ST_Distance(l.geom::geography, s.geom::geography) / 1000.0 AS dist_km
    FROM lines l
    WHERE l.max_kv >= 230
    ORDER BY l.geom <-> s.geom
    LIMIT 1
) hv ON true
-- Count of 115 kV+ lines within 10 km of the substation.
LEFT JOIN LATERAL (
    SELECT COUNT(*) AS line_count
    FROM lines l
    WHERE l.max_kv >= 115
      AND ST_DWithin(l.geom::geography, s.geom::geography, 10000)
) dens ON true
LEFT JOIN county_queue q ON q.county_norm = c.name_norm
WHERE s.max_kv >= 69;

CREATE UNIQUE INDEX site_features_id_idx ON site_features (id);
