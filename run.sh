#!/bin/bash
# Meridian — start all services
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDS=()

wait_for_http() {
	local url="$1"
	local label="$2"
	local attempts="${3:-60}"
	for ((i=1; i<=attempts; i++)); do
		if curl -fsS "$url" >/dev/null 2>&1; then
			echo "    $label ready"
			return 0
		fi
		sleep 1
	done
	echo "    $label failed to become ready: $url"
	return 1
}

start_bg() {
	local cmd="$1"
	local workdir="$2"
	(
		cd "$workdir"
		eval "$cmd"
	) &
	local pid=$!
	PIDS+=("$pid")
}

echo "━━━ Meridian ━━━"
echo ""

echo "[1/7] Building provider services..."
(
	cd "$SCRIPT_DIR/services/cdp"
	npm run build >/dev/null
)
(
	cd "$SCRIPT_DIR/services/stripe"
	npm run build >/dev/null
)
(
	cd "$SCRIPT_DIR/services/atxp"
	npm run build >/dev/null
)
(
	cd "$SCRIPT_DIR/services/ap2"
	uv sync >/dev/null
)

echo "[2/7] Starting CDP service on :3030..."
start_bg "set -a; source ../../.env; set +a; PORT=3030 node dist/index.js" "$SCRIPT_DIR/services/cdp"
wait_for_http "http://localhost:3030/health" "CDP"

echo "[3/7] Starting Stripe service on :3020..."
start_bg "set -a; source ../../.env; set +a; PORT=3020 node dist/index.js" "$SCRIPT_DIR/services/stripe"
wait_for_http "http://localhost:3020/health" "Stripe"

echo "[4/7] Starting ATXP service on :3010..."
start_bg "set -a; source ../../.env; set +a; PORT=3010 node dist/index.js" "$SCRIPT_DIR/services/atxp"
wait_for_http "http://localhost:3010/health" "ATXP"

echo "[5/7] Starting AP2 service on :3040..."
start_bg "set -a; source ../../.env; set +a; PORT=3040 uv run meridian-ap2-service" "$SCRIPT_DIR/services/ap2"
wait_for_http "http://localhost:3040/health" "AP2"

echo "[6/7] Building and starting commerce engine on :4080..."
(
	cd "$SCRIPT_DIR/engine"
	cargo build >/dev/null
)
start_bg "set -a; source ../.env; set +a; ./target/debug/meridian-engine --port 4080" "$SCRIPT_DIR/engine"
wait_for_http "http://localhost:4080/health" "Engine"

echo "[7/7] Starting frontend on :5173..."
start_bg "npm run dev" "$SCRIPT_DIR/web"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Meridian is running"
echo "  CDP:      http://localhost:3030"
echo "  Stripe:   http://localhost:3020"
echo "  ATXP:     http://localhost:3010"
echo "  Engine:   http://localhost:4080"
echo "  Frontend: http://localhost:5173"
echo "  Capabilities: curl http://localhost:4080/capabilities"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Run simulation:"
echo "  cd sim && .venv/bin/python -m sim.engine"
echo ""
echo "Press Ctrl+C to stop all services"

trap 'kill "${PIDS[@]}" 2>/dev/null || true' EXIT INT TERM
wait
