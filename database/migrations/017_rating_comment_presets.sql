-- Migration 017: Fixed comment text per rating value
--
-- The reviewer no longer types the comment. They pick a star rating and the
-- comment is the agreed wording for that score, identical on every record.
--
-- Exactly five rows, keyed by the rating itself: rating IS the primary key,
-- so there can never be two competing texts for "3 stars", and the CHECK
-- keeps the table to the 1-5 range the UI offers. Global by design -- every
-- form type shares one vocabulary, which is the point of fixing the wording.
--
-- The text lives in the database, not in code, so the wording can be reworded
-- with one UPDATE and no redeploy:
--
--   UPDATE rating_comment_presets SET comment_text = '...' WHERE rating = 3;
--
-- Changing a preset does NOT rewrite comments already stored on past records:
-- form_record_ratings.comment and form_actions.comment hold the text as it
-- stood when the record was rated, which is what an audit trail must do.
--
-- The five texts below are the agreed wording. Re-running this migration
-- will not overwrite them if the rows already exist (ON CONFLICT DO NOTHING),
-- so reword live rows with an UPDATE rather than by editing this file.

BEGIN;

CREATE TABLE IF NOT EXISTS rating_comment_presets (
    rating       SMALLINT PRIMARY KEY,
    comment_text TEXT NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_rcp_rating CHECK (rating BETWEEN 1 AND 5),
    CONSTRAINT chk_rcp_text   CHECK (btrim(comment_text) <> '')
);

-- ON CONFLICT DO NOTHING so re-running never clobbers edited wording.
INSERT INTO rating_comment_presets (rating, comment_text) VALUES
    (1, 'Critical Non-compliance'),
    (2, 'Minor Deficiencies Found'),
    (3, 'Standard Compliance Verified'),
    (4, 'High Quality Standards Verified'),
    (5, 'Outstanding Quality & Zero Defects')
ON CONFLICT (rating) DO NOTHING;

COMMIT;
