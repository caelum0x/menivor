"""Static dependency-completeness guard for the Menivor settlement path.

This is the regression test for the ``blake3`` production outage: ``blake3`` was
declared in ``pyproject.toml`` (the canonical dependency source) but MISSING from
the root ``requirements.txt`` that ``apps/api/Dockerfile`` actually installs from
(``COPY requirements.txt`` -> ``pip install -r requirements.txt``). The api image
therefore lacked the module, ``import blake3`` in
``app/domains/wallet/hold_settlement_attestation.py`` raised
``ModuleNotFoundError`` at runtime, every Mint ``hold.capture`` 502'd, and the
wallet could never settle a render Replicate had already been paid for.

These tests fail-closed on that ENTIRE class of bug -- a runtime module importing
a package that is declared in ``pyproject.toml`` but absent from the Dockerfile's
``requirements.txt`` (or not installable at all) -- so it can never silently ship
again.

Two complementary guards:

* :func:`test_settlement_runtime_imports_are_declared_and_installed` -- an AST
  scan of the wallet / settlement / attestation runtime modules. Every
  third-party top-level import there that is declared in ``pyproject.toml`` must
  also be a direct entry in ``requirements.txt`` AND be importable now. This is
  the import-driven catcher that would have caught ``blake3`` at the exact site
  of the failure.
* :func:`test_pyproject_core_dependencies_are_mirrored_in_requirements` -- the
  manifest-level catcher: every core (non-optional) dependency in
  ``pyproject.toml`` must be mirrored in the Dockerfile's ``requirements.txt``.
  This catches drift regardless of whether an import already exists, encoding the
  "Keep in sync with pyproject.toml" comment the manifest itself carries.

Stdlib-only: uses ``ast`` + a tiny requirements/pyproject parser. No network, no
Docker, no live server.
"""

from __future__ import annotations

import ast
import re
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

# tests/reelforge/ -> repo root is two parents up.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REQUIREMENTS = _REPO_ROOT / "requirements.txt"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_APP_ROOT = _REPO_ROOT / "apps" / "api" / "app"

# The runtime modules on the money-settlement / attestation path. A missing
# dependency in ANY of these fails a real render's settlement at runtime, so they
# are held to the strict "direct import must be a direct requirement" invariant.
_SETTLEMENT_MODULES = (
    _APP_ROOT / "domains" / "wallet",
    _APP_ROOT / "services" / "crypto_tokens.py",
)


def _canonical(name: str) -> str:
    """PEP 503 style normalization so ``edge_tts`` == ``edge-tts`` etc."""
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def _parse_requirement_names(text: str) -> set[str]:
    """Canonical distribution names from a ``requirements.txt`` body."""
    names: set[str] = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        # Strip version specifiers, extras, markers, urls: keep the bare name.
        name = re.split(r"[=<>!~;\[\s@]", line, 1)[0]
        if name:
            names.add(_canonical(name))
    return names


def _parse_pyproject_core_names(pyproject_text: str) -> set[str]:
    """Canonical distribution names from ``[project].dependencies`` (core only).

    ``[project.optional-dependencies]`` are intentionally excluded -- those are
    import-guarded accelerators that are NOT installed by default.
    """
    data = tomllib.loads(pyproject_text)
    names: set[str] = set()
    for dep in data.get("project", {}).get("dependencies", []):
        name = re.split(r"[=<>!~;\[\s@]", dep.strip(), 1)[0]
        if name:
            names.add(_canonical(name))
    return names


def _iter_python_files(*targets: Path):
    for target in targets:
        if target.is_dir():
            yield from sorted(target.rglob("*.py"))
        elif target.suffix == ".py":
            yield target


def _top_level_third_party_imports(*targets: Path) -> dict[str, list[str]]:
    """Map each absolute top-level import name -> list of files that import it.

    Only ABSOLUTE imports are considered (relative ``from . import x`` are
    first-party). Stdlib and first-party (``app`` / test packages) are excluded.
    """
    import sys

    stdlib = set(sys.stdlib_module_names)
    first_party = {"app", "tests", "engine", "runtime", "tools", "webui", "cli"}
    found: dict[str, list[str]] = {}
    for path in _iter_python_files(*targets):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    names.add(node.module.split(".")[0])
        for name in names:
            if name in stdlib or name in first_party:
                continue
            found.setdefault(name, []).append(
                str(path.relative_to(_REPO_ROOT))
            )
    return found


