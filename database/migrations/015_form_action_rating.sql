-- Migration 015: Capture the rating alongside the remark on a transition
--
-- The Submit/Verify popup already collects a remark, which lands in
-- form_actions.remarks. The rating is given in that same breath, so it is
-- stored on the same row: who rated, at which step, from which state, with
-- what justification -- one coherent history entry instead of two half ones.
--
-- This complements form_record_ratings (014) rather than replacing it, the
-- same way form_actions.from_state/to_state complements form_records.status:
--   form_actions.rating        -> the full history ("rated 2 at submit, 4 at verify")
--   form_record_ratings.rating -> the current score, one row per record,
--                                 which is what lists and averages read
-- process_transition() writes both in one commit, so they cannot drift.
--
-- NULL is meaningful here: most actions carry no rating (a cancel, or a
-- submit where the reviewer skipped it), so the column is nullable and the
-- CHECK only constrains the values that are actually present.
--
-- Idempotent and purely additive: one nullable column, no existing data
-- touched, no backfill needed.

BEGIN;

ALTER TABLE form_actions
    ADD COLUMN IF NOT EXISTS rating SMALLINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_form_actions_rating'
    ) THEN
        ALTER TABLE form_actions
            ADD CONSTRAINT chk_form_actions_rating
            CHECK (rating IS NULL OR rating BETWEEN 1 AND 5);
    END IF;
END $$;

COMMIT;
