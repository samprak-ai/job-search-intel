-- Add a posted_level column to roles for the posted seniority level chip when
-- the board exposes one (Google Careers renders "Mid"/"Advanced", etc.). The
-- posted level is authoritative for seniority_fit while titles can mislead
-- (e.g. "Associate Principal" is tagged Mid). 'Mid' is below Sam's L6;
-- 'Advanced' is at/above. (L33)
--
-- Historical rows get NULL (no silent backfill) — re-scoring is manual.

ALTER TABLE public.roles ADD COLUMN IF NOT EXISTS posted_level text;