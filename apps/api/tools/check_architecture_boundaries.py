#!/usr/bin/env python3
"""Enforce product/external isolation and immutable workflow manifests."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = REPO_ROOT / "apps" / "api"
PRODUCT_PYTHON_ROOTS = (API_ROOT / "app", API_ROOT / "engine" / "reelforge_engine")
MANIFEST_ROOT = API_ROOT / "assets" / "workflows" / "manifests"
PLATFORM_CONSUMER_ROOTS = (API_ROOT / "app" / "domains", API_ROOT / "app" / "workers")
CLIENT_SOURCE_ROOTS = (
    REPO_ROOT / "apps" / "web",
    REPO_ROOT / "apps" / "mobile",
    REPO_ROOT / "apps" / "desktop" / "src",
    REPO_ROOT / "packages" / "sdk-typescript" / "src",
    REPO_ROOT / "packages" / "sdk-python" / "reelforge_sdk",
)


def external_import_violations() -> list[str]:
    violations: list[str] = []
    for root in PRODUCT_PYTHON_ROOTS:
        for path in root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}: invalid Python: {exc}"
                )
                continue
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                for name in names:
                    if name == "external" or name.startswith("external."):
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)}:{node.lineno}: forbidden runtime import {name!r}"
                        )
    return violations


def registry_violations() -> list[str]:
    registry = (REPO_ROOT / "external" / "REGISTRY.md").read_text(encoding="utf-8")
    return [
        f"external/{directory.name}: missing from external/REGISTRY.md"
        for directory in sorted((REPO_ROOT / "external").iterdir())
        if directory.is_dir() and f"| {directory.name} |" not in registry
    ]


def legacy_platform_import_violations() -> list[str]:
    """Prevent migrated domains/workers from returning to legacy service paths."""
    violations: list[str] = []
    for root in PLATFORM_CONSUMER_ROOTS:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                for name in names:
                    if name == "app.services.storage" or name.startswith(
                        "app.services.storage."
                    ):
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                            f"use app.platform.storage instead of {name!r}"
                        )
                    if name == "app.controllers.v1.jobs" or name.startswith(
                        "app.controllers.v1.jobs."
                    ):
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                            "domains/workers must use core, platform, or domain services "
                            "instead of the reels compatibility controller"
                        )
    return violations


def root_router_violations() -> list[str]:
    """Keep application composition at domain granularity.

    Even legacy video/LLM compatibility routes are composed through a contained
    domain. New product routes must first acquire a domain.
    """
    path = API_ROOT / "app" / "router.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module != "app.controllers.v1":
            continue
        names = {alias.name for alias in node.names}
        if names:
            violations.append(
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: root router must compose "
                "all routes from app.domains, never app.controllers.v1"
            )
    return violations


def workspace_violations() -> list[str]:
    """Pin the deployable workspace graph described by the architecture."""
    violations: list[str] = []
    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    actual_npm = set(package.get("workspaces") or [])
    expected_npm = {"apps/web", "apps/mobile", "packages/*"}
    if actual_npm != expected_npm:
        violations.append(
            "package.json: npm workspaces must include both JS clients and every "
            f"repository package (found {sorted(actual_npm)})"
        )
    cargo = tomllib.loads((REPO_ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    cargo_members = set(cargo.get("workspace", {}).get("members") or [])
    expected_cargo = {"apps/desktop", "apps/desktop/crates/*"}
    if cargo_members != expected_cargo:
        violations.append(
            "Cargo.toml: Rust workspace must contain the desktop root and its crates "
            f"(found {sorted(cargo_members)})"
        )
    return violations


def client_contract_violations() -> list[str]:
    """Prevent clients and SDKs from returning to legacy B-roll routes."""
    violations: list[str] = []
    route_pattern = re.compile(r"[\"'`]\/broll\/")
    ignored_parts = {"node_modules", ".next", "dist", "electron-legacy"}
    for root in CLIENT_SOURCE_ROOTS:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".ts", ".tsx", ".rs", ".py"}:
                continue
            if ignored_parts.intersection(path.parts):
                continue
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if route_pattern.search(line):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{line_number}: clients must use "
                        "canonical /generation/broll/* routes"
                    )
    return violations


def manifest_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(MANIFEST_ROOT.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        label = path.relative_to(REPO_ROOT)
        workflow_value = str(data.get("workflow_file") or "")
        workflow_path = (path.parent / workflow_value).resolve()
        if not workflow_value or not workflow_path.is_file():
            violations.append(f"{label}: workflow_file does not resolve to a file")
            continue
        expected = str(data.get("workflow_sha256") or "").lower()
        actual = hashlib.sha256(workflow_path.read_bytes()).hexdigest()
        if expected != actual:
            violations.append(f"{label}: workflow_sha256 mismatch (actual {actual})")
        status = str(data.get("status") or "")
        dispatch_enabled = data.get("dispatch_enabled") is True
        operations = data.get("operations") or {}
        upstream = data.get("upstream") or {}
        outputs = data.get("outputs") or {}
        if status != "approved" and dispatch_enabled:
            violations.append(f"{label}: only approved manifests may enable dispatch")
        if status == "approved":
            if not operations.get("approved_at"):
                violations.append(
                    f"{label}: approved manifest needs operations.approved_at"
                )
            if upstream.get("weights_license_review") in (None, "", "pending"):
                violations.append(
                    f"{label}: approved manifest needs completed weights license review"
                )
            if outputs.get("video_node") in (None, "", "pending-export"):
                violations.append(
                    f"{label}: approved manifest needs a concrete video output node"
                )
    return violations


def main() -> int:
    violations = [
        *external_import_violations(),
        *legacy_platform_import_violations(),
        *root_router_violations(),
        *workspace_violations(),
        *client_contract_violations(),
        *registry_violations(),
        *manifest_violations(),
    ]
    if violations:
        print("Architecture boundary violations:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1
    print("Architecture boundaries and workflow manifests are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