def _dependency_violations(
    imports: dict[str, list[str]],
    requirement_names: set[str],
    pyproject_core_names: set[str],
    import_to_dists: dict[str, list[str]],
) -> list[tuple[str, str, list[str]]]:
    """Pure classifier so the guard can be proven against synthetic manifests.

    A violation is a runtime third-party import whose distribution is DECLARED in
    ``pyproject.toml`` but is either not installed, or absent from the
    Dockerfile's ``requirements.txt``. Returns ``(import, reason, files)`` tuples.
    """
    violations: list[tuple[str, str, list[str]]] = []
    for import_name, files in sorted(imports.items()):
        dists = import_to_dists.get(import_name)
        if not dists:
            # Not installed in the current interpreter at all: if it is declared
            # in pyproject it is a genuine missing runtime dependency.
            if _canonical(import_name) in pyproject_core_names:
                violations.append((import_name, "declared but NOT installed", files))
            continue
        canon_dists = {_canonical(d) for d in dists}
        declared_in_pyproject = bool(canon_dists & pyproject_core_names)
        in_requirements = bool(canon_dists & requirement_names)
        if declared_in_pyproject and not in_requirements:
            violations.append(
                (
                    import_name,
                    "in pyproject.toml but MISSING from requirements.txt "
                    "(Dockerfile manifest)",
                    files,
                )
            )
    return violations


def test_settlement_runtime_imports_are_declared_and_installed():
    """Every settlement-path third-party import must ship in the Docker image.

    This is the test that would have caught the blake3 outage: blake3 is imported
    by ``hold_settlement_attestation.py``, declared in pyproject, and (after the
    fix) present in requirements.txt.
    """
    requirement_names = _parse_requirement_names(_REQUIREMENTS.read_text())
    pyproject_core = _parse_pyproject_core_names(_PYPROJECT.read_text())
    imports = _top_level_third_party_imports(*_SETTLEMENT_MODULES)
    import_to_dists = packages_distributions()

    # Sanity: the scan actually reaches the attestation crypto imports.
    assert "blake3" in imports, "AST scan did not see the blake3 import"
    assert "cryptography" in imports, "AST scan did not see the cryptography import"

    violations = _dependency_violations(
        imports, requirement_names, pyproject_core, import_to_dists
    )
    assert not violations, (
        "settlement-path modules import packages that the Docker image would "
        "lack (pyproject-vs-requirements drift):\n"
        + "\n".join(f"  - {name}: {reason} (used in {files})" for name, reason, files in violations)
    )


def test_pyproject_core_dependencies_are_mirrored_in_requirements():
    """The Dockerfile's requirements.txt must mirror every core pyproject dep.

    ``requirements.txt`` even carries a "Keep in sync with pyproject.toml"
    comment; this asserts it. Catches drift (blake3, cryptography) at the
    manifest level, independent of whether any code imports it yet.
    """
    requirement_names = _parse_requirement_names(_REQUIREMENTS.read_text())
    pyproject_core = _parse_pyproject_core_names(_PYPROJECT.read_text())
    missing = sorted(pyproject_core - requirement_names)
    assert not missing, (
        "core dependencies declared in pyproject.toml are missing from the "
        f"Dockerfile's requirements.txt: {missing}"
    )


def test_guard_catches_a_removed_core_dependency():
    """Prove the guard has teeth: strip blake3 from a copy of requirements.txt
    and confirm the classifier flags it -- and does NOT flag it when present.

    This makes the "temporarily remove blake3" proof a durable, self-contained
    regression rather than a one-off manual demonstration.
    """
    real_text = _REQUIREMENTS.read_text()
    real_names = _parse_requirement_names(real_text)
    assert "blake3" in real_names, "precondition: blake3 is present after the fix"

    stripped_text = "\n".join(
        line for line in real_text.splitlines() if "blake3" not in line
    )
    stripped_names = _parse_requirement_names(stripped_text)
    assert "blake3" not in stripped_names

    pyproject_core = _parse_pyproject_core_names(_PYPROJECT.read_text())
    imports = _top_level_third_party_imports(*_SETTLEMENT_MODULES)
    import_to_dists = packages_distributions()

    # With blake3 removed from the manifest, the guard reports blake3.
    stripped_violations = _dependency_violations(
        imports, stripped_names, pyproject_core, import_to_dists
    )
    assert any(name == "blake3" for name, _reason, _files in stripped_violations), (
        "guard failed to flag blake3 when it was removed from requirements.txt"
    )

    # With the real (fixed) manifest, blake3 is NOT a violation.
    real_violations = _dependency_violations(
        imports, real_names, pyproject_core, import_to_dists
    )
    assert not any(name == "blake3" for name, _reason, _files in real_violations)


def test_pyjwt_pin_in_requirements_is_declared_in_pyproject():
    """Worktree venvs install from pyproject; the image from requirements.txt.

    PyJWT (Clerk and Scribase token checks) was pinned only in requirements.txt,
    so a venv built from pyproject lacked ``jwt``. Both manifests carry the same pin.
    """
    def pins(lines):
        return {_canonical(re.split(r"==", line, 1)[0]): line.split("==", 1)[1].strip()
                for line in lines if "==" in line and _canonical(line.split("==", 1)[0]) == "pyjwt"}

    req_lines = [raw.split("#", 1)[0].strip() for raw in _REQUIREMENTS.read_text().splitlines()]
    deps = tomllib.loads(_PYPROJECT.read_text())["project"]["dependencies"]
    in_requirements, in_pyproject = pins(req_lines), pins(d.strip() for d in deps)
    assert in_requirements.get("pyjwt"), "requirements.txt pins PyJWT"
    assert in_pyproject == in_requirements, (in_pyproject, in_requirements)
