-- Email application-update log: idempotency + audit trail for the
-- inbox -> outcome -> Forge bridge (services/application_updates.py).
--
-- The daily Cowork scheduled task reads ATS reply emails and POSTs them to
-- /application-updates/ingest. Every processed message is recorded here keyed by
-- its Gmail message_id (UNIQUE), so re-running the task never double-processes a
-- message or double-fires a Forge session. It also serves as a human-readable
-- record of what was detected, what role it matched, and what changed.
--
-- Run this in the Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS email_application_updates (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id        text UNIQUE NOT NULL,
    from_address      text,
    subject           text,
    detected_company  text,
    detected_status   text,   -- confirmation | rejection | interview_invite | online_assessment | offer
    matched_role_id   uuid REFERENCES roles(id) ON DELETE SET NULL,
    applied_status    text,   -- the role.application_status we set (null = no write)
    forge_fired       boolean NOT NULL DEFAULT false,
    confidence        numeric,
    evidence          text,
    processed_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_email_updates_role
    ON email_application_updates(matched_role_id);
CREATE INDEX IF NOT EXISTS idx_email_updates_processed_at
    ON email_application_updates(processed_at DESC);

-- RLS: single-user app; RLS enabled with no public policies — only the
-- service_role backend can access (the anon key is locked out). Matches the
-- pattern in migration_application_outcomes.sql / migration_enable_rls.sql.
ALTER TABLE email_application_updates ENABLE ROW LEVEL SECURITY;
