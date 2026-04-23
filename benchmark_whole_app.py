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
RAW_ROUTE_PRESSURE_FALLBACK_FIELDS = ["reason", "failure_count", "pressure_level"]
ROUTE_SCORE_RATIONALE_FIELDS = [
    "route_score",
    "route_score_drivers",
    "route_score_context",
    "avg_route_score",
    "avg_route_pressure_penalty",
    "avg_sustainability_bias",
    "route_score_pressure_drag",
    "route_score_sustainability_lift",
]
ROUTE_SCORE_FRONTEND_DISPLAY_FIELDS = [
    "avg_route_score",
    "avg_route_pressure_penalty",
    "avg_sustainability_bias",
]
ROUTE_SCORE_DRIVER_TOKEN_LABELS = ["score", "pressure", "sustain"]
INHERITED_GATE_GUIDANCE = [
    {
        "name": "whole_app_contract_gate",
        "command": "python3 {worktree}/benchmark_whole_app.py --target {target} --profile gate --min-score 1.0",
        "scope": "static contracts and Python compileability",
        "related_task_ids": ["static_contracts", "python_compile"],
        "preserve_when_combining": True,
    },
    {
        "name": "ap2_offline_settlement_semantics",
        "command": "cd {target}/services/ap2 && PYTHONPATH=src python3 -m unittest discover -s tests -q",
        "scope": "AP2 offline settlement helper semantics",
        "related_task_ids": ["service_offline_ap2", "service_offline_protocol_tests"],
        "preserve_when_combining": True,
    },
    {
        "name": "stripe_mpp_offline_semantics",
        "command": "cd {target}/services/stripe && CACHE_ROOT=\"${XDG_CACHE_HOME:-${HOME:-/tmp}/.cache}/meridian-evo-bench\" && PNPM_STORE_DIR=\"$CACHE_ROOT/pnpm-store-v10\" && pnpm install --store-dir \"$PNPM_STORE_DIR\" --frozen-lockfile --prefer-offline --ignore-scripts && pnpm run test:offline",
        "scope": "Stripe MPP offline request and settlement helper semantics",
        "related_task_ids": ["service_offline_stripe", "service_offline_protocol_tests"],
        "preserve_when_combining": True,
    },
    {
        "name": "atxp_offline_direct_transfer_topup_contract",
        "command": "cd {target}/services/atxp && CACHE_ROOT=\"${XDG_CACHE_HOME:-${HOME:-/tmp}/.cache}/meridian-evo-bench\" && PNPM_STORE_DIR=\"$CACHE_ROOT/pnpm-store-v10\" && pnpm install --store-dir \"$PNPM_STORE_DIR\" --frozen-lockfile --prefer-offline --ignore-scripts && pnpm run test:offline",
        "scope": "ATXP direct-transfer and cdp-base treasury top-up contracts",
        "related_task_ids": ["service_offline_atxp", "service_offline_protocol_tests"],
        "preserve_when_combining": True,
    },
    {
        "name": "cdp_offline_treasury_transfer_contract",
        "command": "cd {target}/services/cdp && CACHE_ROOT=\"${XDG_CACHE_HOME:-${HOME:-/tmp}/.cache}/meridian-evo-bench\" && PNPM_STORE_DIR=\"$CACHE_ROOT/pnpm-store-v10\" && pnpm install --store-dir \"$PNPM_STORE_DIR\" --frozen-lockfile --prefer-offline --ignore-scripts && pnpm run test:offline",
        "scope": "CDP offline treasury transfer route request and response contract",
        "related_task_ids": ["service_offline_cdp", "service_offline_protocol_tests"],
        "preserve_when_combining": True,
    },
    {
        "name": "route_score_merchant_switch_report_readout",
        "command": "cd {target}/sim && CACHE_ROOT=\"${XDG_CACHE_HOME:-/tmp}/meridian-evo-bench\" && PIP_CACHE_DIR=\"$CACHE_ROOT/pip-cache\" && export PIP_CACHE_DIR && PY_TAG=\"$(python3 -c 'import sys; print(sys.implementation.cache_tag)')\" && DEPS_KEY=\"$(sha256sum pyproject.toml uv.lock | sha256sum | cut -d \" \" -f 1)\" && SHORT_KEY=\"$(printf \"%s\" \"$DEPS_KEY\" | cut -c 1-16)\" && VENVDIR=\"$CACHE_ROOT/python-sim-venv-$PY_TAG-$SHORT_KEY\" && READY=\"$VENVDIR/.ready-$SHORT_KEY\" && if [ ! -f \"$READY\" ]; then rm -rf \"$VENVDIR\" && python3 -m venv \"$VENVDIR\" && \"$VENVDIR/bin/python3\" -m pip install -q --disable-pip-version-check --prefer-binary \"aiohttp>=3.9.0\" \"pytest>=8.0\" \"pytest-asyncio>=0.23\" && touch \"$READY\"; fi && PYTHONPATH=\"$PWD${PYTHONPATH:+:$PYTHONPATH}\" \"$VENVDIR/bin/python3\" -m pytest tests/test_engine.py::test_report_explains_route_score_driven_merchant_protocol_change -q",
        "scope": "Route-score merchant switch report readout",
        "related_task_ids": ["python_sim_tests"],
        "preserve_when_combining": True,
    },
]
FOCUSED_GATE_DUPLICATE_VALIDATION = [
    {
        "gate_name": "ap2_offline_settlement_semantics",
        "focused_task_id": "service_offline_ap2",
        "aggregate_task_id": "service_offline_protocol_tests",
        "reruns_after_benchmark_profile": True,
        "cost_is_expected": True,
        "reason": "The full benchmark already runs AP2 offline protocol tests; this focused gate reruns them after the benchmark to protect inherited settlement semantics.",
    },
    {
        "gate_name": "stripe_mpp_offline_semantics",
        "focused_task_id": "service_offline_stripe",
        "aggregate_task_id": "service_offline_protocol_tests",
        "reruns_after_benchmark_profile": True,
        "cost_is_expected": True,
        "reason": "The full benchmark already runs Stripe MPP offline protocol tests; this focused gate reruns them after the benchmark to protect inherited MPP semantics.",
    },
    {
        "gate_name": "atxp_offline_direct_transfer_topup_contract",
        "focused_task_id": "service_offline_atxp",
        "aggregate_task_id": "service_offline_protocol_tests",
        "reruns_after_benchmark_profile": True,
        "cost_is_expected": True,
        "reason": "The full benchmark already runs ATXP offline protocol tests; this focused gate reruns them after the benchmark to protect inherited direct-transfer and top-up semantics.",
    },
    {
        "gate_name": "cdp_offline_treasury_transfer_contract",
        "focused_task_id": "service_offline_cdp",
        "aggregate_task_id": "service_offline_protocol_tests",
        "reruns_after_benchmark_profile": True,
        "cost_is_expected": True,
        "reason": "The full benchmark already runs CDP offline protocol tests; this focused gate reruns them after the benchmark to protect inherited treasury transfer semantics.",
    },
]
PROTECTED_SURFACES_CHECKPOINT = {
    "label": "protected_surfaces_checkpoint",
    "version": 1,
    "docs_anchor": "Current protected surfaces checkpoint",
    "related_task_ids": [
        "static_contracts",
        "service_offline_protocol_tests",
        "service_offline_cdp",
        "service_offline_stripe",
        "service_offline_atxp",
        "service_offline_ap2",
        "python_compile",
    ],
    "related_gate_names": [
        *[gate["name"] for gate in INHERITED_GATE_GUIDANCE],
    ],
    "protects": "Compact label for the current docs-defined checkpoint of inherited protected surfaces.",
}
LIST_TASKS_METADATA_SCHEMA_VERSION = 1
LIST_TASKS_METADATA_SCHEMA = {
    "kind": "list_tasks_metadata_schema",
    "schema_version": LIST_TASKS_METADATA_SCHEMA_VERSION,
    "top_level_keys": [
        "tasks",
        "profiles",
        "manual_selection",
        "gate_guidance",
        "metadata_schema",
    ],
    "task_entry_required_keys": [
        "task_id",
        "benchmark_profile",
        "gate_profile",
    ],
    "task_entry_optional_keys": [
        "category",
        "parent_task_id",
        "service",
        "phase",
        "command",
        "target_seconds",
        "manual_validation_task_ids",
        "manual_selection",
        "covered_test_files",
        "covered_helper_files",
        "coverage_points",
        "semantic_surfaces",
        "semantic_surfaces_by_service",
        "duplicate_validation",
        "preserved_gate_names",
    ],
    "metadata_rich_task_ids": [
        "web_check_build",
        "service_builds_summary",
        "service_offline_protocol_tests",
        "service_offline_cdp",
        "service_offline_stripe",
        "service_offline_atxp",
        "service_offline_ap2",
    ],
    "docs_anchor": "list_tasks_metadata_schema",
    "protects": "--list-tasks metadata shape stays explicit, documented, and cheap to statically validate.",
}

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


