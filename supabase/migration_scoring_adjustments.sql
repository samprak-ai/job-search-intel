-- Scoring adjustments: approved calibration notes from the /reflect loop.
--
-- This is the *persistent* source of truth for one-click "approve" — the
-- backend runs on Railway, so runtime writes to config/scoring_adjustments.json
-- wouldn't survive a redeploy. The JSON file remains as an optional manual /
-- versioned override; load_scoring_adjustments() merges file + active rows here.
--
-- scope = 'global' (applies to every role) or a company name (applies only to it).
--
-- Run this in the Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS scoring_adjustments (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scope         text NOT NULL,
    note          text NOT NULL,
    source        text NOT NULL DEFAULT 'reflection',  -- reflection | manual
    source_gap_id uuid REFERENCES detected_gaps(id) ON DELETE SET NULL,
    active        boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scoring_adjustments_scope ON scoring_adjustments(scope);
CREATE INDEX IF NOT EXISTS idx_scoring_adjustments_active ON scoring_adjustments(active);

ALTER TABLE scoring_adjustments DISABLE ROW LEVEL SECURITY;
