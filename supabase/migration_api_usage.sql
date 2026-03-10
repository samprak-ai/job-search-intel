-- Migration: API usage tracking for web search queries
-- Run this in the Supabase SQL Editor

CREATE TABLE IF NOT EXISTS api_usage (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    provider text NOT NULL,         -- 'serper' or 'brave'
    caller text NOT NULL,           -- 'discovery', 'intel', or 'unknown'
    query_preview text,             -- first 120 chars of query for debugging
    status text NOT NULL,           -- 'success' or 'error'
    result_count int DEFAULT 0,
    created_at timestamptz DEFAULT now()
);

-- Index for fast daily aggregation queries
CREATE INDEX IF NOT EXISTS idx_api_usage_created_at ON api_usage(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_usage_provider ON api_usage(provider);
