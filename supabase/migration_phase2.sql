-- Phase 2 Migration: Application status tracking
-- Run this in the Supabase SQL Editor

ALTER TABLE roles
  ADD COLUMN IF NOT EXISTS application_status text DEFAULT 'unreviewed';

ALTER TABLE roles
  DROP CONSTRAINT IF EXISTS roles_application_status_check;

ALTER TABLE roles
  ADD CONSTRAINT roles_application_status_check
  CHECK (application_status IN ('unreviewed', 'applied', 'interviewing', 'offer', 'rejected', 'skipped'));

CREATE INDEX IF NOT EXISTS idx_roles_application_status ON roles(application_status);
