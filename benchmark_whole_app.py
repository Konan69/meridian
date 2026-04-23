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
PASS_SCORE_FLOOR = 0.82
SPEED_SCORE_WEIGHT = 0.18

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


def merge_trace_metadata(*items: dict[str, Any] | None) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    for item in items:
        if not item:
            continue
        merged.update(item)
    return merged or None


def shared_cache_root() -> Path:
    if os.environ.get("XDG_CACHE_HOME"):
        return Path(os.environ["XDG_CACHE_HOME"]) / "meridian-evo-bench"
    return Path(os.environ.get("HOME", "/tmp")) / ".cache" / "meridian-evo-bench"


def python_cache_root() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", "/tmp")) / "meridian-evo-bench"


def pnpm_cached_install_command(after_install: str) -> str:
    return (
        'CACHE_ROOT="${XDG_CACHE_HOME:-${HOME:-/tmp}/.cache}/meridian-evo-bench" && '
        'PNPM_STORE_DIR="$CACHE_ROOT/pnpm-store-v10" && '
        'pnpm install --store-dir "$PNPM_STORE_DIR" --frozen-lockfile --prefer-offline --ignore-scripts && '
        f"{after_install}"
    )


def cargo_cached_test_command() -> str:
    return (
        'CACHE_ROOT="${XDG_CACHE_HOME:-${HOME:-/tmp}/.cache}/meridian-evo-bench" && '
        'mkdir -p "$CACHE_ROOT" && '
        'RUSTC_KEY="$(rustc -Vv | sha256sum | cut -d " " -f 1)" && '
        'DEPS_KEY="$(sha256sum engine/Cargo.toml engine/Cargo.lock | sha256sum | cut -d " " -f 1)" && '
        'SHORT_KEY="$(printf "%s-%s" "$RUSTC_KEY" "$DEPS_KEY" | sha256sum | cut -c 1-16)" && '
        'CARGO_TARGET_DIR="$CACHE_ROOT/cargo-target-$SHORT_KEY" && '
        'LOCK_FILE="$CACHE_ROOT/cargo-target-$SHORT_KEY.lock" && '
        'echo "cargo target cache key=$SHORT_KEY dir=$CARGO_TARGET_DIR" && '
        'flock "$LOCK_FILE" env CARGO_TARGET_DIR="$CARGO_TARGET_DIR" '
        'cargo test --quiet --manifest-path engine/Cargo.toml'
    )


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def command_trace_metadata(
    root: Path,
    task_id: str,
    command: str,
    command_cwd: Path,
    *,
    target_seconds: float,
    timeout: int,
) -> dict[str, Any]:
    return {
        "execution": {
            "kind": "shell_command_contract",
            "task_id": task_id,
            "cwd": rel(root, command_cwd),
            "timeout_seconds": timeout,
            "target_seconds": target_seconds,
            "command": command,
            "score_policy": {
                "passed_returncode_required": 0,
                "pass_score_floor": PASS_SCORE_FLOOR,
                "speed_score_weight": SPEED_SCORE_WEIGHT,
                "speed_bonus_target_seconds": target_seconds,
                "failed_command_score": 0.0,
            },
        }
    }


def pnpm_trace_metadata(root: Path, package_root: Path, validation_commands: list[str]) -> dict[str, Any]:
    return {
        "validation": {
            "kind": "pnpm_frozen_build_pipeline",
            "package_root": rel(root, package_root),
            "required_phases": ["install", *validation_commands],
            "install_command": "pnpm install --store-dir $PNPM_STORE_DIR --frozen-lockfile --prefer-offline --ignore-scripts",
            "validation_commands": validation_commands,
            "cache_note": "The shared pnpm store may change elapsed time, but the install and validation commands still run.",
        },
        "cache": {
            "kind": "pnpm_store",
            "store_dir": str(shared_cache_root() / "pnpm-store-v10"),
            "key_inputs": [
                rel(root, package_root / "package.json"),
                rel(root, package_root / "pnpm-lock.yaml"),
                "pnpm store content hash",
            ],
            "install_flags": [
                "--frozen-lockfile",
                "--prefer-offline",
                "--ignore-scripts",
            ],
        }
    }


def cargo_trace_metadata(root: Path) -> dict[str, Any]:
    cache_root = shared_cache_root()
    return {
        "validation": {
            "kind": "cargo_test_pipeline",
            "manifest": rel(root, root / "engine" / "Cargo.toml"),
            "validation_commands": ["cargo test --quiet --manifest-path engine/Cargo.toml"],
            "cache_note": "The keyed target dir may change elapsed time, but cargo still compiles/tests the engine crate.",
        },
        "cache": {
            "kind": "cargo_target",
            "target_dir_pattern": str(cache_root / "cargo-target-<short-key>"),
            "lock_file_pattern": str(cache_root / "cargo-target-<short-key>.lock"),
            "key_inputs": [
                "rustc -Vv",
                rel(root, root / "engine" / "Cargo.toml"),
                rel(root, root / "engine" / "Cargo.lock"),
            ],
        }
    }


