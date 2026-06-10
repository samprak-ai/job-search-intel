-- Application outcomes: the RETURN PATH for the scoring loop.
--
-- Captures what actually happened after Sam engaged with a role (applied,
-- interviewed, offer, rejected, ghosted, skipped). This is the ground-truth
-- dataset that lets us later calibrate the scoring rubric: predicted match_tier
-- / overall_score (snapshotted at log time) vs. real outcome.
--
-- One row per role (UNIQUE role_id), upserted as the application progresses —
-- `status` reflects the furthest stage reached.
--
-- Run this in the Supabase SQL Editor.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'application_outcome_status') THEN
        CREATE TYPE application_outcome_status AS ENUM (
            'applied',
            'interview',
            'offer',
            'rejected',
            'ghosted',
            'skipped'
        );
    END IF;
END$$;

CREATE TABLE IF NOT EXISTS application_outcomes (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id                 uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE UNIQUE,
    status                  application_outcome_status NOT NULL,
    notes                   text,
    outcome_date            date NOT NULL DEFAULT current_date,

    -- Prediction snapshot, captured the first time an outcome is logged for the
    -- role. Frozen here so later rescoring of the role doesn't rewrite history —
    -- this is what the system predicted at the moment Sam acted on it.
    predicted_match_tier    text,
    predicted_overall_score integer,

    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_application_outcomes_status
    ON application_outcomes(status);

CREATE INDEX IF NOT EXISTS idx_application_outcomes_role_id
    ON application_outcomes(role_id);

-- Auto-bump updated_at on every UPDATE (mirrors application_packages)
CREATE OR REPLACE FUNCTION application_outcomes_touch_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_application_outcomes_touch_updated_at ON application_outcomes;
CREATE TRIGGER trg_application_outcomes_touch_updated_at
    BEFORE UPDATE ON application_outcomes
    FOR EACH ROW
    EXECUTE FUNCTION application_outcomes_touch_updated_at();

-- RLS: single-user app; RLS enabled with no public policies — only the service_role backend can access (the anon key is locked out).
ALTER TABLE application_outcomes ENABLE ROW LEVEL SECURITY;
