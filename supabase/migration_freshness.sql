-- Freshness check columns for stale role detection
-- Run this in the Supabase SQL Editor

ALTER TABLE roles
  ADD COLUMN IF NOT EXISTS is_live boolean DEFAULT true;

ALTER TABLE roles
  ADD COLUMN IF NOT EXISTS last_checked_at timestamptz;
