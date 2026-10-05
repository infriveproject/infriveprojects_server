-- Migration 009: Remove the "Template" layer from the "My Document" library
--
-- Simplifies the hierarchy introduced in 008 from
--
--   My Documents -> Template -> Folder -> File
--
-- down to
--
--   My Documents -> Folder -> File
--
-- Folders become top-level containers owned directly by their creator (same
-- as before 008). Drops the template_id columns first so the foreign-key
-- dependency on document_templates is gone before the table itself is
-- dropped.
--
-- Destructive for any pre-existing folders/documents that only existed
-- because they were nested under a template — there is no template-aware
-- data to preserve beyond the folder/document rows themselves, which are
-- kept as-is (just un-scoped from their template).

BEGIN;

ALTER TABLE my_document_folders DROP COLUMN IF EXISTS template_id;
ALTER TABLE my_documents DROP COLUMN IF EXISTS template_id;

DROP TABLE IF EXISTS document_templates;

COMMIT;
