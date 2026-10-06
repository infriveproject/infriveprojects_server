-- Migration 011: Add a remark/note field to uploaded documents
--
-- Lets a superadmin attach a short free-text remark to each PDF in their
-- "My Document" library (e.g. "awaiting signature", "final version").
-- Purely additive: one nullable column, no existing data touched.

BEGIN;

ALTER TABLE my_documents ADD COLUMN IF NOT EXISTS remark TEXT;

COMMIT;
