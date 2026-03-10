-- Migration: Update match_tier check constraint to support new tier names
-- Run this in the Supabase SQL Editor

-- Drop the old constraint
ALTER TABLE role_scores
  DROP CONSTRAINT IF EXISTS role_scores_match_tier_check;

-- Add new constraint with both old and new tier names (for backward compatibility)
ALTER TABLE role_scores
  ADD CONSTRAINT role_scores_match_tier_check
  CHECK (match_tier IN (
    'Perfect Match', 'Strong Match', 'Good Match', 'Possible Match', 'Unlikely Match',
    'Strong', 'Worth Applying', 'Stretch', 'Skip'
  ));
