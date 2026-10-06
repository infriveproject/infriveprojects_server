-- Migration 008: Document Templates for the "My Document" library
--
-- Introduces "Template" as the top-level container inside My Documents:
--
--   My Documents -> Template -> Folder -> File
--
-- Folders are scoped to a template and capped at one level (no folder-in-
-- folder nesting, enforced in the application layer). Documents can live
-- directly under a template or inside one of its folders.
--
-- This migration is written defensively (IF NOT EXISTS / IF EXISTS) because
-- an earlier, unversioned prototype of this feature was applied by hand to
-- some environments: document_templates and my_document_folders may already
-- exist there without matching 006/007 exactly. The statements below bring
-- any such environment and a clean 006+007 environment to the same final
-- shape without dropping data.

BEGIN;

CREATE TABLE IF NOT EXISTS document_templates (
    template_id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    created_by VARCHAR(36) NOT NULL REFERENCES users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_document_templates_created_by ON document_templates(created_by);

-- my_document_folders: add template scoping (older environments created this
-- table without it).
ALTER TABLE my_document_folders
    ADD COLUMN IF NOT EXISTS template_id VARCHAR(36) REFERENCES document_templates(template_id) ON DELETE CASCADE;

-- Backfill any pre-existing orphan folders into the oldest template owned by
-- their creator, if one exists. A no-op wherever no templates exist yet.
UPDATE my_document_folders f
SET template_id = (
    SELECT t.template_id FROM document_templates t
    WHERE t.created_by = f.created_by
    ORDER BY t.created_at ASC
    LIMIT 1
)
WHERE f.template_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_my_document_folders_template_id ON my_document_folders(template_id);

-- my_documents: reconcile the two divergent shapes seen in the wild.
-- 006/007 environments have `title` (unused by the current UI) and lack
-- `template_id`; hand-migrated environments have `template_id` and lack
-- `folder_id`. End state: no `title`, both `template_id` and `folder_id`.
ALTER TABLE my_documents DROP COLUMN IF EXISTS title;

ALTER TABLE my_documents
    ADD COLUMN IF NOT EXISTS template_id VARCHAR(36) REFERENCES document_templates(template_id) ON DELETE CASCADE;

ALTER TABLE my_documents
    ADD COLUMN IF NOT EXISTS folder_id VARCHAR(36) REFERENCES my_document_folders(folder_id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_my_documents_template_id ON my_documents(template_id);
CREATE INDEX IF NOT EXISTS idx_my_documents_folder_id ON my_documents(folder_id);

COMMIT;
