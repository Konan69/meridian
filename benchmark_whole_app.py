#!/usr/bin/env python3
"""Whole-app evo benchmark for Meridian.

The benchmark is intentionally offline: it checks build/test/runtime contracts
without starting live services or using credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_TRACES_DIR = Path(os.environ["EVO_TRACES_DIR"]) if os.environ.get("EVO_TRACES_DIR") else None
_EXPERIMENT_ID = os.environ.get("EVO_EXPERIMENT_ID", "unknown")
_SCORES: dict[str, float] = {}
_STARTED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")

if _TRACES_DIR:
    _TRACES_DIR.mkdir(parents=True, exist_ok=True)


def log_task(
    task_id: str,
    score: float,
    *,
    summary: str | None = None,
    failure_reason: str | None = None,
    log: list[Any] | None = None,
    **extra: Any,
) -> None:
    task_id = str(task_id)
    _SCORES[task_id] = score
    if _TRACES_DIR is None:
        return
    trace: dict[str, Any] = {
        "experiment_id": _EXPERIMENT_ID,
        "task_id": task_id,
        "status": "passed" if score >= 0.999 else "failed",
        "score": score,
        "ended_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if summary is not None:
        trace["summary"] = summary
    if failure_reason is not None:
        trace["failure_reason"] = failure_reason
    if log is not None:
        trace["log"] = log
    trace.update(extra)
    (_TRACES_DIR / f"task_{task_id}.json").write_text(
        json.dumps(trace, indent=2), encoding="utf-8"
    )


def write_result(score: float | None = None) -> float:
    if score is None:
        score = sum(_SCORES.values()) / len(_SCORES) if _SCORES else 0.0
    score = round(score, 4)
    print(
        json.dumps(
            {
                "score": score,
                "tasks": dict(_SCORES),
                "started_at": _STARTED_AT,
                "ended_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            indent=2,
        )
    )
    return score


def tail(text: str, limit: int = 5000) -> str:
    return text[-limit:] if len(text) > limit else text


def run_command(root: Path, task_id: str, command: str, *, cwd: Path | None = None, timeout: int = 180, target_seconds: float = 30.0) -> float:
    env = os.environ.copy()
    env.update(
        {
            "CI": "1",
            "CARGO_TERM_COLOR": "never",
            "NO_COLOR": "1",
            "PYTHONUNBUFFERED": "1",
            "SVELTEKIT_TELEMETRY_DISABLED": "1",
        }
    )
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=cwd or root,
            shell=True,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - started
        passed = result.returncode == 0
        time_score = min(1.0, target_seconds / max(elapsed, 0.001))
        score = (0.82 + 0.18 * time_score) if passed else 0.0
        log_task(
            task_id,
            score,
            summary=f"{'pass' if passed else 'fail'} in {elapsed:.2f}s",
            failure_reason=None if passed else f"exit {result.returncode}",
            log=[
                {"stream": "stdout", "text": tail(result.stdout)},
                {"stream": "stderr", "text": tail(result.stderr)},
            ],
            elapsed_seconds=round(elapsed, 3),
            returncode=result.returncode,
        )
        return score
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - started
        log_task(
            task_id,
            0.0,
            summary=f"timeout after {elapsed:.2f}s",
            failure_reason=f"timeout after {timeout}s",
            log=[
                {"stream": "stdout", "text": tail(exc.stdout or "")},
                {"stream": "stderr", "text": tail(exc.stderr or "")},
            ],
            elapsed_seconds=round(elapsed, 3),
        )
        return 0.0


def require_contains(path: Path, needles: list[str], failures: list[str]) -> None:
    if not path.exists():
        failures.append(f"missing {path}")
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    for needle in needles:
        if needle not in text:
            failures.append(f"{path}: missing {needle!r}")


def task_static_contracts(root: Path) -> float:
    failures: list[str] = []
    required_files = [
        "README.md",
        "docs/funding.md",
        "run.sh",
        "engine/Cargo.toml",
        "engine/Cargo.lock",
        "sim/pyproject.toml",
        "sim/uv.lock",
        "web/package.json",
        "web/pnpm-lock.yaml",
        "services/atxp/package.json",
        "services/atxp/pnpm-lock.yaml",
        "services/cdp/pnpm-lock.yaml",
        "services/stripe/pnpm-lock.yaml",
        "services/ap2/pyproject.toml",
        "services/ap2/uv.lock",
    ]
    for rel in required_files:
        if not (root / rel).exists():
            failures.append(f"missing {rel}")

    require_contains(
        root / "run.sh",
        [
            "Starting CDP service",
            "Starting Stripe service",
            "Starting ATXP service",
            "Starting AP2 service",
            "Building and starting commerce engine",
            "Starting frontend",
            "ATXP funding: curl http://localhost:3010/funding",
            "cd sim && .venv/bin/python3 -m sim.engine",
        ],
        failures,
    )
    require_contains(
        root / "docs/funding.md",
        [
            "treasury recycling",
            "/evm/transfer-usdc",
            "/evm/transfer-native",
            "CDP treasury recycling",
        ],
        failures,
    )
    require_contains(
        root / "services/cdp/src/index.ts",
        [
            'app.post("/evm/transfer-usdc"',
            'app.post("/evm/transfer-native"',
            "BASE_SEPOLIA_USDC",
            "encodeErc20Transfer",
            "treasury USDC transfers only support base-sepolia",
            "treasury native transfers only support base-sepolia",
        ],
        failures,
    )
    require_contains(
        root / "services/atxp/src/cdpBaseSepoliaAccount.ts",
        [
            "ATXP_CDP_TREASURY_ADDRESS",
            "ATXP_CDP_TREASURY_NATIVE_TOPUP",
            "ATXP_CDP_TREASURY_USDC_TOPUP_UNITS",
            "tryTreasuryTopUp",
            '"/evm/transfer-native"',
            '"/evm/transfer-usdc"',
            "falling back to faucet",
        ],
        failures,
    )
    require_contains(
        root / "services/atxp/src/index.ts",
        [
            'app.get("/health"',
            'app.get("/funding"',
            'app.post("/atxp/authorize"',
            'app.post("/atxp/direct-transfer"',
            'app.post("/atxp/execute"',
            "runtimeStatusForPayerMode",
            "settleDirectTransfer",
        ],
        failures,
    )
    require_contains(
        root / "engine/src/protocols/atxp.rs",
        [
            "supports_direct_settle",
            "runtime_ready",
            "runtime_mode",
            "/atxp/authorize",
            "/atxp/direct-transfer",
            "/atxp/execute",
        ],
        failures,
    )
    require_contains(
        root / "web/src/routes/+layout.svelte",
        ["/funding"],
        failures,
    )
    require_contains(
        root / "web/src/routes/funding/+page.svelte",
        ["/evm/transfer-usdc", "/evm/transfer-native"],
        failures,
    )
    require_contains(
        root / "web/src/routes/api/funding/+server.ts",
        ["http://localhost:3010", "http://localhost:3030", "http://localhost:3040"],
        failures,
    )
    require_contains(
        root / "engine/src/routes/capabilities.rs",
        [
            "tokio::join!",
            "AtxpAdapter::health_status",
            "MppAdapter::health_status",
            "Ap2Adapter::health_status",
            "status.runtime_ready && status.integration == \"in_engine\"",
        ],
        failures,
    )

    score = 1.0 if not failures else max(0.0, 1.0 - len(failures) / 20.0)
    log_task(
        "static_contracts",
        score,
        summary="all contracts present" if not failures else f"{len(failures)} contract issues",
        failure_reason="; ".join(failures[:8]) if failures else None,
        failures=failures,
    )
    return score


def task_python_compile(root: Path) -> float:
    return run_command(
        root,
        "python_compile",
        "python3 -m compileall -q sim/sim services/ap2/src",
        timeout=60,
        target_seconds=4,
    )


def task_python_tests(root: Path) -> float:
    return run_command(
        root,
        "python_sim_tests",
        'VENVDIR="${EVO_TRACES_DIR:-/tmp/meridian-evo-bench}/python-sim-venv" && '
        'if [ ! -f "$VENVDIR/.ready" ]; then '
        'python3 -m venv "$VENVDIR" && '
        '"$VENVDIR/bin/python3" -m pip install -q -e \'.[dev]\' && '
        'touch "$VENVDIR/.ready"; '
        'fi && '
        '"$VENVDIR/bin/python3" -m pytest tests/test_economy.py tests/test_engine.py::test_agent_generation tests/test_engine.py::test_scenarios -q',
        cwd=root / "sim",
        timeout=120,
        target_seconds=14,
    )


def task_rust_tests(root: Path) -> float:
    return run_command(
        root,
        "rust_engine_tests",
        "cargo test --quiet --manifest-path engine/Cargo.toml",
        timeout=240,
        target_seconds=70,
    )


def task_service_builds(root: Path) -> float:
    scores = []
    for service, target_seconds in [("cdp", 22), ("stripe", 22), ("atxp", 35)]:
        scores.append(
            run_command(
                root,
                f"service_build_{service}",
                "pnpm install --frozen-lockfile --prefer-offline --ignore-scripts && pnpm run build",
                cwd=root / "services" / service,
                timeout=180,
                target_seconds=target_seconds,
            )
        )
    score = sum(scores) / len(scores)
    log_task(
        "service_builds_summary",
        score,
        summary=f"mean service build score {score:.4f}",
        component_scores=scores,
    )
    return score


def task_web_check(root: Path) -> float:
    return run_command(
        root,
        "web_check_build",
        "pnpm install --frozen-lockfile --prefer-offline --ignore-scripts && pnpm run check && pnpm run build",
        cwd=root / "web",
        timeout=240,
        target_seconds=70,
    )


def run_benchmark(root: Path) -> float:
    scores = [
        task_static_contracts(root),
        task_python_compile(root),
        task_python_tests(root),
        task_rust_tests(root),
        task_service_builds(root),
        task_web_check(root),
    ]
    return write_result(sum(scores) / len(scores))


def run_gate(root: Path) -> float:
    scores = [
        task_static_contracts(root),
        task_python_compile(root),
    ]
    return write_result(sum(scores) / len(scores))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--profile", choices=["benchmark", "gate"], default="benchmark")
    parser.add_argument("--min-score", type=float)
    args = parser.parse_args()

    root = Path(args.target).resolve()
    if not root.is_dir():
        raise SystemExit(f"target must be the repository root directory, got {root}")

    score = run_gate(root) if args.profile == "gate" else run_benchmark(root)
    if args.min_score is not None and score < args.min_score:
        print(
            f"GATE FAIL: score {score:.4f} below minimum {args.min_score:.4f}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
