# Cuadrada

Cuadrada is an AI-powered peer review system that helps researchers validate their work with instant feedback from three AI reviewers.

## Prerequisites

- **Rust** (1.70+): [rustup.rs](https://rustup.rs) - run `rustup default stable` if needed
- **Docker** (for PostgreSQL)
- **Anthropic API key** (for Claude AI reviews)

## Quick Start

1. **Copy environment file:**
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env`** and set your `CLAUDE_API_KEY`

3. **Start everything:**
   ```bash
   ./start.sh
   ```

The script will:
- Start PostgreSQL in Docker
- Run database migrations
- Start the Cuadrada backend on http://localhost:5001

## Manual Setup

If you prefer to run components separately:

```bash
# 1. Start PostgreSQL
docker compose up -d postgres

# 2. Wait for DB, then run migrations (optional - app runs them on startup)
sqlx migrate run

# 3. Create .env with DATABASE_URL and CLAUDE_API_KEY

# 4. Run the app
cargo run
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgres://cuadrada:cuadrada_dev@localhost:5432/cuadrada` |
| `CLAUDE_API_KEY` | Anthropic API key for Claude | Required |
| `UPLOAD_FOLDER` | Directory for uploaded PDFs | `uploads` |
| `RESULTS_FOLDER` | Directory for generated files | `results` |
| `HOST` | Server bind address | `0.0.0.0` |
| `PORT` | Server port | `5001` |

## Certificate Generation

PDF certificates require system fonts. On Ubuntu/Debian:
```bash
sudo apt install fonts-liberation
```

## Project Structure

```
cuadrada/
├── Cargo.toml
├── docker-compose.yml
├── start.sh           # Unified startup script
├── migrations/        # SQL migrations
├── src/
│   ├── main.rs
│   ├── config.rs
│   ├── db/            # Database layer
│   ├── routes/        # HTTP handlers
│   ├── agents/        # Claude API client
│   ├── pdf/           # Certificate generation
│   └── storage/       # File utilities
├── templates/         # HTML templates (Tera)
└── static/            # JS, CSS, images
```

## License

Proprietary - Syndicate Laboratories
