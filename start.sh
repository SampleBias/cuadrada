#!/bin/bash
# Cuadrada - Unified startup script
# Starts PostgreSQL in Docker, runs migrations, then starts the Rust backend

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Cuadrada Startup ==="

# Docker Compose command (v2 or v1)
DOCKER_COMPOSE="docker compose"
if ! $DOCKER_COMPOSE version &>/dev/null; then
    DOCKER_COMPOSE="docker-compose"
fi

# 1. Start PostgreSQL
echo "Starting PostgreSQL..."
$DOCKER_COMPOSE up -d postgres

# 2. Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL to be ready..."
for i in {1..30}; do
    if $DOCKER_COMPOSE exec -T postgres pg_isready -U cuadrada -d cuadrada 2>/dev/null; then
        echo "PostgreSQL is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "ERROR: PostgreSQL failed to start within 30 seconds"
        exit 1
    fi
    sleep 1
done

# 3. Load environment
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# 4. Run migrations (requires sqlx-cli: cargo install sqlx-cli)
echo "Running database migrations..."
if command -v sqlx &> /dev/null; then
    sqlx migrate run
else
    echo "Note: sqlx-cli not found. Migrations will run on first app start."
fi

# 5. Create directories
mkdir -p uploads results

# 6. Start the Rust backend
echo "Starting Cuadrada backend..."
cargo run
