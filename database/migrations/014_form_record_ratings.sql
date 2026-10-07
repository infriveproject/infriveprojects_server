-- Migration 014: Rating and remark for an inspection (form record)
--
-- Every record in the list (EARTHW-00001, EARTHW-00002, ...) can carry one
-- review: a 1-5 score plus a free-text remark explaining it.
--
-- One rating per inspection: record_id IS the primary key, so re-rating the
-- same record overwrites the previous score (upsert) instead of piling up
-- rows. If a rating *history* is ever needed (several reviewers, or an audit
-- trail of score changes), that is a different table with its own surrogate
-- key -- this one deliberately answers only "what is this record's rating".
--
-- rating is SMALLINT, not NUMERIC: the UI is a 5-star picker, so only whole
-- values 1..5 are reachable and the CHECK enforces exactly that. A half-star
-- scale later would widen this column, not add a second one.
--
-- Idempotent (IF NOT EXISTS throughout): init_db() runs Base.metadata.create_all
-- on startup, so the app may already have created this table from the model.
--
-- Purely additive: new table, no existing data touched.

BEGIN;

CREATE TABLE IF NOT EXISTS form_record_ratings (
    record_id  VARCHAR(50) PRIMARY KEY REFERENCES form_records(record_id) ON DELETE CASCADE,

    -- 1 (worst) .. 5 (best). NOT NULL: a row here means "this was rated",
    -- so an unrated record simply has no row rather than a NULL score.
    rating     SMALLINT NOT NULL,

    -- Why that score was given. Optional -- a reviewer may rate without
    -- writing anything, but never write a remark without a score.
    remark     TEXT,

    rated_by   VARCHAR(100),
    rated_at   TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_frr_rating CHECK (rating BETWEEN 1 AND 5)
);

-- Supports "show me everything rated 2 or below" and the average-score
-- rollups per form type / project without scanning the whole table.
CREATE INDEX IF NOT EXISTS idx_form_record_ratings_rating ON form_record_ratings(rating);
CREATE INDEX IF NOT EXISTS idx_form_record_ratings_rated_at ON form_record_ratings(rated_at);

COMMIT;
