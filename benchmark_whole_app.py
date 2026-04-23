#!/usr/bin/env python3
"""Whole-app evo benchmark for Meridian.

The benchmark is intentionally offline: it checks build/test/runtime contracts
without starting live services or using credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
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


PNPM_DEPENDENCY_FIELDS = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
    "pnpm",
    "packageManager",
)


def file_digest(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_dependency_fingerprint(package_root: Path) -> str | None:
    package_json = package_root / "package.json"
    lockfile = package_root / "pnpm-lock.yaml"
    if not package_json.exists() or not lockfile.exists():
        return None
    try:
        package_data = json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    dependency_data = {
        field: package_data.get(field)
        for field in PNPM_DEPENDENCY_FIELDS
        if field in package_data
    }
    payload = {
        "dependencies": dependency_data,
        "lockfile": file_digest(lockfile),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def pnpm_store_dir_with_version() -> Path:
    return shared_cache_root() / "pnpm-store-v10" / "v10"


def modules_store_dir(node_modules: Path) -> str | None:
    modules_yaml = node_modules / ".modules.yaml"
    if not modules_yaml.exists():
        return None
    text = modules_yaml.read_text(encoding="utf-8", errors="replace")
    try:
        parsed = json.loads(text)
        value = parsed.get("storeDir")
        if isinstance(value, str):
            return value
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('"storeDir":') or stripped.startswith("storeDir:"):
            return stripped.split(":", 1)[1].strip().strip('",')
    return None


def evo_run_root(root: Path) -> Path | None:
    if root.parent.name == "worktrees" and root.parent.parent.name.startswith("run_"):
        return root.parent.parent
    return None


def candidate_worktree_roots(root: Path) -> list[Path]:
    candidates: list[Path] = []
    env_source = os.environ.get("MERIDIAN_NODE_MODULES_SOURCE_ROOT")
    if env_source:
        candidates.append(Path(env_source).expanduser().resolve())

    run_root = evo_run_root(root)
    if run_root is not None:
        worktrees = run_root / "worktrees"
        if worktrees.exists():
            candidates.extend(
                sorted(
                    (path for path in worktrees.iterdir() if path.is_dir()),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )
            )
        candidates.append(run_root.parent.parent)

    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved == root or resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def matching_node_modules_sources(root: Path, package_root: Path) -> list[Path]:
    try:
        package_rel = package_root.relative_to(root)
    except ValueError:
        return []
    target_fingerprint = package_dependency_fingerprint(package_root)
    if target_fingerprint is None:
        return []

    expected_store = str(pnpm_store_dir_with_version())
    sources: list[Path] = []
    for candidate_root in candidate_worktree_roots(root):
        candidate_package = candidate_root / package_rel
        candidate_node_modules = candidate_package / "node_modules"
        if not candidate_node_modules.exists():
            continue
        if package_dependency_fingerprint(candidate_package) != target_fingerprint:
            continue
        if modules_store_dir(candidate_node_modules) != expected_store:
            continue
        sources.append(candidate_node_modules)
    return sources


def seed_node_modules(root: Path, package_root: Path) -> dict[str, Any]:
    node_modules = package_root / "node_modules"
    expected_store = str(pnpm_store_dir_with_version())
    package_label = rel(root, package_root)
    existing_store = modules_store_dir(node_modules)
    if node_modules.exists() and existing_store == expected_store:
        return {
            "status": "present",
            "package_root": package_label,
            "store_dir": expected_store,
        }

    if node_modules.exists():
        shutil.rmtree(node_modules)

    for source in matching_node_modules_sources(root, package_root):
        started = time.perf_counter()
        hardlink_result = subprocess.run(
            ["cp", "-a", "-l", str(source), str(node_modules)],
            capture_output=True,
            text=True,
        )
        copy_mode = "hardlink"
        if hardlink_result.returncode != 0:
            if node_modules.exists():
                shutil.rmtree(node_modules)
            hardlink_result = subprocess.run(
                ["cp", "-a", str(source), str(node_modules)],
                capture_output=True,
                text=True,
            )
            copy_mode = "copy"
        elapsed = time.perf_counter() - started
        if hardlink_result.returncode == 0 and modules_store_dir(node_modules) == expected_store:
            return {
                "status": "seeded",
                "package_root": package_label,
                "source": str(source),
                "store_dir": expected_store,
                "copy_mode": copy_mode,
                "elapsed_seconds": round(elapsed, 3),
            }
        if node_modules.exists():
            shutil.rmtree(node_modules)

    return {
        "status": "miss",
        "package_root": package_label,
        "store_dir": expected_store,
    }


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


def pnpm_trace_metadata(
    root: Path,
    package_root: Path,
    validation_commands: list[str],
    node_modules_seed: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
            "node_modules_seed": node_modules_seed,
        }
    }


SERVICE_OFFLINE_COVERAGE: dict[str, dict[str, list[str]]] = {
    "cdp": {
        "test_files": [
            "services/cdp/src/signMessage.test.ts",
            "services/cdp/src/sendTransaction.test.ts",
            "services/cdp/src/signTypedData.test.ts",
            "services/cdp/src/treasury.test.ts",
        ],
        "helper_files": [
            "services/cdp/src/signMessage.ts",
            "services/cdp/src/sendTransaction.ts",
            "services/cdp/src/signTypedData.ts",
            "services/cdp/src/treasury.ts",
        ],
        "coverage_points": [
            "sign-message request normalization and rejection",
            "send-transaction request normalization and rejection",
            "sign-typed-data request normalization and rejection",
            "deterministic decimal/native/USDC amount parsing",
            "ERC-20 transfer calldata encoding",
        ],
    },
    "stripe": {
        "test_files": [
            "services/stripe/src/mppKeys.test.ts",
            "services/stripe/src/mppRequest.test.ts",
        ],
        "helper_files": [
            "services/stripe/src/mppKeys.ts",
            "services/stripe/src/mppRequest.ts",
        ],
        "coverage_points": [
            "deterministic MPP private key derivation",
            "merchant and amount request normalization",
            "MPP execute request validation",
        ],
    },
    "atxp": {
        "test_files": [
            "services/atxp/src/cdpTreasuryTopUp.test.ts",
            "services/atxp/src/directTransfer.test.ts",
        ],
        "helper_files": [
            "services/atxp/src/cdpTreasuryTopUp.ts",
            "services/atxp/src/directTransfer.ts",
        ],
        "coverage_points": [
            "cdp-base treasury top-up planning",
            "direct-transfer raw transaction credential parsing",
            "ATXP credential object parsing and USDC amount rounding",
        ],
    },
    "ap2": {
        "test_files": [
            "services/ap2/tests/test_contracts.py",
        ],
        "helper_files": [
            "services/ap2/src/meridian_ap2_direct/contracts.py",
        ],
        "coverage_points": [
            "canonical credential hashing",
            "rounded USD amount comparison",
            "settlement merchant and amount mismatch diagnostics",
        ],
    },
}


def service_offline_node_trace_metadata(
    root: Path,
    package_root: Path,
    service: str,
    node_modules_seed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    coverage = SERVICE_OFFLINE_COVERAGE[service]
    metadata = pnpm_trace_metadata(
        root,
        package_root,
        ["pnpm run test:offline"],
        node_modules_seed,
    )
    metadata["validation"].update(
        {
            "kind": "service_offline_protocol_tests",
            "service": service,
            "offline": True,
            "credential_free": True,
            "covered_test_files": coverage["test_files"],
            "covered_helper_files": coverage["helper_files"],
            "coverage_points": coverage["coverage_points"],
            "protects": "Pure protocol helper contracts run without live provider credentials.",
        }
    )
    return metadata


def service_offline_python_trace_metadata(root: Path) -> dict[str, Any]:
    coverage = SERVICE_OFFLINE_COVERAGE["ap2"]
    return {
        "validation": {
            "kind": "service_offline_protocol_tests",
            "service": "ap2",
            "package_root": "services/ap2",
            "offline": True,
            "credential_free": True,
            "validation_commands": [
                "PYTHONPATH=src python3 -m unittest discover -s tests -q"
            ],
            "covered_test_files": coverage["test_files"],
            "covered_helper_files": coverage["helper_files"],
            "coverage_points": coverage["coverage_points"],
            "protects": "AP2 canonical credential and settlement helper contracts run without live credentials.",
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


def service_builds_summary_trace_metadata(component_tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "aggregation": {
            "kind": "mean_component_score",
            "component_count": len(component_tasks),
            "component_tasks": component_tasks,
            "score_formula": "sum(component_scores) / len(component_scores)",
            "note": "This synthetic summary runs no shell command; inspect component traces for cache, validation, and logs.",
        }
    }


def service_offline_tests_summary_trace_metadata(
    component_tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "aggregation": {
            "kind": "mean_component_score",
            "component_count": len(component_tasks),
            "component_tasks": component_tasks,
            "score_formula": "sum(component_scores) / len(component_scores)",
            "note": "This synthetic summary runs no shell command; inspect component traces for offline protocol test logs and dependency cache details.",
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
    contract_surfaces: list[dict[str, Any]],
    service_offline_coverage_files: list[dict[str, Any]],
) -> dict[str, Any]:
    needles_by_path = {path: len(needles) for path, needles in contains_contracts}
    return {
        "validation": {
            "kind": "static_contracts",
            "required_file_count": len(required_files),
            "required_files": required_files,
            "coverage_areas": [
                {
                    **surface,
                    "needle_count": sum(needles_by_path.get(path, 0) for path in surface["paths"]),
                }
                for surface in contract_surfaces
            ],
            "contains_contracts": [
                {
                    "path": path,
                    "needle_count": len(needles),
                    "needles": needles,
                }
                for path, needles in contains_contracts
            ],
            "metadata_drift_checks": [
                {
                    "kind": "service_offline_coverage_files_exist_and_nonempty",
                    "source": "SERVICE_OFFLINE_COVERAGE",
                    "required_nonempty_fields": ["test_files", "helper_files"],
                    "file_count": sum(
                        item["file_count"] for item in service_offline_coverage_files
                    ),
                    "empty_required_field_count": sum(
                        len(item["empty_required_fields"])
                        for item in service_offline_coverage_files
                    ),
                    "services": [
                        item["service"] for item in service_offline_coverage_files
                    ],
                    "protects": "Offline service trace coverage must name at least one test file and helper file per service, and every listed path must exist.",
                }
            ],
            "service_offline_coverage_files": service_offline_coverage_files,
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

    service_offline_coverage_files = []
    for service, coverage in SERVICE_OFFLINE_COVERAGE.items():
        required_fields = ["test_files", "helper_files"]
        empty_required_fields = [
            field for field in required_fields if len(coverage[field]) == 0
        ]
        for field in empty_required_fields:
            failures.append(
                f"SERVICE_OFFLINE_COVERAGE[{service}]: {field} must list at least one file"
            )
        checked_paths = [
            *coverage["test_files"],
            *coverage["helper_files"],
        ]
        missing_paths = [path for path in checked_paths if not (root / path).exists()]
        for path in missing_paths:
            failures.append(
                f"SERVICE_OFFLINE_COVERAGE[{service}]: missing listed file {path}"
            )
        service_offline_coverage_files.append(
            {
                "service": service,
                "checked_fields": ["test_files", "helper_files"],
                "test_files": coverage["test_files"],
                "helper_files": coverage["helper_files"],
                "field_counts": {
                    field: len(coverage[field]) for field in required_fields
                },
                "empty_required_fields": empty_required_fields,
                "file_count": len(checked_paths),
                "missing_files": missing_paths,
            }
        )

    contract_surfaces = [
        {
            "surface": "local_runtime_bootstrap",
            "paths": ["run.sh"],
            "protects": "run.sh still starts every local service and the simulation worker.",
        },
        {
            "surface": "funding_and_treasury_guidance",
            "paths": [
                "docs/funding.md",
                "services/cdp/src/index.ts",
                "services/atxp/src/cdpBaseSepoliaAccount.ts",
                "services/atxp/src/funding.ts",
                "web/src/routes/funding/+page.svelte",
                "web/src/routes/api/funding/+server.ts",
            ],
            "protects": "Funding docs, CDP treasury routes, ATXP fallback wording, and frontend funding probes stay aligned.",
        },
        {
            "surface": "atxp_runtime_settlement",
            "paths": [
                "services/atxp/src/index.ts",
                "engine/src/protocols/atxp.rs",
            ],
            "protects": "ATXP health, authorize, execute, direct transfer, and engine runtime readiness contracts stay visible.",
        },
        {
            "surface": "frontend_navigation",
            "paths": ["web/src/routes/+layout.svelte"],
            "protects": "Funding diagnostics remain reachable from the Svelte app shell.",
        },
        {
            "surface": "engine_capability_readiness",
            "paths": ["engine/src/routes/capabilities.rs"],
            "protects": "Engine capability checks still join live protocol readiness signals.",
        },
    ]
    score = 1.0 if not failures else max(0.0, 1.0 - len(failures) / 20.0)
    log_task(
        "static_contracts",
        score,
        summary="all contracts present" if not failures else f"{len(failures)} contract issues",
        failure_reason="; ".join(failures[:8]) if failures else None,
        failures=failures,
        trace_metadata=static_contract_trace_metadata(
            required_files,
            contains_contracts,
            contract_surfaces,
            service_offline_coverage_files,
        ),
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
    component_tasks = []
    service_targets = [("cdp", 22), ("stripe", 22), ("atxp", 35)]
    for service, target_seconds in service_targets:
        task_id = f"service_build_{service}"
        package_root = root / "services" / service
        node_modules_seed = seed_node_modules(root, package_root)
        component_tasks.append(
            {
                "task_id": task_id,
                "service": service,
                "package_root": f"services/{service}",
                "target_seconds": target_seconds,
                "node_modules_seed": node_modules_seed,
            }
        )
        scores.append(
            run_command(
                root,
                task_id,
                pnpm_cached_install_command("pnpm run build"),
                cwd=package_root,
                timeout=180,
                target_seconds=target_seconds,
                trace_metadata=pnpm_trace_metadata(
                    root,
                    package_root,
                    ["pnpm run build"],
                    node_modules_seed,
                ),
            )
        )
    score = sum(scores) / len(scores)
    log_task(
        "service_builds_summary",
        score,
        summary=f"mean service build score {score:.4f}",
        component_scores=scores,
        trace_metadata=service_builds_summary_trace_metadata(component_tasks),
    )
    return score


def task_service_offline_protocol_tests(root: Path) -> float:
    scores = []
    component_tasks = []
    node_targets = [("cdp", 22), ("stripe", 22), ("atxp", 35)]
    for service, target_seconds in node_targets:
        task_id = f"service_offline_{service}"
        package_root = root / "services" / service
        node_modules_seed = seed_node_modules(root, package_root)
        coverage = SERVICE_OFFLINE_COVERAGE[service]
        component_tasks.append(
            {
                "task_id": task_id,
                "service": service,
                "package_root": f"services/{service}",
                "target_seconds": target_seconds,
                "node_modules_seed": node_modules_seed,
                "validation_command": "pnpm run test:offline",
                "covered_test_files": coverage["test_files"],
                "covered_helper_files": coverage["helper_files"],
            }
        )
        scores.append(
            run_command(
                root,
                task_id,
                pnpm_cached_install_command("pnpm run test:offline"),
                cwd=package_root,
                timeout=180,
                target_seconds=target_seconds,
                trace_metadata=service_offline_node_trace_metadata(
                    root,
                    package_root,
                    service,
                    node_modules_seed,
                ),
            )
        )

    ap2_task = {
        "task_id": "service_offline_ap2",
        "service": "ap2",
        "package_root": "services/ap2",
        "target_seconds": 4,
        "validation_command": "PYTHONPATH=src python3 -m unittest discover -s tests -q",
        "covered_test_files": SERVICE_OFFLINE_COVERAGE["ap2"]["test_files"],
        "covered_helper_files": SERVICE_OFFLINE_COVERAGE["ap2"]["helper_files"],
    }
    component_tasks.append(ap2_task)
    scores.append(
        run_command(
            root,
            "service_offline_ap2",
            "PYTHONPATH=src python3 -m unittest discover -s tests -q",
            cwd=root / "services" / "ap2",
            timeout=60,
            target_seconds=4,
            trace_metadata=service_offline_python_trace_metadata(root),
        )
    )

    score = sum(scores) / len(scores)
    log_task(
        "service_offline_protocol_tests",
        score,
        summary=f"mean service offline protocol test score {score:.4f}",
        component_scores=scores,
        trace_metadata=service_offline_tests_summary_trace_metadata(component_tasks),
    )
    return score


def task_web_check(root: Path) -> float:
    package_root = root / "web"
    node_modules_seed = seed_node_modules(root, package_root)
    return run_command(
        root,
        "web_check_build",
        pnpm_cached_install_command("pnpm run check && pnpm run build"),
        cwd=package_root,
        timeout=240,
        target_seconds=70,
        trace_metadata=pnpm_trace_metadata(
            root,
            package_root,
            ["pnpm run check", "pnpm run build"],
            node_modules_seed,
        ),
    )


def run_benchmark(root: Path) -> float:
    scores = [
        task_static_contracts(root),
        task_python_compile(root),
        task_python_tests(root),
        task_rust_tests(root),
        task_service_builds(root),
        task_service_offline_protocol_tests(root),
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
