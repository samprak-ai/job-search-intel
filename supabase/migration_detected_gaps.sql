-- Detected gaps: the auto-capture plane of the self-improvement loop.
--
-- Where LEARNINGS.md + selfcheck.py capture *engineering* regressions, this
-- table captures *runtime/product* gaps the system notices about itself:
--   - prediction_mismatch  — an outcome contradicted the score we predicted
--   - taste_mismatch       — scored high but Sam skipped it
--   - stale_high_score     — a Strong+ role went dead (possibly surfaced/emailed)
--   - manual               — a gap Sam logged by hand (e.g. "we missed this role")
--
-- The weekly /reflect pass reads open gaps + application_outcomes and proposes
-- tuning (new guards, rubric deltas, discovery keywords) for approval.
--
-- Run this in the Supabase SQL Editor.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'detected_gap_status') THEN
        CREATE TYPE detected_gap_status AS ENUM ('open', 'guarded', 'resolved', 'wontfix');
    END IF;
END$$;

CREATE TABLE IF NOT EXISTS detected_gaps (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gap_type     text NOT NULL,
    severity     text NOT NULL DEFAULT 'medium',          -- low | medium | high
    description  text NOT NULL,
    role_id      uuid REFERENCES roles(id) ON DELETE SET NULL,
    role_label   text,                                     -- "Title @ Company" snapshot; survives role deletion
    detail       jsonb,
    status       detected_gap_status NOT NULL DEFAULT 'open',
    source       text NOT NULL DEFAULT 'system',           -- system | manual
    detected_at  timestamptz NOT NULL DEFAULT now(),
    resolved_at  timestamptz
);

CREATE INDEX IF NOT EXISTS idx_detected_gaps_status ON detected_gaps(status);
CREATE INDEX IF NOT EXISTS idx_detected_gaps_type ON detected_gaps(gap_type);
CREATE INDEX IF NOT EXISTS idx_detected_gaps_detected_at ON detected_gaps(detected_at DESC);

ALTER TABLE detected_gaps ENABLE ROW LEVEL SECURITY;
