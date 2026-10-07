-- Migration 012: GPS location of an inspection (form record)
--
-- Stores where on site an inspection was actually carried out. The web app
-- only persists and serves this data — reading the device GPS and showing it
-- on a map is the mobile app's job, so nothing here assumes a map provider.
--
-- One location per inspection: record_id IS the primary key, so re-sending a
-- location for the same record overwrites it (upsert) rather than piling up
-- rows. This is deliberately different from a project/site, which may have
-- several pins (gate, each building) and would need its own one-to-many table.
--
-- No PostGIS: plain NUMERIC lat/lng with range CHECKs is enough for storage
-- and for bounding-box lookups. The (latitude, longitude) index keeps a
-- future "inspections near me" query on the mobile side cheap.
--
-- Idempotent (IF NOT EXISTS throughout): init_db() runs Base.metadata.create_all
-- on startup, so the app may already have created this table from the model.
--
-- Purely additive: new table, no existing data touched.

BEGIN;

CREATE TABLE IF NOT EXISTS form_record_locations (
    record_id   VARCHAR(50) PRIMARY KEY REFERENCES form_records(record_id) ON DELETE CASCADE,

    -- WGS84 degrees. 6 decimal places ~= 0.11 m precision, far finer than
    -- any phone GPS, so nothing meaningful is lost to rounding.
    latitude    NUMERIC(9,6) NOT NULL,
    longitude   NUMERIC(9,6) NOT NULL,

    -- Reported by the device at capture time. accuracy_m is the radius the
    -- phone claims the true position lies within — keep it, it is what tells
    -- you later whether a reading is trustworthy or was taken indoors.
    accuracy_m  NUMERIC(8,2),
    altitude_m  NUMERIC(8,2),

    -- Reverse-geocoded or hand-typed address, purely for display/search.
    address     TEXT,

    source      VARCHAR(20) NOT NULL DEFAULT 'device_gps',

    captured_by VARCHAR(100),
    captured_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_frl_latitude  CHECK (latitude  BETWEEN -90  AND 90),
    CONSTRAINT chk_frl_longitude CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT chk_frl_accuracy  CHECK (accuracy_m IS NULL OR accuracy_m >= 0),
    CONSTRAINT chk_frl_source    CHECK (source IN ('device_gps', 'manual', 'map_pick', 'import'))
);

CREATE INDEX IF NOT EXISTS idx_form_record_locations_latlng ON form_record_locations(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_form_record_locations_captured_at ON form_record_locations(captured_at);

COMMIT;
