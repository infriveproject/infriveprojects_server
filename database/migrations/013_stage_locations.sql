-- Migration 013: GPS location of a project / folder (stage)
--
-- Every inspection under "AAI Imphal Airport" happens at the same place, so
-- the site coordinates belong to the folder, not to each record. One row per
-- stage: stage_id IS the primary key.
--
-- Deliberately NOT restricted to project heads (depth 1). Today you only fill
-- in the heads — "University of Delhi", "AAI Imphal Airport", "IIT Tirupur" —
-- and every folder beneath them inherits that location. The day you want a
-- separate pin for the "Earthwork" sub-folder, you just insert a row for it:
-- no migration, no code change. Resolution always walks lineage_path from the
-- deepest ancestor upwards, so the most specific pin available wins.
--
-- No PostGIS: plain NUMERIC lat/lng with range CHECKs. radius_m is the site
-- extent, which is what a later "is this inspection actually on site?" check
-- would compare a reading against.
--
-- Idempotent (IF NOT EXISTS throughout): init_db() runs Base.metadata.create_all
-- on startup, so the app may already have created this table from the model.
--
-- Purely additive: new table, no existing data touched.

BEGIN;

CREATE TABLE IF NOT EXISTS stage_locations (
    stage_id    VARCHAR(50) PRIMARY KEY REFERENCES stages(stage_id) ON DELETE CASCADE,

    -- WGS84 degrees. 6 decimals ~= 0.11 m, finer than any phone GPS.
    latitude    NUMERIC(9,6) NOT NULL,
    longitude   NUMERIC(9,6) NOT NULL,

    -- How far the site extends from that point, in metres. Lets the mobile
    -- app draw a site boundary and, later, verify an inspection was on site.
    radius_m    INTEGER,
    altitude_m  NUMERIC(8,2),

    -- Free-text site address and an optional link to the admin `locations`
    -- lookup (region/office) already used for permission scoping. The lookup
    -- row says WHICH region; these coordinates say WHERE on the ground.
    address     TEXT,
    location_id VARCHAR(36) REFERENCES locations(location_id) ON DELETE SET NULL,

    source      VARCHAR(20) NOT NULL DEFAULT 'manual',

    created_by  VARCHAR(100),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_sl_latitude  CHECK (latitude  BETWEEN -90  AND 90),
    CONSTRAINT chk_sl_longitude CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT chk_sl_radius    CHECK (radius_m IS NULL OR radius_m > 0),
    CONSTRAINT chk_sl_source    CHECK (source IN ('device_gps', 'manual', 'map_pick', 'import'))
);

CREATE INDEX IF NOT EXISTS idx_stage_locations_latlng ON stage_locations(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_stage_locations_location ON stage_locations(location_id);

COMMIT;
