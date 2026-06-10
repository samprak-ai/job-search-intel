-- Enable Row-Level Security on every public table.
--
-- WHY: with RLS disabled, anyone holding the project's anon key (a publishable
-- credential) can read/write all data via PostgREST. Supabase's security advisor
-- flags this as a critical `rls_disabled_in_public` error.
--
-- HOW IT STAYS SAFE: the backend authenticates with the service_role key, which
-- BYPASSES RLS. So no policies are needed — enabling RLS with zero policies
-- denies the public anon/authenticated roles by default while the service_role
-- backend keeps full access.
--
-- PRECONDITION: the backend MUST be using the service_role key before this is
-- applied (set SUPABASE_SERVICE_KEY in Railway + local .env). If the backend is
-- still on the anon key when this runs, every query will be denied — the app
-- breaks. See config.get_supabase_client().
--
-- Run this in the Supabase SQL Editor (or via apply_migration) only after the
-- service key swap is live.

ALTER TABLE public.roles                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.role_scores           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.interview_intel       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sessions              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_packets   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.resume_tailors        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.api_usage             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_packages  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_outcomes  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.detected_gaps         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scoring_adjustments   ENABLE ROW LEVEL SECURITY;
