#!/bin/bash

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Get the root directory of the project
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

log_info "Starting AegisGraph initialization and startup..."
log_info "Project root: $PROJECT_ROOT"

# Environment variables (can be overridden)
export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${PGUSER:-myuser}"
export PGPASSWORD="${PGPASSWORD:-mypassword}"
export PGDATABASE="${PGDATABASE:-postgres}"
export NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}"
export NEO4J_USER="${NEO4J_USER:-neo4j}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-12345678}"
export OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"

# ============================================================================
# 1. Check External Services
# ============================================================================
log_info "Checking external services..."

check_service() {
    local name=$1
    local url=$2
    if curl -s "$url" > /dev/null 2>&1; then
        log_success "$name is running"
        return 0
    else
        log_warn "$name may not be running at $url"
        return 1
    fi
}

check_service "Ollama" "$OLLAMA_URL" || log_warn "Ollama not responding. Make sure it's running: ollama serve"
check_service "Neo4j" "http://localhost:7474" || log_warn "Neo4j not responding. Make sure it's running."

# Check PostgreSQL
if psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -c "SELECT 1;" > /dev/null 2>&1; then
    log_success "PostgreSQL is running"
else
    log_error "PostgreSQL is not running or not accessible"
    log_info "Start PostgreSQL and try again"
    exit 1
fi

# ============================================================================
# 2. Initialize Python Virtual Environment
# ============================================================================
log_info "Setting up Python environment..."

if [ ! -d ".venv" ]; then
    log_info "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate
log_success "Virtual environment activated"

# Install dependencies
log_info "Installing Python dependencies..."
pip install -q -r core/requirements.txt
log_success "Python dependencies installed"

# ============================================================================
# 3. Initialize Database
# ============================================================================
log_info "Initializing PostgreSQL database..."

psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -f scripts/init_postgres.sql > /dev/null 2>&1
log_success "Database schema initialized"

# ============================================================================
# 4. Seed Initial Data
# ============================================================================
log_info "Seeding initial data..."

python scripts/seed_data.py > /dev/null 2>&1
log_success "Data seeded successfully"

# ============================================================================
# 5. Build Gateway (C++)
# ============================================================================
log_info "Building C++ gateway..."

if [ ! -d "gateway/build" ]; then
    log_info "Creating build directory..."
    mkdir -p gateway/build
fi

cd gateway/build

if ! cmake .. > /dev/null 2>&1; then
    log_error "CMake configuration failed"
    exit 1
fi

if ! make -j"$(sysctl -n hw.ncpu 2>/dev/null || echo 4)" > /dev/null 2>&1; then
    log_error "Build failed"
    exit 1
fi

cd "$PROJECT_ROOT"
log_success "Gateway built successfully"

# ============================================================================
# 6. Install Frontend Dependencies
# ============================================================================
log_info "Setting up frontend..."

if [ ! -d "frontend/node_modules" ]; then
    log_info "Installing frontend dependencies..."
    cd frontend
    npm install --silent
    cd "$PROJECT_ROOT"
fi

log_success "Frontend dependencies ready"

# ============================================================================
# 7. Start Services with Log Output Batching
# ============================================================================
log_info "Starting services..."

# Function to prefix output lines
prefix_output() {
    local prefix=$1
    while IFS= read -r line; do
        echo -e "${prefix}${line}${NC}"
    done
}

log_success "================================"
log_success "AegisGraph is now running!"
log_success "================================"
log_info "Frontend: http://localhost:3000"
log_info "FastAPI Core: http://localhost:8000"
log_info "FastAPI Docs: http://localhost:8000/docs"
log_info "C++ Gateway: http://localhost:8080 (default)"
log_info ""
log_info "Press Ctrl+C to stop all services"
log_info ""
log_info "Starting services (all output below):"
log_info "================================"

# Function to gracefully shutdown all services
cleanup() {
    log_warn ""
    log_warn "Shutting down services..."
    kill -TERM $GATEWAY_PID $CORE_PID $FRONTEND_PID 2>/dev/null || true
    pkill -P $$ 2>/dev/null || true
    wait $GATEWAY_PID $CORE_PID $FRONTEND_PID 2>/dev/null || true
    log_success "All services stopped"
}

trap cleanup EXIT INT TERM

# Start the gateway with output prefixing
log_info "Starting C++ gateway..."
./gateway/build/gateway > >(prefix_output "${BLUE}[GATEWAY]${NC} ") 2>&1 &
GATEWAY_PID=$!

# Give gateway time to start
sleep 2

# Start the FastAPI core server with output prefixing
log_info "Starting FastAPI core server..."
uvicorn core.app:app --host 0.0.0.0 --port 8000 --reload > >(prefix_output "${GREEN}[CORE]${NC} ") 2>&1 &
CORE_PID=$!

# Start the Next.js frontend with output prefixing
log_info "Starting Next.js frontend..."
cd frontend
npm run dev > >(prefix_output "${YELLOW}[FRONTEND]${NC} ") 2>&1 &
FRONTEND_PID=$!
cd "$PROJECT_ROOT"

log_info "All services started. Collecting logs..."
log_info "================================"
log_info ""

# ============================================================================
# 8. Keep Script Running and Collect All Output
# ============================================================================
# Wait for all processes
wait $GATEWAY_PID $CORE_PID $FRONTEND_PID
