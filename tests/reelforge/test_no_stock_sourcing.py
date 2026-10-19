"""ReelForge must never source stock footage (build-plan §1).

ReelForge composes the user's *uploaded screen recording*
(``ReelForgeParams.screen_recording_key``) under the avatar — it must NOT
reach for MoneyPrinterTurbo's stock-footage path
(``app.services.material.download_videos`` / the Pexels / Pixabay / Coverr
search functions). MPT's original path is left intact in the fork for MPT
compatibility, but the ReelForge stage functions and Celery worker modules must
neither import nor invoke it.

This module enforces that with two complementary, network-free checks:

1. **Static import-graph assertion** — parse every ReelForge stage/worker source
   file with :mod:`ast` and collect *all* imports (module-level *and* the lazy
   in-function imports the pipeline uses). None may reference
   ``app.services.material`` or any ``pexels`` / ``pixabay`` / ``coverr``
   provider module.

2. **Source-scan assertion** — with comments and docstrings stripped, assert no
   executable line references the forbidden stock-sourcing symbols
   (``download_videos``, ``search_videos_pexels``, …) as whole words, so a
   substring like ``re-materialize`` never trips a false positive.

A positive assertion also pins ``stage_compose`` to ``screen_recording_key`` so
the "use the uploaded recording" contract can't silently regress.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Files under contract: the ReelForge stage transforms + the worker modules
# that orchestrate them. MPT's own modules (app/services/material.py, the MPT
# task entrypoints) are deliberately NOT listed — the fork keeps them working.
# --------------------------------------------------------------------------- #
_REPO_ROOT = Path(__file__).resolve().parents[2]

_REELFORGE_SOURCE_FILES: tuple[Path, ...] = (
    _REPO_ROOT / "apps" / "api" / "app" / "services" / "reelforge.py",
    _REPO_ROOT / "apps" / "api" / "app" / "workers" / "__init__.py",
    _REPO_ROOT / "apps" / "api" / "app" / "workers" / "tasks.py",
    _REPO_ROOT / "apps" / "api" / "app" / "workers" / "pipeline.py",
    _REPO_ROOT / "apps" / "api" / "app" / "workers" / "context.py",
    _REPO_ROOT / "apps" / "api" / "app" / "workers" / "celery_app.py",
)

# Fully-qualified modules the ReelForge graph must never pull in.
_FORBIDDEN_IMPORT_MODULES: tuple[str, ...] = (
    "app.services.material",
)

# Provider substrings that betray a stock-footage dependency wherever they hide
# (import path, function name, symbol import).
_FORBIDDEN_PROVIDER_TOKENS: tuple[str, ...] = (
    "pexels",
    "pixabay",
    "coverr",
)

# Stock-sourcing entrypoints that must never be imported or invoked by name.
_FORBIDDEN_SYMBOLS: tuple[str, ...] = (
    "download_videos",
    "search_videos_pexels",
    "search_videos_pixabay",
    "search_videos_coverr",
)


def _iter_existing_files() -> list[Path]:
    present = [p for p in _REELFORGE_SOURCE_FILES if p.is_file()]
    assert present, "no ReelForge source files found; fix _REELFORGE_SOURCE_FILES"
    return present


def _collect_imports(tree: ast.AST) -> list[tuple[str, str]]:
    """Return every ``(module, imported_name)`` pair in ``tree``.

    ``ast.walk`` reaches imports nested inside functions, so the lazy
    ``from app.services... import ...`` calls the pipeline uses are covered too.
    ``imported_name`` is the empty string for a bare ``import x`` statement.
    """
    pairs: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            pairs.extend((alias.name, "") for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            pairs.extend((module, alias.name) for alias in node.names)
    return pairs


def _strip_comments_and_docstrings(source: str) -> str:
    """Return ``source`` with comments and string literals blanked out.

    Comments are dropped via :mod:`tokenize`; string tokens (which include
    docstrings and any incidental prose) are replaced with an empty literal so a
    forbidden word appearing only inside documentation never trips the scan,
    while real ``foo = download_videos(...)`` calls remain visible.
    """
    out: list[str] = []
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING:
            out.append('""')
            continue
        out.append(tok.string)
    return " ".join(out)


# --------------------------------------------------------------------------- #
# 1. Static import-graph: no stock-sourcing module is ever imported.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", _iter_existing_files(), ids=lambda p: p.name)
def test_reelforge_module_never_imports_stock_sourcing(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = _collect_imports(tree)

    for module, name in imports:
        qualified = f"{module}.{name}" if name else module
        lowered = qualified.lower()

        for forbidden in _FORBIDDEN_IMPORT_MODULES:
            assert not (
                module == forbidden or module.startswith(forbidden + ".")
            ), f"{path.name} imports stock-sourcing module {qualified!r}"

        for token in _FORBIDDEN_PROVIDER_TOKENS:
            assert token not in lowered, (
                f"{path.name} imports stock provider token {token!r} via {qualified!r}"
            )

        assert name not in _FORBIDDEN_SYMBOLS, (
            f"{path.name} imports stock-sourcing symbol {name!r} from {module!r}"
        )


# --------------------------------------------------------------------------- #
# 2. Source scan: no stock-sourcing symbol is invoked in executable code.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", _iter_existing_files(), ids=lambda p: p.name)
def test_reelforge_module_never_invokes_stock_sourcing(path: Path) -> None:
    code = _strip_comments_and_docstrings(path.read_text(encoding="utf-8"))

    for symbol in _FORBIDDEN_SYMBOLS:
        assert not re.search(rf"\b{re.escape(symbol)}\b", code), (
            f"{path.name} references stock-sourcing symbol {symbol!r} in code"
        )

    for token in _FORBIDDEN_PROVIDER_TOKENS:
        assert not re.search(rf"\b{re.escape(token)}\w*", code, re.IGNORECASE), (
            f"{path.name} references stock provider {token!r} in code"
        )

    # Whole-word "material" as a bare name/attribute would betray a dependency on
    # app.services.material even without an explicit import (e.g. a rebound alias);
    # "re-materialize" and friends are hyphenated prose and never survive as tokens.
    assert not re.search(r"\bmaterial\b", code), (
        f"{path.name} references the stock 'material' module in code"
    )


# --------------------------------------------------------------------------- #
# 3. Positive contract: stage_compose uses the uploaded screen recording.
# --------------------------------------------------------------------------- #
def test_stage_compose_uses_uploaded_screen_recording() -> None:
    from app.services import reelforge

    compose_src = _REPO_ROOT / "apps" / "api" / "app" / "services" / "reelforge.py"
    tree = ast.parse(compose_src.read_text(encoding="utf-8"), filename=str(compose_src))

    func = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "stage_compose"
        ),
        None,
    )
    assert func is not None, "stage_compose is missing from app/services/reelforge.py"

    attrs = {
        node.attr
        for node in ast.walk(func)
        if isinstance(node, ast.Attribute)
    }
    assert "screen_recording_key" in attrs, (
        "stage_compose must source the video from params.screen_recording_key"
    )

    # And the module surfaces the stage transform without a stock-sourcing hook.
    assert hasattr(reelforge, "stage_compose")
    assert not hasattr(reelforge, "download_videos")
