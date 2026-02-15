# Cuadrada Refactor Plan

## Overview

This plan transforms Cuadrada from a Python/Flask application with Auth0 and Heroku into a streamlined Rust application with local PostgreSQL in Docker and no authentication.

## Requirements Summary

1. **Rewrite backend in Rust** - Replace Flask/Python with Rust web framework
2. **Remove Auth0 and Heroku** - No authentication, no cloud hosting dependencies
3. **Remove Windows setup scripts** - setup_venv.bat, deploy_heroku.bat, setup_and_run.bat
4. **PostgreSQL in Docker** - Local Postgres via Docker Compose (replacing Supabase)
5. **Unified startup script** - Single script to start database + backend

---

## Execution Order

### Phase 1: Infrastructure Setup
- Create `docker-compose.yml` with PostgreSQL service
- Create simplified database schema (submissions, reviews - no users/subscriptions)
- Create SQL migration files
- Create `.env.example` for configuration

### Phase 2: Rust Backend Structure
- Initialize Cargo project with workspace structure
- Add dependencies: axum, tokio, sqlx, reqwest, pdf-extract, printpdf, tera, tower-http, etc.
- Create module structure: main, routes, db, agents, storage, templates

### Phase 3: Core Rust Implementation
- **Database layer**: sqlx with PostgreSQL connection pool
- **PDF extraction**: pdf-extract crate (replacing PyMuPDF)
- **Claude API client**: reqwest for Anthropic API calls (replacing anthropic Python SDK)
- **Review agent logic**: Port REVIEW_PROMPT and decision parsing from agents.py
- **File storage**: Local filesystem (uploads/, results/) - no Supabase
- **Background processing**: tokio spawn for async review processing
- **PDF generation**: printpdf for certificates and review PDFs

### Phase 4: Web Layer
- **Routes**: GET /, POST /upload, GET /view_review_results/:id, GET /check_review_status/:id, GET /download/:filename, etc.
- **Templates**: Port HTML to Tera (index, results, summary) - merge login_landing + index (no auth)
- **Static files**: Serve JS, favicon from static/
- **Session**: In-memory or cookie-based submission_id tracking (no Auth0)

### Phase 5: Unified Startup
- Create `start.sh` that:
  1. Starts Docker PostgreSQL (docker-compose up -d)
  2. Waits for DB to be ready
  3. Runs migrations (sqlx migrate run)
  4. Starts Rust backend (cargo run)
- Ensure uploads/ and results/ directories are created

### Phase 6: Cleanup
- Delete: app.py, agents.py, supabase_db.py
- Delete: setup_venv.sh, setup_venv.bat, setup_and_run.bat, deploy_heroku.bat
- Delete: Procfile, runtime.txt, setup.py
- Delete: templates/auth_error.html, admin*.html, login_landing.html, logout.html
- Remove: Auth0, Stripe, Heroku, Supabase references from codebase
- Delete: requirements.txt (replaced by Cargo.toml)

### Phase 7: Documentation
- Rewrite README.md with new setup instructions
- Document environment variables (.env.example)
- Remove Heroku/Auth0 deployment sections

---

## Architecture After Refactor

```
cuadrada/
├── Cargo.toml
├── docker-compose.yml
├── .env.example
├── start.sh              # Unified startup
├── migrations/           # SQL migrations
├── src/
│   ├── main.rs
│   ├── config.rs
│   ├── db/
│   ├── routes/
│   ├── agents/           # Claude API client
│   ├── storage/          # Local file storage
│   └── templates/       # Tera templates
├── static/
│   └── js/
└── templates/            # HTML templates (Tera)
```

## Database Schema (Simplified)

```sql
-- submissions: tracks each paper upload
CREATE TABLE submissions (
    id SERIAL PRIMARY KEY,
    submission_id TEXT UNIQUE NOT NULL,
    paper_title TEXT,
    filename TEXT,
    file_path TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processing_complete BOOLEAN DEFAULT FALSE,
    all_accepted BOOLEAN DEFAULT FALSE,
    error TEXT
);

-- review_results: JSONB for each reviewer's output
CREATE TABLE review_results (
    id SERIAL PRIMARY KEY,
    submission_id TEXT REFERENCES submissions(submission_id),
    reviewer_name TEXT NOT NULL,
    decision TEXT,
    summary TEXT,
    full_review TEXT,
    model_used TEXT,
    file_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## Key Simplifications

- **No users**: Anonymous submissions only
- **No subscriptions**: Unlimited reviews
- **No Auth0**: Direct access to all pages
- **No Supabase**: Local Postgres + local file storage
- **No Heroku**: Run locally via start.sh
- **No admin panel**: Removed (was for user management)
