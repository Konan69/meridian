#!/bin/bash
# Meridian — start all services
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "━━━ Meridian ━━━"
echo ""

# Build Rust engine
echo "[1/3] Building commerce engine..."
cd "$SCRIPT_DIR/engine"
cargo build --release 2>&1 | tail -1

# Start engine in background
echo "[2/3] Starting commerce engine on :4080..."
cargo run --release -- --port 4080 &
ENGINE_PID=$!
sleep 1

# Start SvelteKit dev server
echo "[3/3] Starting frontend on :5173..."
cd "$SCRIPT_DIR/web"
npm run dev &
WEB_PID=$!

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Meridian is running"
echo "  Engine:   http://localhost:4080"
echo "  Frontend: http://localhost:5173"
echo "  Protocols: ACP, AP2, x402, MPP, ATXP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Run simulation:"
echo "  cd sim && .venv/bin/python -m sim.engine"
echo ""
echo "Press Ctrl+C to stop all services"

trap "kill $ENGINE_PID $WEB_PID 2>/dev/null" EXIT INT TERM
wait