def write_result(
    score: float | None = None,
    *,
    result_metadata: dict[str, Any] | None = None,
) -> float:
    if score is None:
        score = sum(_SCORES.values()) / len(_SCORES) if _SCORES else 0.0
    score = round(score, 4)
    result: dict[str, Any] = {
        "score": score,
        "tasks": dict(_SCORES),
        "started_at": _STARTED_AT,
        "ended_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if result_metadata:
        result.update(result_metadata)
    print(
        json.dumps(result, indent=2)
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


def inherited_gate_guidance_metadata() -> dict[str, Any]:
    return {
        "kind": "inherited_gate_guidance",
        "protected_surfaces_checkpoint": PROTECTED_SURFACES_CHECKPOINT,
        "source_of_truth": "evo gate list <parent-or-checkpoint>",
        "combine_rule": "Before manual combines, compare source and destination gate lists and reattach every missing gate listed here.",
        "default_profile_changed": False,
        "gate_profile_changed": False,
        "gates": INHERITED_GATE_GUIDANCE,
        "duplicate_validation": focused_gate_duplicate_validation_metadata(),
    }


def focused_gate_duplicate_validation_metadata() -> dict[str, Any]:
    return {
        "kind": "focused_gate_duplicate_validation_cost",
        "source_of_truth": "evo run executes the benchmark profile before inherited focused gates",
        "benchmark_aggregate_task_id": "service_offline_protocol_tests",
        "default_profile_changed": False,
        "gate_profile_changed": False,
        "entries": FOCUSED_GATE_DUPLICATE_VALIDATION,
        "note": "Duplicate offline service validation is intentional correctness cost, not stale cache work. Do not remove, skip, merge, or weaken focused gates to save this time.",
    }


def inherited_gate_names() -> list[str]:
    return [gate["name"] for gate in INHERITED_GATE_GUIDANCE]


def service_readme_paths() -> list[str]:
    return [f"services/{service}/README.md" for service in SERVICE_OFFLINE_COVERAGE]


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


def pnpm_install_phase_command() -> str:
    return pnpm_cached_install_command(":")


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
    phase_tasks: list[dict[str, Any]] | None = None,
    parent_task_id: str | None = None,
) -> dict[str, Any]:
    validation: dict[str, Any] = {
        "kind": "pnpm_frozen_build_pipeline",
        "package_root": rel(root, package_root),
        "required_phases": ["install", *validation_commands],
        "install_command": "pnpm install --store-dir $PNPM_STORE_DIR --frozen-lockfile --prefer-offline --ignore-scripts",
        "validation_commands": validation_commands,
        "cache_note": "The shared pnpm store may change elapsed time, but the install and validation commands still run.",
    }
    if phase_tasks is not None:
        validation["manual_phase_tasks"] = phase_tasks
        validation["phase_debug_note"] = (
            "Default profiles keep the combined command. Use these task ids manually "
            "to isolate install, build, check, or test diagnostics."
        )
    metadata: dict[str, Any] = {
        "validation": {
            **validation,
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
    if phase_tasks is not None and parent_task_id is not None:
        task_ids = [task["task_id"] for task in phase_tasks]
        metadata["manual_validation"] = {
            "kind": "manual_phase_task_index",
            "parent_task_id": parent_task_id,
            "package_root": rel(root, package_root),
            "task_ids": task_ids,
            "tasks": phase_tasks,
            "selection_args": {
                "single": f"--task-id {task_ids[0]}",
                "all": f"--task-ids {','.join(task_ids)}",
            },
            "default_profile": False,
            "gate_profile": False,
            "note": "Manual phase tasks are opt-in diagnostics for this aggregate; default benchmark and gate profiles are unchanged.",
        }
    return metadata


SERVICE_OFFLINE_COVERAGE: dict[str, dict[str, list[str]]] = {
    "cdp": {
        "test_files": [
            "services/cdp/src/signMessage.test.ts",
            "services/cdp/src/sendTransaction.test.ts",
            "services/cdp/src/signTypedData.test.ts",
            "services/cdp/src/treasury.test.ts",
        ],
        "helper_files": [
            "services/cdp/src/requestValidation.ts",
            "services/cdp/src/signMessage.ts",
            "services/cdp/src/sendTransaction.ts",
            "services/cdp/src/signTypedData.ts",
            "services/cdp/src/treasury.ts",
        ],
        "coverage_points": [
            "shared request shape, address, and non-empty string validation",
            "sign-message request normalization and rejection",
            "send-transaction request normalization and rejection",
            "sign-typed-data request normalization and rejection",
            "deterministic decimal/native/USDC amount parsing",
            "ERC-20 transfer calldata encoding",
        ],
        "semantic_surfaces": [
            "CDP sign-message exact byte preservation and own-field validation",
            "CDP send-transaction network/value normalization and own-field validation",
            "CDP sign-typed-data exact key, primaryType, nested own-key, and message own-field semantics",
            "CDP treasury native and USDC transfer route request/response contracts",
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
        "semantic_surfaces": [
            "Stripe MPP deterministic actor and merchant key derivation",
            "Stripe MPP authorize payment session URL semantics",
            "Stripe MPP execute paid-resource URL and settlement response semantics",
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
        "semantic_surfaces": [
            "ATXP cdp-base treasury top-up amount boundary and default planning",
            "ATXP direct-transfer raw transaction credential parsing",
            "ATXP direct-transfer own-field request shape and USDC amount boundary contracts",
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
        "semantic_surfaces": [
            "AP2 canonical credential hashing",
            "AP2 nested mandate actor, merchant, and amount settlement semantics",
            "AP2 settlement mismatch diagnostics for merchant and amount drift",
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
            "semantic_surfaces": coverage["semantic_surfaces"],
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
            "semantic_surfaces": coverage["semantic_surfaces"],
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
                "python3 -m pytest tests/test_economy.py tests/test_engine.py::test_agent_generation tests/test_engine.py::test_scenarios tests/test_engine.py::test_self_sustainability_report_uses_raw_route_pressure_events_without_summary -q",
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
    manual_tasks = [
        phase_task
        for component_task in component_tasks
        for phase_task in component_task.get("manual_phase_tasks", [])
    ]
    manual_task_ids = [task["task_id"] for task in manual_tasks]
    return {
        "aggregation": {
            "kind": "mean_component_score",
            "component_count": len(component_tasks),
            "component_tasks": component_tasks,
            "score_formula": "sum(component_scores) / len(component_scores)",
            "note": "This synthetic summary runs no shell command; component entries list manual phase task ids for install/build isolation, while component traces show full cache, validation, and logs.",
        },
        "manual_validation": {
            "kind": "manual_phase_task_index",
            "parent_task_id": "service_builds_summary",
            "task_ids": manual_task_ids,
            "tasks": manual_tasks,
            "selection_args": {
                "single": "--task-id service_cdp_install",
                "all": f"--task-ids {','.join(manual_task_ids)}",
            },
            "default_profile": False,
            "gate_profile": False,
            "note": "Use these opt-in service phase tasks to isolate install versus TypeScript build without rerunning every service aggregate.",
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
        },
        "gate_guidance": inherited_gate_guidance_metadata(),
        "duplicate_validation": focused_gate_duplicate_validation_metadata(),
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


def check_raw_route_pressure_report_contract(root: Path, failures: list[str]) -> dict[str, Any]:
    docs_path = root / "docs/simulation-payload-contract.md"
    report_path = root / "sim/sim/report.py"
    test_path = root / "sim/tests/test_engine.py"
    targets = [
        (
            "docs",
            docs_path,
            ['event_type="route_pressure"', *RAW_ROUTE_PRESSURE_FALLBACK_FIELDS],
        ),
        (
            "report_fallback",
            report_path,
            [
                '_source") == "world_events.route_pressure"',
                *[f'{field} {{' for field in RAW_ROUTE_PRESSURE_FALLBACK_FIELDS],
            ],
        ),
        (
            "report_test",
            test_path,
            [
                "test_self_sustainability_report_uses_raw_route_pressure_events_without_summary",
                *[f'"{field}"' for field in RAW_ROUTE_PRESSURE_FALLBACK_FIELDS],
                *[f"{field} " for field in RAW_ROUTE_PRESSURE_FALLBACK_FIELDS],
            ],
        ),
    ]
    checked_paths = []
    missing_needles = []
    for label, path, needles in targets:
        rel_path = path.relative_to(root).as_posix()
        checked_paths.append(rel_path)
        if not path.exists():
            failures.append(f"raw_route_pressure_report_contract[{label}]: missing {rel_path}")
            missing_needles.extend(
                {"surface": label, "path": rel_path, "needle": needle}
                for needle in needles
            )
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in needles:
            if needle not in text:
                failures.append(
                    f"raw_route_pressure_report_contract[{label}]: missing {needle!r}"
                )
                missing_needles.append(
                    {"surface": label, "path": rel_path, "needle": needle}
                )
    return {
        "kind": "raw_route_pressure_report_contract",
        "source_fields": RAW_ROUTE_PRESSURE_FALLBACK_FIELDS,
        "checked_paths": checked_paths,
        "missing_needles": missing_needles,
        "protects": "Raw route_pressure fallback docs, report wording, and focused tests stay tied to reason, failure_count, and pressure_level field names.",
    }


def check_route_score_rationale_contract(root: Path, failures: list[str]) -> dict[str, Any]:
    targets = [
        (
            "architecture",
            root / "docs/simulation-architecture.md",
            [
                "## Route-Score Rationale",
                "self-sustainability bias",
                *ROUTE_SCORE_RATIONALE_FIELDS,
            ],
        ),
        (
            "payload_contract",
            root / "docs/simulation-payload-contract.md",
            [
                "Route-score rationale",
                "explain the selected buyer",
                "protocol-level route evidence",
                "frontend route-score",
                *ROUTE_SCORE_RATIONALE_FIELDS,
                *ROUTE_SCORE_DRIVER_TOKEN_LABELS,
            ],
        ),
        (
            "report_route_score_readout",
            root / "sim/sim/report.py",
            [
                "Route-score merchant changes:",
                "route_score_pressure_drag",
                "route_score_sustainability_lift",
                *ROUTE_SCORE_DRIVER_TOKEN_LABELS,
            ],
        ),
        (
            "frontend_stream_contract",
            root / "web/src/lib/simStream.contract.ts",
            [
                "routeScoreDriverDisplay",
                "metricsRouteScore",
                "metricsPressureDrag",
                "metricsSustainabilityLift",
                *ROUTE_SCORE_FRONTEND_DISPLAY_FIELDS,
            ],
        ),
        (
            "frontend_display_helper",
            root / "web/src/lib/routeScoreDrivers.ts",
            [
                "routeScoreDriverDisplay",
                *ROUTE_SCORE_DRIVER_TOKEN_LABELS,
            ],
        ),
        (
            "frontend_observability_display",
            root / "web/src/lib/components/EconomyObservability.svelte",
            [
                "routeScoreDriverDisplay",
                "score-driver-strip",
                *ROUTE_SCORE_FRONTEND_DISPLAY_FIELDS,
            ],
        ),
        (
            "frontend_market_chart_display",
            root / "web/src/lib/components/MarketCharts.svelte",
            [
                "routeScoreDriverDisplay",
                "score_drivers",
                *ROUTE_SCORE_FRONTEND_DISPLAY_FIELDS,
            ],
        ),
    ]
    checked_paths = []
    missing_needles = []
    for label, path, needles in targets:
        rel_path = path.relative_to(root).as_posix()
        checked_paths.append(rel_path)
        if not path.exists():
            failures.append(f"route_score_rationale_contract[{label}]: missing {rel_path}")
            missing_needles.extend(
                {"surface": label, "path": rel_path, "needle": needle}
                for needle in needles
            )
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in needles:
            if needle not in text:
                failures.append(
                    f"route_score_rationale_contract[{label}]: missing {needle!r}"
                )
                missing_needles.append(
                    {"surface": label, "path": rel_path, "needle": needle}
                )
    return {
        "kind": "route_score_rationale_contract",
        "source_fields": ROUTE_SCORE_RATIONALE_FIELDS,
        "frontend_display_fields": ROUTE_SCORE_FRONTEND_DISPLAY_FIELDS,
        "driver_token_labels": ROUTE_SCORE_DRIVER_TOKEN_LABELS,
        "checked_paths": checked_paths,
        "missing_needles": missing_needles,
        "protects": "Route-score docs and frontend displays stay tied to exact payload fields for buyer choice, protocol summary, merchant switch evidence, and self-sustainable protocol evolution.",
    }


def check_inherited_gate_guidance_contract(
    root: Path, failures: list[str]
) -> dict[str, Any]:
    checked_paths = ["AGENTS.md", "docs/simulation-architecture.md"]
    required_needles = [
        "benchmark_whole_app.py --list-tasks",
        PROTECTED_SURFACES_CHECKPOINT["label"],
        f"version: {PROTECTED_SURFACES_CHECKPOINT['version']}",
        "duplicate focused gate validation",
        *inherited_gate_names(),
    ]
    missing_needles = []
    for rel_path in checked_paths:
        path = root / rel_path
        if not path.exists():
            failures.append(f"inherited_gate_guidance[{rel_path}]: missing file")
            missing_needles.extend(
                {"path": rel_path, "needle": needle} for needle in required_needles
            )
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in required_needles:
            if needle not in text:
                failures.append(
                    f"inherited_gate_guidance[{rel_path}]: missing {needle!r}"
                )
                missing_needles.append({"path": rel_path, "needle": needle})
    return {
        "kind": "inherited_gate_guidance_docs",
        "source": "INHERITED_GATE_GUIDANCE",
        "protected_surfaces_checkpoint": PROTECTED_SURFACES_CHECKPOINT,
        "checked_paths": checked_paths,
        "required_gate_names": inherited_gate_names(),
        "duplicate_validation": focused_gate_duplicate_validation_metadata(),
        "missing_needles": missing_needles,
        "protects": "Gate hygiene docs and list-task metadata keep inherited focused gate names discoverable without source hunting.",
    }


def list_tasks_payload() -> dict[str, Any]:
    return {
        "tasks": task_catalog(),
        "profiles": {
            "benchmark": BENCHMARK_PROFILE_TASK_IDS,
            "gate": GATE_PROFILE_TASK_IDS,
        },
        "manual_selection": {
            "single": "--task-id web_check_build",
            "multiple": "--task-ids service_cdp_install,service_cdp_build",
        },
        "gate_guidance": inherited_gate_guidance_metadata(),
        "metadata_schema": LIST_TASKS_METADATA_SCHEMA,
    }


def check_list_tasks_metadata_schema_contract(
    root: Path, failures: list[str]
) -> dict[str, Any]:
    payload = list_tasks_payload()
    schema = LIST_TASKS_METADATA_SCHEMA
    actual_schema_version = payload["metadata_schema"].get("schema_version")
    if actual_schema_version != LIST_TASKS_METADATA_SCHEMA_VERSION:
        failures.append(
            "list_tasks_metadata_schema: schema_version "
            f"{actual_schema_version!r} does not match expected "
            f"{LIST_TASKS_METADATA_SCHEMA_VERSION!r}"
        )
    expected_top_keys = set(schema["top_level_keys"])
    actual_top_keys = set(payload)
    missing_top_keys = sorted(actual_top_keys - expected_top_keys)
    extra_top_keys = sorted(expected_top_keys - actual_top_keys)
    for key in missing_top_keys:
        failures.append(f"list_tasks_metadata_schema: top-level key {key!r} missing from schema")
    for key in extra_top_keys:
        failures.append(f"list_tasks_metadata_schema: schema key {key!r} missing from --list-tasks payload")

    required_keys = set(schema["task_entry_required_keys"])
    optional_keys = set(schema["task_entry_optional_keys"])
    known_task_keys = required_keys | optional_keys
    unexpected_task_keys = sorted(
        key for task in payload["tasks"] for key in task if key not in known_task_keys
    )
    missing_required_task_keys = sorted(
        f"{task.get('task_id', '<unknown>')}.{key}"
        for task in payload["tasks"]
        for key in required_keys
        if key not in task
    )
    for key in unexpected_task_keys:
        failures.append(f"list_tasks_metadata_schema: task key {key!r} missing from schema")
    for item in missing_required_task_keys:
        failures.append(f"list_tasks_metadata_schema: required task key missing: {item}")

    docs_path = root / "docs/simulation-architecture.md"
    docs_needles = [
        schema["docs_anchor"],
        "metadata_schema",
        f"schema_version: {LIST_TASKS_METADATA_SCHEMA_VERSION}",
        "task_entry_required_keys",
        "task_entry_optional_keys",
        "manual_validation_task_ids",
        "duplicate_validation",
        "semantic_surfaces",
        "preserved_gate_names",
    ]
    missing_docs_needles = []
    if not docs_path.exists():
        failures.append("list_tasks_metadata_schema[docs/simulation-architecture.md]: missing file")
        missing_docs_needles = docs_needles
    else:
        text = docs_path.read_text(encoding="utf-8", errors="replace")
        missing_docs_needles = [needle for needle in docs_needles if needle not in text]
        for needle in missing_docs_needles:
            failures.append(
                f"list_tasks_metadata_schema[docs/simulation-architecture.md]: missing {needle!r}"
            )

    return {
        "kind": "list_tasks_metadata_schema_contract",
        "source": "LIST_TASKS_METADATA_SCHEMA",
        "checked_paths": ["docs/simulation-architecture.md"],
        "schema_version": actual_schema_version,
        "top_level_keys": schema["top_level_keys"],
        "task_entry_required_keys": schema["task_entry_required_keys"],
        "task_entry_optional_keys": schema["task_entry_optional_keys"],
        "metadata_rich_task_ids": schema["metadata_rich_task_ids"],
        "unexpected_task_keys": unexpected_task_keys,
        "missing_required_task_keys": missing_required_task_keys,
        "missing_docs_needles": missing_docs_needles,
        "protects": "--list-tasks metadata fields stay declared in the schema and linked from worker docs.",
    }


def static_contract_trace_metadata(
    required_files: list[str],
    contains_contracts: list[tuple[str, list[str]]],
    contract_surfaces: list[dict[str, Any]],
    service_offline_coverage_files: list[dict[str, Any]],
    raw_route_pressure_report_contract: dict[str, Any],
    route_score_rationale_contract: dict[str, Any],
    inherited_gate_guidance_contract: dict[str, Any],
    list_tasks_metadata_schema_contract: dict[str, Any],
) -> dict[str, Any]:
    needles_by_path = {path: len(needles) for path, needles in contains_contracts}
    return {
        "validation": {
            "kind": "static_contracts",
            "metadata_schema": {
                "kind": LIST_TASKS_METADATA_SCHEMA["kind"],
                "schema_version": LIST_TASKS_METADATA_SCHEMA_VERSION,
                "source": "LIST_TASKS_METADATA_SCHEMA",
                "related_list_tasks_key": "metadata_schema",
            },
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
                    "kind": "service_offline_coverage_metadata_exists_and_nonempty",
                    "source": "SERVICE_OFFLINE_COVERAGE",
                    "required_nonempty_fields": [
                        "test_files",
                        "helper_files",
                        "semantic_surfaces",
                    ],
                    "path_fields": ["test_files", "helper_files"],
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
                    "protects": "Offline service trace coverage must name at least one test file, helper file, and protected semantic surface per service; every listed path must exist.",
                },
                {
                    "kind": "service_readme_semantic_surface_contracts",
                    "source": "SERVICE_OFFLINE_COVERAGE",
                    "source_task_id": "service_offline_protocol_tests",
                    "source_task_metadata_fields": ["semantic_surfaces"],
                    "source_fields": ["semantic_surfaces"],
                    "checked_paths": [
                        item["readme_path"] for item in service_offline_coverage_files
                    ],
                    "required_surface_count": sum(
                        item["semantic_surface_count"]
                        for item in service_offline_coverage_files
                    ),
                    "surface_check_count": sum(
                        len(item["readme_semantic_surface_checks"])
                        for item in service_offline_coverage_files
                    ),
                    "expected_semantic_surfaces": [
                        check
                        for item in service_offline_coverage_files
                        for check in item["readme_semantic_surface_checks"]
                    ],
                    "missing_surface_count": sum(
                        len(item["missing_readme_semantic_surfaces"])
                        for item in service_offline_coverage_files
                    ),
                    "missing_semantic_surfaces": [
                        detail
                        for item in service_offline_coverage_files
                        for detail in item["missing_readme_semantic_surface_details"]
                    ],
                    "protects": "Service READMEs must mention each offline semantic surface named by service protocol trace metadata.",
                },
                {
                    "kind": "service_readme_enforcing_file_contracts",
                    "source": "SERVICE_OFFLINE_COVERAGE",
                    "source_task_id": "service_offline_protocol_tests",
                    "source_task_metadata_fields": [
                        "covered_test_files",
                        "covered_helper_files",
                    ],
                    "source_fields": ["test_files", "helper_files"],
                    "checked_paths": [
                        item["readme_path"] for item in service_offline_coverage_files
                    ],
                    "required_file_count": sum(
                        item["file_count"] for item in service_offline_coverage_files
                    ),
                    "reference_check_count": sum(
                        len(item["readme_file_reference_checks"])
                        for item in service_offline_coverage_files
                    ),
                    "expected_file_references": [
                        check
                        for item in service_offline_coverage_files
                        for check in item["readme_file_reference_checks"]
                    ],
                    "missing_file_reference_count": sum(
                        len(item["missing_readme_file_references"])
                        for item in service_offline_coverage_files
                    ),
                    "missing_file_references": [
                        detail
                        for item in service_offline_coverage_files
                        for detail in item["missing_readme_file_reference_details"]
                    ],
                    "protects": "Service READMEs must point to each offline test and helper file named by service protocol trace metadata.",
                },
                raw_route_pressure_report_contract,
                route_score_rationale_contract,
                inherited_gate_guidance_contract,
                list_tasks_metadata_schema_contract,
            ],
            "service_offline_coverage_files": service_offline_coverage_files,
            "gate_guidance": inherited_gate_guidance_metadata(),
        }
    }


def task_static_contracts(root: Path) -> float:
    failures: list[str] = []
    required_files = [
        "AGENTS.md",
        "README.md",
        "docs/simulation-architecture.md",
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
        (
            "AGENTS.md",
            [
                "evo gate list <parent-or-checkpoint>",
                "preserve every focused gate",
                *inherited_gate_names(),
                "benchmark_whole_app.py --list-tasks",
                "Manual diff combines do not automatically carry gate metadata",
                "duplicate focused gate validation",
            ],
        ),
        (
            "docs/simulation-architecture.md",
            [
                "list_tasks_metadata_schema",
                "Manual Evo combines need a separate gate hygiene pass",
                "evo gate list <source>",
                "evo gate list <destination>",
                "reattach any focused gates",
                *inherited_gate_names(),
                "benchmark_whole_app.py --list-tasks",
                "service_offline_ap2",
                "duplicate focused gate validation",
                "SERVICE_OFFLINE_COVERAGE",
                *service_readme_paths(),
                "`static_contracts` protects this architecture cross-reference",
            ],
        ),
    ]
    for path, needles in contains_contracts:
        require_contains(root / path, needles, failures)

    raw_route_pressure_report_contract = check_raw_route_pressure_report_contract(
        root, failures
    )
    route_score_rationale_contract = check_route_score_rationale_contract(
        root, failures
    )
    inherited_gate_guidance_contract = check_inherited_gate_guidance_contract(
        root, failures
    )
    list_tasks_metadata_schema_contract = check_list_tasks_metadata_schema_contract(
        root, failures
    )

    service_offline_coverage_files = []
    for service, coverage in SERVICE_OFFLINE_COVERAGE.items():
        required_fields = ["test_files", "helper_files", "semantic_surfaces"]
        path_fields = ["test_files", "helper_files"]
        readme_path = f"services/{service}/README.md"
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
        readme_file_reference_checks = [
            {
                "service": service,
                "readme_path": readme_path,
                "source": "SERVICE_OFFLINE_COVERAGE",
                "source_task_id": f"service_offline_{service}",
                "source_field": field,
                "source_index": index,
                "expected_path": path,
                "expected_path_exists": (root / path).exists(),
            }
            for field in path_fields
            for index, path in enumerate(coverage[field])
        ]
        missing_paths = [path for path in checked_paths if not (root / path).exists()]
        for path in missing_paths:
            failures.append(
                f"SERVICE_OFFLINE_COVERAGE[{service}]: missing listed file {path}"
            )
        readme = root / readme_path
        readme_text = readme.read_text(encoding="utf-8", errors="replace") if readme.exists() else ""
        missing_readme_semantic_surfaces = [
            surface
            for surface in coverage["semantic_surfaces"]
            if surface not in readme_text
        ]
        readme_semantic_surface_checks = [
            {
                "service": service,
                "readme_path": readme_path,
                "source": "SERVICE_OFFLINE_COVERAGE",
                "source_task_id": f"service_offline_{service}",
                "source_field": "semantic_surfaces",
                "source_index": index,
                "expected_surface": surface,
                "readme_exists": readme.exists(),
                "readme_reference_present": surface in readme_text,
            }
            for index, surface in enumerate(coverage["semantic_surfaces"])
        ]
        missing_readme_semantic_surface_details = [
            check
            for check in readme_semantic_surface_checks
            if not check["readme_reference_present"]
        ]
        missing_readme_file_references = [
            check["expected_path"]
            for check in readme_file_reference_checks
            if check["expected_path"] not in readme_text
        ]
        missing_readme_file_reference_details = [
            {
                **check,
                "readme_exists": readme.exists(),
                "readme_reference_present": False,
            }
            for check in readme_file_reference_checks
            if check["expected_path"] not in readme_text
        ]
        readme_file_reference_checks = [
            {
                **check,
                "readme_exists": readme.exists(),
                "readme_reference_present": check["expected_path"] in readme_text,
            }
            for check in readme_file_reference_checks
        ]
        if not readme.exists():
            failures.append(f"SERVICE_OFFLINE_COVERAGE[{service}]: missing README {readme_path}")
        for surface in missing_readme_semantic_surfaces:
            failures.append(
                f"SERVICE_OFFLINE_COVERAGE[{service}]: {readme_path} missing semantic surface {surface!r}"
            )
        for path in missing_readme_file_references:
            failures.append(
                f"SERVICE_OFFLINE_COVERAGE[{service}]: {readme_path} missing offline helper/test file reference {path}"
            )
        service_offline_coverage_files.append(
            {
                "service": service,
                "checked_fields": path_fields,
                "required_nonempty_fields": required_fields,
                "readme_path": readme_path,
                "test_files": coverage["test_files"],
                "helper_files": coverage["helper_files"],
                "semantic_surfaces": coverage["semantic_surfaces"],
                "semantic_surface_count": len(coverage["semantic_surfaces"]),
                "field_counts": {
                    field: len(coverage[field]) for field in required_fields
                },
                "empty_required_fields": empty_required_fields,
                "file_count": len(checked_paths),
                "missing_files": missing_paths,
                "readme_semantic_surface_checks": readme_semantic_surface_checks,
                "readme_file_reference_checks": readme_file_reference_checks,
                "missing_readme_semantic_surfaces": missing_readme_semantic_surfaces,
                "missing_readme_semantic_surface_details": missing_readme_semantic_surface_details,
                "missing_readme_file_references": missing_readme_file_references,
                "missing_readme_file_reference_details": missing_readme_file_reference_details,
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
        {
            "surface": "raw_route_pressure_report_contract",
            "paths": [
                "docs/simulation-payload-contract.md",
                "sim/sim/report.py",
                "sim/tests/test_engine.py",
            ],
            "protects": "Raw route_pressure fallback fields stay documented and asserted by report tests.",
        },
        {
            "surface": "route_score_rationale_contract",
            "paths": [
                "docs/simulation-architecture.md",
                "docs/simulation-payload-contract.md",
            ],
            "protects": "Route-score rationale stays documented as evidence for self-sustainable protocol evolution.",
        },
        {
            "surface": "manual_combine_gate_hygiene",
            "paths": [
                "AGENTS.md",
                "docs/simulation-architecture.md",
            ],
            "protects": "Manual Evo combines keep inherited focused gates visible from benchmark-owned metadata.",
        },
        {
            "surface": "list_tasks_metadata_schema",
            "paths": [
                "benchmark_whole_app.py",
                "docs/simulation-architecture.md",
            ],
            "protects": "--list-tasks metadata fields stay declared in the benchmark schema and linked from docs.",
        },
        {
            "surface": "service_offline_protocol_docs",
            "paths": service_readme_paths(),
            "protects": "Service docs expose the offline protocol helper contracts named by service trace metadata.",
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
            raw_route_pressure_report_contract,
            route_score_rationale_contract,
            inherited_gate_guidance_contract,
            list_tasks_metadata_schema_contract,
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
        'PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}" "$VENVDIR/bin/python3" -m pytest tests/test_economy.py tests/test_engine.py::test_agent_generation tests/test_engine.py::test_scenarios tests/test_engine.py::test_self_sustainability_report_uses_raw_route_pressure_events_without_summary -q',
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


SERVICE_BUILD_TARGETS = {
    "cdp": 22,
    "stripe": 22,
    "atxp": 35,
}

SERVICE_BUILD_PHASES = {
    "install": {
        "command": "pnpm install --store-dir $PNPM_STORE_DIR --frozen-lockfile --prefer-offline --ignore-scripts",
        "target_seconds": 12,
        "log_anchors": ["Lockfile is up to date", "Already up to date", "Done in"],
    },
    "build": {
        "command": "pnpm run build",
        "target_seconds_ratio": 0.75,
        "log_anchors": ["tsc -p tsconfig.json"],
    },
}

SERVICE_OFFLINE_TARGETS = {
    "cdp": 22,
    "stripe": 22,
    "atxp": 35,
}

WEB_PHASE_TASKS = {
    "web_install": {
        "phase": "install",
        "command": "pnpm install --store-dir $PNPM_STORE_DIR --frozen-lockfile --prefer-offline --ignore-scripts",
        "target_seconds": 12,
        "log_anchors": ["Lockfile is up to date", "Already up to date", "Done in"],
    },
    "web_check": {
        "phase": "svelte_check",
        "command": "pnpm run check",
        "target_seconds": 35,
        "log_anchors": ["svelte-check", "found 0 errors"],
    },
    "web_build": {
        "phase": "vite_build",
        "command": "pnpm run build",
        "target_seconds": 45,
        "log_anchors": ["vite build", "built in", "Using @sveltejs/adapter-auto"],
    },
}


def web_phase_task_list() -> list[dict[str, Any]]:
    return [
        {
            "task_id": task_id,
            "phase": metadata["phase"],
            "command": metadata["command"],
            "target_seconds": metadata["target_seconds"],
            "log_anchors": metadata["log_anchors"],
        }
        for task_id, metadata in WEB_PHASE_TASKS.items()
    ]


def service_build_phase_task_id(service: str, phase: str) -> str:
    return f"service_{service}_{phase}"


def service_build_phase_target_seconds(service: str, phase: str) -> float:
    metadata = SERVICE_BUILD_PHASES[phase]
    if "target_seconds" in metadata:
        return metadata["target_seconds"]
    return round(SERVICE_BUILD_TARGETS[service] * metadata["target_seconds_ratio"], 2)


def service_build_phase_task_list(service: str) -> list[dict[str, Any]]:
    return [
        {
            "task_id": service_build_phase_task_id(service, phase),
            "service": service,
            "phase": phase,
            "command": metadata["command"],
            "target_seconds": service_build_phase_target_seconds(service, phase),
            "log_anchors": metadata["log_anchors"],
        }
        for phase, metadata in SERVICE_BUILD_PHASES.items()
    ]


def run_service_build_task(root: Path, service: str) -> tuple[float, dict[str, Any]]:
    target_seconds = SERVICE_BUILD_TARGETS[service]
    task_id = f"service_build_{service}"
    package_root = root / "services" / service
    node_modules_seed = seed_node_modules(root, package_root)
    component_task = {
        "task_id": task_id,
        "service": service,
        "package_root": f"services/{service}",
        "target_seconds": target_seconds,
        "node_modules_seed": node_modules_seed,
        "manual_phase_tasks": service_build_phase_task_list(service),
    }
    score = run_command(
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
            service_build_phase_task_list(service),
            task_id,
        ),
    )
    return score, component_task


def task_service_builds(root: Path) -> float:
    scores = []
    component_tasks = []
    for service in SERVICE_BUILD_TARGETS:
        score, component_task = run_service_build_task(root, service)
        scores.append(score)
        component_tasks.append(component_task)
    score = sum(scores) / len(scores)
    log_task(
        "service_builds_summary",
        score,
        summary=f"mean service build score {score:.4f}",
        component_scores=scores,
        trace_metadata=service_builds_summary_trace_metadata(component_tasks),
    )
    return score


def task_service_build_component(root: Path, service: str) -> float:
    score, _component_task = run_service_build_task(root, service)
    return score


def task_service_build_phase(root: Path, service: str, phase: str) -> float:
    package_root = root / "services" / service
    metadata = SERVICE_BUILD_PHASES[phase]
    node_modules_seed = seed_node_modules(root, package_root)
    task_id = service_build_phase_task_id(service, phase)
    validation_commands = [] if phase == "install" else [metadata["command"]]
    command = (
        pnpm_install_phase_command()
        if phase == "install"
        else pnpm_cached_install_command(metadata["command"])
    )
    return run_command(
        root,
        task_id,
        command,
        cwd=package_root,
        timeout=120,
        target_seconds=service_build_phase_target_seconds(service, phase),
        trace_metadata=pnpm_trace_metadata(
            root,
            package_root,
            validation_commands,
            node_modules_seed,
            service_build_phase_task_list(service),
            f"service_build_{service}",
        )
        | {
            "phase": {
                "kind": "service_build_validation_phase",
                "parent_task_id": f"service_build_{service}",
                "service": service,
                "phase": phase,
                "log_anchors": metadata["log_anchors"],
                "default_profile": False,
                "gate_profile": False,
            }
        },
    )


def run_service_offline_node_task(root: Path, service: str) -> tuple[float, dict[str, Any]]:
    target_seconds = SERVICE_OFFLINE_TARGETS[service]
    task_id = f"service_offline_{service}"
    package_root = root / "services" / service
    node_modules_seed = seed_node_modules(root, package_root)
    coverage = SERVICE_OFFLINE_COVERAGE[service]
    component_task = {
        "task_id": task_id,
        "service": service,
        "package_root": f"services/{service}",
        "target_seconds": target_seconds,
        "node_modules_seed": node_modules_seed,
        "validation_command": "pnpm run test:offline",
        "covered_test_files": coverage["test_files"],
        "covered_helper_files": coverage["helper_files"],
        "coverage_points": coverage["coverage_points"],
        "semantic_surfaces": coverage["semantic_surfaces"],
    }
    score = run_command(
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
        )
    )
    return score, component_task


def run_service_offline_ap2_task(root: Path) -> tuple[float, dict[str, Any]]:
    component_task = {
        "task_id": "service_offline_ap2",
        "service": "ap2",
        "package_root": "services/ap2",
        "target_seconds": 4,
        "validation_command": "PYTHONPATH=src python3 -m unittest discover -s tests -q",
        "covered_test_files": SERVICE_OFFLINE_COVERAGE["ap2"]["test_files"],
        "covered_helper_files": SERVICE_OFFLINE_COVERAGE["ap2"]["helper_files"],
        "coverage_points": SERVICE_OFFLINE_COVERAGE["ap2"]["coverage_points"],
        "semantic_surfaces": SERVICE_OFFLINE_COVERAGE["ap2"]["semantic_surfaces"],
    }
    score = run_command(
        root,
        "service_offline_ap2",
        "PYTHONPATH=src python3 -m unittest discover -s tests -q",
        cwd=root / "services" / "ap2",
        timeout=60,
        target_seconds=4,
        trace_metadata=service_offline_python_trace_metadata(root),
    )
    return score, component_task


def task_service_offline_protocol_tests(root: Path) -> float:
    scores = []
    component_tasks = []
    for service in SERVICE_OFFLINE_TARGETS:
        score, component_task = run_service_offline_node_task(root, service)
        scores.append(score)
        component_tasks.append(component_task)

    score, ap2_task = run_service_offline_ap2_task(root)
    scores.append(score)
    component_tasks.append(ap2_task)

    score = sum(scores) / len(scores)
    log_task(
        "service_offline_protocol_tests",
        score,
        summary=f"mean service offline protocol test score {score:.4f}",
        component_scores=scores,
        trace_metadata=service_offline_tests_summary_trace_metadata(component_tasks),
    )
    return score


def task_service_offline_component(root: Path, service: str) -> float:
    if service == "ap2":
        score, _component_task = run_service_offline_ap2_task(root)
        return score
    score, _component_task = run_service_offline_node_task(root, service)
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
            web_phase_task_list(),
            "web_check_build",
        ),
    )


def task_web_phase(root: Path, task_id: str) -> float:
    package_root = root / "web"
    phase = WEB_PHASE_TASKS[task_id]
    node_modules_seed = seed_node_modules(root, package_root)
    validation_commands = [] if task_id == "web_install" else [phase["command"]]
    command = (
        pnpm_install_phase_command()
        if task_id == "web_install"
        else pnpm_cached_install_command(phase["command"])
    )
    return run_command(
        root,
        task_id,
        command,
        cwd=package_root,
        timeout=120,
        target_seconds=phase["target_seconds"],
        trace_metadata=pnpm_trace_metadata(
            root,
            package_root,
            validation_commands,
            node_modules_seed,
            web_phase_task_list(),
            "web_check_build",
        )
        | {
            "phase": {
                "kind": "web_validation_phase",
                "parent_task_id": "web_check_build",
                "phase": phase["phase"],
                "log_anchors": phase["log_anchors"],
                "default_profile": False,
                "gate_profile": False,
            }
        },
    )


BENCHMARK_PROFILE_TASK_IDS = [
    "static_contracts",
    "python_compile",
    "python_sim_tests",
    "rust_engine_tests",
    "service_builds_summary",
    "service_offline_protocol_tests",
    "web_check_build",
]

GATE_PROFILE_TASK_IDS = [
    "static_contracts",
    "python_compile",
]


def task_runners() -> dict[str, Any]:
    return {
        "static_contracts": task_static_contracts,
        "python_compile": task_python_compile,
        "python_sim_tests": task_python_tests,
        "rust_engine_tests": task_rust_tests,
        "service_build_cdp": lambda root: task_service_build_component(root, "cdp"),
        "service_build_stripe": lambda root: task_service_build_component(root, "stripe"),
        "service_build_atxp": lambda root: task_service_build_component(root, "atxp"),
        "service_builds_summary": task_service_builds,
        "service_cdp_install": lambda root: task_service_build_phase(root, "cdp", "install"),
        "service_cdp_build": lambda root: task_service_build_phase(root, "cdp", "build"),
        "service_stripe_install": lambda root: task_service_build_phase(root, "stripe", "install"),
        "service_stripe_build": lambda root: task_service_build_phase(root, "stripe", "build"),
        "service_atxp_install": lambda root: task_service_build_phase(root, "atxp", "install"),
        "service_atxp_build": lambda root: task_service_build_phase(root, "atxp", "build"),
        "service_offline_cdp": lambda root: task_service_offline_component(root, "cdp"),
        "service_offline_stripe": lambda root: task_service_offline_component(root, "stripe"),
        "service_offline_atxp": lambda root: task_service_offline_component(root, "atxp"),
        "service_offline_ap2": lambda root: task_service_offline_component(root, "ap2"),
        "service_offline_protocol_tests": task_service_offline_protocol_tests,
        "web_install": lambda root: task_web_phase(root, "web_install"),
        "web_check": lambda root: task_web_phase(root, "web_check"),
        "web_build": lambda root: task_web_phase(root, "web_build"),
        "web_check_build": task_web_check,
    }


def task_catalog() -> list[dict[str, Any]]:
    benchmark_tasks = set(BENCHMARK_PROFILE_TASK_IDS)
    gate_tasks = set(GATE_PROFILE_TASK_IDS)
    catalog = []
    for task_id in task_runners():
        entry = {
            "task_id": task_id,
            "benchmark_profile": task_id in benchmark_tasks,
            "gate_profile": task_id in gate_tasks,
        }
        for service in SERVICE_BUILD_TARGETS:
            for phase_task in service_build_phase_task_list(service):
                if phase_task["task_id"] == task_id:
                    entry.update(
                        {
                            "category": "service_build_phase",
                            "parent_task_id": f"service_build_{service}",
                            "service": service,
                            "phase": phase_task["phase"],
                            "command": phase_task["command"],
                            "target_seconds": phase_task["target_seconds"],
                        }
                    )
                    break
            if entry.get("category") == "service_build_phase":
                break
        for phase_task in web_phase_task_list():
            if phase_task["task_id"] == task_id:
                entry.update(
                    {
                        "category": "web_build_phase",
                        "parent_task_id": "web_check_build",
                        "phase": phase_task["phase"],
                        "command": phase_task["command"],
                        "target_seconds": phase_task["target_seconds"],
                    }
                )
                break
        if task_id == "web_check_build":
            web_task_ids = [task["task_id"] for task in web_phase_task_list()]
            entry["manual_validation_task_ids"] = web_task_ids
            entry["manual_selection"] = f"--task-ids {','.join(web_task_ids)}"
        if task_id == "service_builds_summary":
            service_task_ids = [
                task["task_id"]
                for service in SERVICE_BUILD_TARGETS
                for task in service_build_phase_task_list(service)
            ]
            entry["manual_validation_task_ids"] = service_task_ids
            entry["manual_selection"] = f"--task-ids {','.join(service_task_ids)}"
        duplicate_validation = focused_gate_duplicate_validation_metadata()
        if task_id.startswith("service_offline_"):
            service = task_id.removeprefix("service_offline_")
            if service in SERVICE_OFFLINE_COVERAGE:
                coverage = SERVICE_OFFLINE_COVERAGE[service]
                entry.update(
                    {
                        "category": "service_offline_protocol",
                        "service": service,
                        "covered_test_files": coverage["test_files"],
                        "covered_helper_files": coverage["helper_files"],
                        "coverage_points": coverage["coverage_points"],
                        "semantic_surfaces": coverage["semantic_surfaces"],
                    }
                )
        if task_id == "service_offline_protocol_tests":
            entry["semantic_surfaces_by_service"] = {
                service: coverage["semantic_surfaces"]
                for service, coverage in SERVICE_OFFLINE_COVERAGE.items()
            }
        if task_id == duplicate_validation["benchmark_aggregate_task_id"]:
            entry["duplicate_validation"] = duplicate_validation
        else:
            duplicate_entries = [
                item
                for item in FOCUSED_GATE_DUPLICATE_VALIDATION
                if item["focused_task_id"] == task_id
            ]
            if duplicate_entries:
                entry["duplicate_validation"] = {
                    "kind": duplicate_validation["kind"],
                    "entries": duplicate_entries,
                    "note": duplicate_validation["note"],
                }
        matching_gates = [
            gate
            for gate in INHERITED_GATE_GUIDANCE
            if task_id in gate["related_task_ids"]
        ]
        if matching_gates:
            entry["preserved_gate_names"] = [gate["name"] for gate in matching_gates]
        catalog.append(entry)
    return catalog


def list_tasks() -> float:
    print(
        json.dumps(
            list_tasks_payload(),
            indent=2,
        )
    )
    return 0.0


def parse_task_selection(
    repeated_task_ids: list[str] | None,
    comma_task_ids: str | None,
) -> list[str]:
    raw_values = []
    if repeated_task_ids:
        raw_values.extend(repeated_task_ids)
    if comma_task_ids:
        raw_values.append(comma_task_ids)

    selected: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        for task_id in value.split(","):
            task_id = task_id.strip()
            if not task_id or task_id in seen:
                continue
            selected.append(task_id)
            seen.add(task_id)
    return selected


def run_selected_tasks(root: Path, selected_task_ids: list[str], profile: str) -> float:
    runners = task_runners()
    unknown_task_ids = [
        task_id for task_id in selected_task_ids if task_id not in runners
    ]
    if unknown_task_ids:
        known = ", ".join(runners)
        raise SystemExit(
            f"unknown task id(s): {', '.join(unknown_task_ids)}. Known task ids: {known}"
        )

    scores = [runners[task_id](root) for task_id in selected_task_ids]
    return write_result(
        sum(scores) / len(scores),
        result_metadata={
            "profile": profile,
            "selection_mode": "manual_task_ids",
            "selected_task_ids": selected_task_ids,
        },
    )


def run_benchmark(root: Path) -> float:
    runners = task_runners()
    scores = [runners[task_id](root) for task_id in BENCHMARK_PROFILE_TASK_IDS]
    return write_result(sum(scores) / len(scores))


def run_gate(root: Path) -> float:
    runners = task_runners()
    scores = [runners[task_id](root) for task_id in GATE_PROFILE_TASK_IDS]
    return write_result(sum(scores) / len(scores))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target")
    parser.add_argument("--profile", choices=["benchmark", "gate"], default="benchmark")
    parser.add_argument("--min-score", type=float)
    parser.add_argument(
        "--list-tasks",
        action="store_true",
        help="Print valid manual task ids and default profile membership, then exit.",
    )
    parser.add_argument(
        "--task-id",
        action="append",
        dest="task_ids",
        help="Run one task id for manual validation; repeat for multiple tasks.",
    )
    parser.add_argument(
        "--task-ids",
        dest="task_id_csv",
        help="Comma-separated task ids for manual validation.",
    )
    args = parser.parse_args()

    if args.list_tasks:
        list_tasks()
        return 0

    if not args.target:
        raise SystemExit("--target is required unless --list-tasks is used")

    root = Path(args.target).resolve()
    if not root.is_dir():
        raise SystemExit(f"target must be the repository root directory, got {root}")

    selected_task_ids = parse_task_selection(args.task_ids, args.task_id_csv)
    score = (
        run_selected_tasks(root, selected_task_ids, args.profile)
        if selected_task_ids
        else run_gate(root) if args.profile == "gate" else run_benchmark(root)
    )
    if args.min_score is not None and score < args.min_score:
        print(
            f"GATE FAIL: score {score:.4f} below minimum {args.min_score:.4f}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
