-- Migration 016: Mandatory comment alongside the rating
--
-- The Submit/Verify popup now collects three things, in this order:
--   Rating  (required)  -- the 1-5 score
--   Comment (required)  -- why that score was given
--   Remarks (optional)  -- anything else about the transition itself
--
-- Comment and remark are deliberately separate columns, not one reused field:
-- the comment justifies the SCORE and must always be there, while the remark
-- is a free note about the STEP and may be empty. Collapsing them would mean
-- either forcing a remark on a cancel, or letting a score stand unexplained.
--
-- Nullability differs by table, and that difference is the point:
--   form_record_ratings.comment  NOT NULL -- a row here means "rated", and a
--                                            rating is never allowed to exist
--                                            without its justification.
--   form_actions.comment         NULL     -- most actions (a cancel) carry no
--                                            rating at all, so no comment.
--
-- The CHECK uses btrim() so a comment of spaces is rejected the same as an
-- empty one -- NOT NULL alone would happily accept '   '.
--
-- Written to be safe on an environment that already has ratings: the column
-- is added nullable, backfilled from the existing remark (falling back to a
-- placeholder), and only then made NOT NULL.

BEGIN;

-- ── form_record_ratings.comment ──────────────────────────────────────────
ALTER TABLE form_record_ratings
    ADD COLUMN IF NOT EXISTS comment TEXT;

-- Backfill before the NOT NULL: any pre-existing rating keeps its reason if
-- it had one in remark, otherwise it is marked as migrated-without-one.
UPDATE form_record_ratings
SET comment = COALESCE(NULLIF(btrim(remark), ''), 'No comment recorded (added before comments were required)')
WHERE comment IS NULL;

ALTER TABLE form_record_ratings
    ALTER COLUMN comment SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_frr_comment') THEN
        ALTER TABLE form_record_ratings
            ADD CONSTRAINT chk_frr_comment CHECK (btrim(comment) <> '');
    END IF;
END $$;

-- ── form_actions.comment ─────────────────────────────────────────────────
ALTER TABLE form_actions
    ADD COLUMN IF NOT EXISTS comment TEXT;

-- A comment is only meaningful next to a score: forbid one without the other,
-- so the history can never show a justification for a rating that is not there.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_form_actions_comment') THEN
        ALTER TABLE form_actions
            ADD CONSTRAINT chk_form_actions_comment
            CHECK (comment IS NULL OR (rating IS NOT NULL AND btrim(comment) <> ''));
    END IF;
END $$;

COMMIT;
