-- Resume tailoring results per role
-- Stores Claude-generated resume prioritization advice for each role

CREATE TABLE IF NOT EXISTS resume_tailors (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    role_id uuid REFERENCES roles(id) ON DELETE CASCADE,
    tailoring jsonb NOT NULL,
    created_at timestamptz DEFAULT now(),
    UNIQUE(role_id)
);

CREATE INDEX IF NOT EXISTS idx_resume_tailors_role_id ON resume_tailors(role_id);
