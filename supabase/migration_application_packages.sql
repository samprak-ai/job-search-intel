-- Application packages: multi-stage agentic pipeline for Anthropic role applications.
-- Supersedes the abandoned `application_packets` table/feature.
--
-- Pipeline stages (status enum): gating → aligning → drafting → verifying →
--   self_healing → verifying again → awaiting_review | auto_sent (or skipped/failed).
--
-- Run this in the Supabase SQL Editor.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'application_package_status') THEN
        CREATE TYPE application_package_status AS ENUM (
            'pending',
            'gating',
            'aligning',
            'drafting',
            'verifying',
            'self_healing',
            'awaiting_review',
            'auto_sent',
            'skipped',
            'failed'
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'application_send_mode') THEN
        CREATE TYPE application_send_mode AS ENUM (
            'auto_sent',
            'review_requested'
        );
    END IF;
END$$;

CREATE TABLE IF NOT EXISTS application_packages (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id         uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE UNIQUE,
    status          application_package_status NOT NULL DEFAULT 'pending',

    -- Snapshots and intermediate artifacts (jsonb for flexibility)
    persona_used    jsonb,
    angles          jsonb,
    requirements    jsonb,
    artifact_paths  jsonb,
    findings_v1     jsonb,
    findings_v2     jsonb,
    self_healed     boolean NOT NULL DEFAULT FALSE,

    -- Delivery
    send_mode       application_send_mode,
    email_sent_at   timestamptz,

    -- Error tracking
    error           text,
    error_stage     text,

    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_application_packages_status
    ON application_packages(status);

CREATE INDEX IF NOT EXISTS idx_application_packages_created_at
    ON application_packages(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_application_packages_role_id
    ON application_packages(role_id);

-- Auto-bump updated_at on every UPDATE
CREATE OR REPLACE FUNCTION application_packages_touch_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_application_packages_touch_updated_at ON application_packages;
CREATE TRIGGER trg_application_packages_touch_updated_at
    BEFORE UPDATE ON application_packages
    FOR EACH ROW
    EXECUTE FUNCTION application_packages_touch_updated_at();

-- RLS: single-user app; disable RLS to match the pattern used by other tables
-- (roles, role_scores, etc.). The backend uses SUPABASE_KEY (service role)
-- so authorization happens at the API layer, not row-level.
ALTER TABLE application_packages DISABLE ROW LEVEL SECURITY;
