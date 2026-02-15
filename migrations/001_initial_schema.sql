-- Cuadrada initial schema (no auth - anonymous submissions)
-- Run with: sqlx migrate run

CREATE TABLE IF NOT EXISTS submissions (
    id SERIAL PRIMARY KEY,
    submission_id TEXT UNIQUE NOT NULL,
    paper_title TEXT,
    filename TEXT,
    file_path TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processing_complete BOOLEAN DEFAULT FALSE,
    all_accepted BOOLEAN DEFAULT FALSE,
    error TEXT,
    certificate_filename TEXT
);

CREATE TABLE IF NOT EXISTS review_results (
    id SERIAL PRIMARY KEY,
    submission_id TEXT NOT NULL REFERENCES submissions(submission_id) ON DELETE CASCADE,
    reviewer_name TEXT NOT NULL,
    decision TEXT NOT NULL,
    summary TEXT,
    full_review TEXT,
    model_used TEXT,
    file_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_submissions_submission_id ON submissions(submission_id);
CREATE INDEX idx_review_results_submission_id ON review_results(submission_id);