def python_sim_trace_metadata(root: Path) -> dict[str, Any]:
    cache_root = python_cache_root()
    return {
        "validation": {
            "kind": "python_sim_pytest_pipeline",
            "package_root": "sim",
            "validation_commands": [
                "python3 -m venv when dependency cache marker is missing",
                "python3 -m pip install pytest dependencies when marker is missing",
                "python3 -m pytest tests/test_economy.py tests/test_engine.py::test_agent_generation tests/test_engine.py::test_scenarios -q",
            ],
            "cache_note": "The keyed dependency venv may skip reinstalling wheels, but pytest still runs.",
        },
        "cache": {
            "kind": "python_sim_dependency_venv",
            "venv_pattern": str(cache_root / "python-sim-venv-<py-tag>-<short-key>"),
            "pip_cache_dir": str(cache_root / "pip-cache"),
            "ready_marker_pattern": ".ready-<short-key>",
            "key_inputs": [
                "sys.implementation.cache_tag",
                rel(root, root / "sim" / "pyproject.toml"),
                rel(root, root / "sim" / "uv.lock"),
            ],
        }
    }


def run_command(
    root: Path,
    task_id: str,
    command: str,
    *,
    cwd: Path | None = None,
    timeout: int = 180,
    target_seconds: float = 30.0,
    trace_metadata: dict[str, Any] | None = None,
) -> float:
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
    command_cwd = cwd or root
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    started = time.perf_counter()
    full_trace_metadata = merge_trace_metadata(
        command_trace_metadata(
            root,
            task_id,
            command,
            command_cwd,
            target_seconds=target_seconds,
            timeout=timeout,
        ),
        trace_metadata,
    )
    try:
        result = subprocess.run(
            command,
            cwd=command_cwd,
            shell=True,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - started
        passed = result.returncode == 0
        time_score = min(1.0, target_seconds / max(elapsed, 0.001))
        score = (PASS_SCORE_FLOOR + SPEED_SCORE_WEIGHT * time_score) if passed else 0.0
        log_task(
            task_id,
            score,
            summary=f"{'pass' if passed else 'fail'} in {elapsed:.2f}s",
            failure_reason=None if passed else f"exit {result.returncode}",
            log=[
                {"stream": "stdout", "text": tail(result.stdout)},
                {"stream": "stderr", "text": tail(result.stderr)},
            ],
            started_at=started_at,
            elapsed_seconds=round(elapsed, 3),
            returncode=result.returncode,
            command_context={
                "cwd": str(command_cwd),
                "timeout_seconds": timeout,
                "target_seconds": target_seconds,
                "shell": True,
                "command": command,
            },
            trace_metadata=full_trace_metadata,
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
            started_at=started_at,
            elapsed_seconds=round(elapsed, 3),
            command_context={
                "cwd": str(command_cwd),
                "timeout_seconds": timeout,
                "target_seconds": target_seconds,
                "shell": True,
                "command": command,
            },
            trace_metadata=full_trace_metadata,
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


def static_contract_trace_metadata(
    required_files: list[str],
    contains_contracts: list[tuple[str, list[str]]],
) -> dict[str, Any]:
    return {
        "validation": {
            "kind": "static_contracts",
            "required_file_count": len(required_files),
            "required_files": required_files,
            "contains_contracts": [
                {
                    "path": path,
                    "needle_count": len(needles),
                    "needles": needles,
                }
                for path, needles in contains_contracts
            ],
        }
    }


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

    contains_contracts = [
        (
            "run.sh",
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
        ),
        (
            "docs/funding.md",
            [
                "treasury recycling",
                "/evm/transfer-usdc",
                "/evm/transfer-native",
                "CDP treasury recycling",
            ],
        ),
        (
            "services/cdp/src/index.ts",
            [
                'app.post("/evm/transfer-usdc"',
                'app.post("/evm/transfer-native"',
                "BASE_SEPOLIA_USDC",
                "encodeErc20Transfer",
                "treasury USDC transfers only support base-sepolia",
                "treasury native transfers only support base-sepolia",
            ],
        ),
        (
            "services/atxp/src/cdpBaseSepoliaAccount.ts",
            [
                "ATXP_CDP_TREASURY_ADDRESS",
                "ATXP_CDP_TREASURY_NATIVE_TOPUP",
                "ATXP_CDP_TREASURY_USDC_TOPUP_UNITS",
                "tryTreasuryTopUp",
                '"/evm/transfer-native"',
                '"/evm/transfer-usdc"',
                "falling back to faucet",
            ],
        ),
        (
            "services/atxp/src/funding.ts",
            [
                "ATXP_CDP_TREASURY_ADDRESS",
                "/evm/transfer-native",
                "/evm/transfer-usdc",
                "Automatic cdp-base payments also try this treasury path before faucet fallback.",
            ],
        ),
        (
            "services/atxp/src/index.ts",
            [
                'app.get("/health"',
                'app.get("/funding"',
                'app.post("/atxp/authorize"',
                'app.post("/atxp/direct-transfer"',
                'app.post("/atxp/execute"',
                "runtimeStatusForPayerMode",
                "settleDirectTransfer",
            ],
        ),
        (
            "engine/src/protocols/atxp.rs",
            [
                "supports_direct_settle",
                "runtime_ready",
                "runtime_mode",
                "/atxp/authorize",
                "/atxp/direct-transfer",
                "/atxp/execute",
            ],
        ),
        (
            "web/src/routes/+layout.svelte",
            ["/funding"],
        ),
        (
            "web/src/routes/funding/+page.svelte",
            ["/evm/transfer-usdc", "/evm/transfer-native"],
        ),
        (
            "web/src/routes/api/funding/+server.ts",
            ["http://localhost:3010", "http://localhost:3030", "http://localhost:3040"],
        ),
        (
            "engine/src/routes/capabilities.rs",
            [
                "tokio::join!",
                "AtxpAdapter::health_status",
                "MppAdapter::health_status",
                "Ap2Adapter::health_status",
                "status.runtime_ready && status.integration == \"in_engine\"",
            ],
        ),
    ]
    for path, needles in contains_contracts:
        require_contains(root / path, needles, failures)

    score = 1.0 if not failures else max(0.0, 1.0 - len(failures) / 20.0)
    log_task(
        "static_contracts",
        score,
        summary="all contracts present" if not failures else f"{len(failures)} contract issues",
        failure_reason="; ".join(failures[:8]) if failures else None,
        failures=failures,
        trace_metadata=static_contract_trace_metadata(required_files, contains_contracts),
    )
    return score


def task_python_compile(root: Path) -> float:
    return run_command(
        root,
        "python_compile",
        "python3 -m compileall -q sim/sim services/ap2/src",
        timeout=60,
        target_seconds=4,
        trace_metadata={
            "validation": {
                "kind": "python_compileall",
                "paths": ["sim/sim", "services/ap2/src"],
                "validation_commands": ["python3 -m compileall -q sim/sim services/ap2/src"],
                "cache_note": "No dependency cache is used; this is a direct syntax/import-bytecode compile check.",
            }
        },
    )


def task_python_tests(root: Path) -> float:
    return run_command(
        root,
        "python_sim_tests",
        'CACHE_ROOT="${XDG_CACHE_HOME:-/tmp}/meridian-evo-bench" && '
        'PIP_CACHE_DIR="$CACHE_ROOT/pip-cache" && export PIP_CACHE_DIR && '
        'PY_TAG="$(python3 -c \'import sys; print(sys.implementation.cache_tag)\')" && '
        'DEPS_KEY="$(sha256sum pyproject.toml uv.lock | sha256sum | cut -d " " -f 1)" && '
        'SHORT_KEY="$(printf "%s" "$DEPS_KEY" | cut -c 1-16)" && '
        'VENVDIR="$CACHE_ROOT/python-sim-venv-$PY_TAG-$SHORT_KEY" && '
        'READY="$VENVDIR/.ready-$SHORT_KEY" && '
        'if [ ! -f "$READY" ]; then '
        'rm -rf "$VENVDIR" && '
        'python3 -m venv "$VENVDIR" && '
        '"$VENVDIR/bin/python3" -m pip install -q --disable-pip-version-check '
        '--prefer-binary "aiohttp>=3.9.0" "pytest>=8.0" "pytest-asyncio>=0.23" && '
        'touch "$READY"; '
        'fi && '
        'PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}" "$VENVDIR/bin/python3" -m pytest tests/test_economy.py tests/test_engine.py::test_agent_generation tests/test_engine.py::test_scenarios -q',
        cwd=root / "sim",
        timeout=120,
        target_seconds=14,
        trace_metadata=python_sim_trace_metadata(root),
    )


def task_rust_tests(root: Path) -> float:
    return run_command(
        root,
        "rust_engine_tests",
        cargo_cached_test_command(),
        timeout=240,
        target_seconds=70,
        trace_metadata=cargo_trace_metadata(root),
    )


def task_service_builds(root: Path) -> float:
    scores = []
    for service, target_seconds in [("cdp", 22), ("stripe", 22), ("atxp", 35)]:
        scores.append(
            run_command(
                root,
                f"service_build_{service}",
                pnpm_cached_install_command("pnpm run build"),
                cwd=root / "services" / service,
                timeout=180,
                target_seconds=target_seconds,
                trace_metadata=pnpm_trace_metadata(
                    root,
                    root / "services" / service,
                    ["pnpm run build"],
                ),
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
        pnpm_cached_install_command("pnpm run check && pnpm run build"),
        cwd=root / "web",
        timeout=240,
        target_seconds=70,
        trace_metadata=pnpm_trace_metadata(
            root,
            root / "web",
            ["pnpm run check", "pnpm run build"],
        ),
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
