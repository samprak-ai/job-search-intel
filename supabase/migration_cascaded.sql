-- Migration: Add department column for cascaded dashboard grouping
-- Run this in Supabase SQL Editor before using the backfill endpoint.

ALTER TABLE roles ADD COLUMN IF NOT EXISTS department text;
