-- Add a location column to roles so discovery can persist each posting's
-- location and the scorer can weigh location fit (Sam: Seattle/Renton base,
-- open to SF Bay / NYC, H1B, US-remote OK). Fetchers populate it; build_scoring_
-- message() surfaces it; the LOCATION FIT rule in scoring.py uses it.
--
-- Run this in the Supabase SQL Editor (already applied via apply_migration).

ALTER TABLE public.roles ADD COLUMN IF NOT EXISTS location text;
