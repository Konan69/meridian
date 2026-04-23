#!/bin/bash
# Meridian — start all services
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDS=()

pick_js_pm() {
	if command -v pnpm >/dev/null 2>&1; then
		echo "pnpm"
	elif command -v bun >/dev/null 2>&1; then
		echo "bun"
	else
		echo "npm"
	fi
}

JS_PM="$(pick_js_pm)"

js_install() {
	local workdir="$1"
	if [ -d "$workdir/node_modules" ]; then
		case "$JS_PM" in
			pnpm)
				if [ -f "$workdir/node_modules/.modules.yaml" ]; then
					return 0
				fi
				rm -rf "$workdir/node_modules"
				;;
			bun|npm)
				return 0
				;;
		esac
	fi
	case "$JS_PM" in
		bun)
			(
				cd "$workdir"
				bun install >/dev/null
			)
			;;
		pnpm)
			(
				cd "$workdir"
				pnpm install >/dev/null
			)
			;;
		*)
			(
				cd "$workdir"
				npm install >/dev/null
			)
			;;
	esac
}

js_run() {
	local workdir="$1"
	local script="$2"
	case "$JS_PM" in
		bun)
			(
				cd "$workdir"
				bun run "$script"
			)
			;;
		pnpm)
			(
				cd "$workdir"
				pnpm run "$script"
			)
			;;
		*)
			(
				cd "$workdir"
				npm run "$script"
			)
			;;
	esac
}

ensure_ap2_env() {
	if command -v uv >/dev/null 2>&1; then
		(
			cd "$SCRIPT_DIR/services/ap2"
			uv sync >/dev/null
		)
	else
		local venv_dir="$SCRIPT_DIR/services/ap2/.venv"
		if [ ! -x "$venv_dir/bin/python3" ]; then
			python3 -m venv "$venv_dir"
		fi
		if [ -x "$venv_dir/bin/meridian-ap2-service" ]; then
			return 0
		fi
		(
			cd "$SCRIPT_DIR/services/ap2"
			"$venv_dir/bin/pip" install -e . >/dev/null
		)
	fi
}

ap2_start_cmd() {
	if command -v uv >/dev/null 2>&1; then
		echo "PORT=3040 uv run meridian-ap2-service"
	else
		echo "PORT=3040 $SCRIPT_DIR/services/ap2/.venv/bin/meridian-ap2-service"
	fi
}

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

report_atxp_runtime() {
	local health_json
	health_json="$(curl -fsS http://localhost:3010/health 2>/dev/null || true)"
	if [ -z "$health_json" ]; then
		return 0
	fi
	ATXP_HEALTH_JSON="$health_json" python3 - <<'PY'
import json
import os

raw = os.environ.get("ATXP_HEALTH_JSON", "")
if not raw:
    raise SystemExit(0)

try:
    payload = json.loads(raw)
except json.JSONDecodeError:
    raise SystemExit(0)

if payload.get("supportsDirectSettle") is False:
    reason = payload.get("runtimeReadyReason", "ATXP direct settle is unavailable")
    print(f"    ATXP runtime note: {reason}")
PY
}

ensure_port_free() {
	local port="$1"
	local label="$2"
	if command -v lsof >/dev/null 2>&1; then
		local listeners
		listeners="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
		if [ -n "$listeners" ]; then
			echo "    $label cannot start: port $port is already in use"
			echo "$listeners"
			return 1
		fi
	fi
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
echo "Using JS package manager: $JS_PM"

echo "[1/7] Building provider services..."
for service in cdp stripe atxp; do
	js_install "$SCRIPT_DIR/services/$service"
	js_run "$SCRIPT_DIR/services/$service" build >/dev/null
done
ensure_ap2_env

echo "[2/7] Starting CDP service on :3030..."
ensure_port_free 3030 "CDP"
start_bg "set -a; source ../../.env; set +a; PORT=3030 node dist/index.js" "$SCRIPT_DIR/services/cdp"
wait_for_http "http://localhost:3030/health" "CDP"

echo "[3/7] Starting Stripe service on :3020..."
ensure_port_free 3020 "Stripe"
start_bg "set -a; source ../../.env; set +a; PORT=3020 node dist/index.js" "$SCRIPT_DIR/services/stripe"
wait_for_http "http://localhost:3020/health" "Stripe"

echo "[4/7] Starting ATXP service on :3010..."
ensure_port_free 3010 "ATXP"
start_bg "set -a; source ../../.env; set +a; PORT=3010 node dist/index.js" "$SCRIPT_DIR/services/atxp"
wait_for_http "http://localhost:3010/health" "ATXP"
report_atxp_runtime

echo "[5/7] Starting AP2 service on :3040..."
ensure_port_free 3040 "AP2"
start_bg "set -a; source ../../.env; set +a; $(ap2_start_cmd)" "$SCRIPT_DIR/services/ap2"
wait_for_http "http://localhost:3040/health" "AP2"

echo "[6/7] Building and starting commerce engine on :4080..."
(
	cd "$SCRIPT_DIR/engine"
	cargo build >/dev/null
)
ensure_port_free 4080 "Engine"
start_bg "set -a; source ../.env; set +a; ./target/debug/meridian-engine --port 4080" "$SCRIPT_DIR/engine"
wait_for_http "http://localhost:4080/health" "Engine"

echo "[7/7] Starting frontend on :5173..."
ensure_port_free 5173 "Frontend"
start_bg "$JS_PM run dev" "$SCRIPT_DIR/web"
wait_for_http "http://localhost:5173" "Frontend"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Meridian is running"
echo "  CDP:      http://localhost:3030"
echo "  Stripe:   http://localhost:3020"
echo "  ATXP:     http://localhost:3010"
echo "  Engine:   http://localhost:4080"
echo "  Frontend: http://localhost:5173"
echo "  Capabilities: curl http://localhost:4080/capabilities"
echo "  ATXP funding: curl http://localhost:3010/funding"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Run simulation:"
echo "  cd sim && .venv/bin/python3 -m sim.engine"
echo ""
echo "Press Ctrl+C to stop all services"

trap 'kill "${PIDS[@]}" 2>/dev/null || true' EXIT INT TERM
wait
