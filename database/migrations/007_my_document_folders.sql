-- Migration 007: Folders for the "My Document" library
--
-- Adds a simple nested-folder structure on top of the superadmin PDF
-- library introduced in 006. Folders are scoped to their creator, the
-- same way documents are scoped to their uploader. A document or folder
-- with no parent lives at the library root (folder_id / parent_folder_id
-- IS NULL).
--
-- Purely additive: new table + one nullable column, no existing data touched.

BEGIN;

CREATE TABLE my_document_folders (
    folder_id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    parent_folder_id VARCHAR(36) REFERENCES my_document_folders(folder_id) ON DELETE CASCADE,
    created_by VARCHAR(36) NOT NULL REFERENCES users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_my_document_folders_created_by ON my_document_folders(created_by);
CREATE INDEX idx_my_document_folders_parent ON my_document_folders(parent_folder_id);

ALTER TABLE my_documents
    ADD COLUMN folder_id VARCHAR(36) REFERENCES my_document_folders(folder_id) ON DELETE CASCADE;

CREATE INDEX idx_my_documents_folder_id ON my_documents(folder_id);

COMMIT;
