-- Migration 010: Prevent duplicate folder names in "My Documents"
--
-- Folders had no uniqueness constraint at all, so the same superadmin could
-- create "Site Reports" twice with two different folder_ids, which is
-- confusing to navigate. This adds a case-insensitive unique index scoped
-- to the creator, so each superadmin's own folder names must be distinct,
-- but two different superadmins can each have a folder named the same thing.
--
-- NOTE: if duplicate (created_by, lower(name)) rows already exist in your
-- database, this index creation will fail. Rename or delete the duplicates
-- first, then rerun this migration.

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_my_document_folders_created_by_name
    ON my_document_folders (created_by, lower(name));

COMMIT;
