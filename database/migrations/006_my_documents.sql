-- Migration 006: My Document library (superadmin-only PDF uploads)
--
-- A small personal PDF library surfaced as a "My Document" box on the
-- dashboard. Each row is one uploaded PDF, stored in MinIO under
-- documents/{user_id}/{document_id}_{filename}, with uploaded_by scoping
-- the library to its uploader. Superadmin-only at the API layer
-- (require_superadmin), nothing enforced at the schema level.
--
-- Purely additive: new table, no existing data touched.

BEGIN;

CREATE TABLE my_documents (
    document_id VARCHAR(36) PRIMARY KEY,
    title VARCHAR(255),
    file_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    content_type VARCHAR(100) NOT NULL DEFAULT 'application/pdf',
    file_size INTEGER NOT NULL,
    uploaded_by VARCHAR(36) NOT NULL REFERENCES users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_my_documents_uploaded_by ON my_documents(uploaded_by);

COMMIT;
