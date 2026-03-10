-- Job Search Intelligence — Supabase Schema
-- Run this in the Supabase SQL Editor to create all tables

-- Discovered job postings
create table if not exists roles (
  id uuid primary key default gen_random_uuid(),
  company text not null,
  title text not null,
  url text unique not null,
  source text, -- e.g. 'greenhouse', 'lever', 'linkedin'
  raw_jd text,
  date_found timestamp with time zone default now(),
  created_at timestamp with time zone default now()
);

-- Match scoring results
create table if not exists role_scores (
  id uuid primary key default gen_random_uuid(),
  role_id uuid references roles(id) on delete cascade not null,
  match_tier text not null check (match_tier in ('Strong', 'Worth Applying', 'Stretch', 'Skip')),
  overall_score numeric,
  dimension_scores jsonb, -- { domain_fit, technical_fit, seniority_fit, role_type_fit, h1b_likelihood }
  rationale text,
  gaps text[],
  cover_letter_angles text[],
  scored_at timestamp with time zone default now(),
  created_at timestamp with time zone default now()
);

-- Interview intel summaries per company/role type
create table if not exists interview_intel (
  id uuid primary key default gen_random_uuid(),
  company text not null,
  role_type text not null,
  interview_structure text,
  question_themes text[],
  emphasis_areas text[],
  culture_signals text[],
  raw_sources jsonb, -- store source URLs/snippets used
  fetched_at timestamp with time zone default now(),
  created_at timestamp with time zone default now(),
  unique (company, role_type)
);

-- Phase 2: Forge session configs linked to roles
create table if not exists sessions (
  id uuid primary key default gen_random_uuid(),
  role_id uuid references roles(id) on delete cascade not null,
  session_config jsonb not null,
  status text default 'pending' check (status in ('pending', 'active', 'completed')),
  created_at timestamp with time zone default now()
);

-- Indexes for common queries
create index if not exists idx_roles_company on roles(company);
create index if not exists idx_roles_date_found on roles(date_found desc);
create index if not exists idx_role_scores_role_id on role_scores(role_id);
create index if not exists idx_role_scores_match_tier on role_scores(match_tier);
create index if not exists idx_interview_intel_company on interview_intel(company);
create index if not exists idx_sessions_role_id on sessions(role_id);
