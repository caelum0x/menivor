"""FFmpeg-expression bridge — renders the shared kernel math as per-frame FFmpeg
filter expressions.

``kernels.py`` returns the *numeric* transform/filter params at a normalized time
``t`` (used by the live preview + golden fixtures). The render executor
(``app/services/compose/vfx.py``) needs those SAME curves as **FFmpeg filter
expressions** it can splice into a ``scale=...:eval=frame`` / ``crop`` / ``rotate``
chain so a rendered frame at time ``t`` carries the exact value the preview shows.

This module is the single source of truth that binds the two: every builder here
mirrors a function in ``easing.py`` / ``kernels.py`` but emits an FFmpeg
expression **string** (in a caller-supplied normalized-time sub-expression
``tn``) instead of a float. Because the kernels are pure polynomial / exact-
integer math (no ``sin``/``pow`` transcendentals, all intermediates < 2**53),
FFmpeg's ``double`` evaluation of these strings is bit-identical to the Python /
TypeScript numeric kernels — see :func:`evaluate` and the parity tests.

Only the whitelisted FFmpeg operators/functions are used so the output stays
portable and :func:`evaluate` can faithfully model FFmpeg's semantics:
``+ - * /``, ``clip``, ``if``, ``lt``, ``gte``, ``floor``, ``min``, ``max``,
``abs``.
"""

from __future__ import annotations

import ast
import math
import re
from typing import NamedTuple

# Knuth multiplicative hash — must match ``easing.noise1`` / ``keyframe.ts``.
_HASH = 2654435761
_MOD = 4294967296  # 2**32


# --------------------------------------------------------------------------- #
# Easing primitives -> FFmpeg expression strings (mirror ``easing.py``).
# ``tn`` is any FFmpeg sub-expression for normalized time; it is clamped to
# [0,1] here exactly like ``easing.clamp01`` so callers can pass a raw
# ``(t/duration)`` progress term.
# --------------------------------------------------------------------------- #
def clamp01_expr(tn: str) -> str:
    return f"(clip(({tn}),0,1))"


def linear_expr(tn: str) -> str:
    """Mirror ``easing.linear`` — clamped identity."""
    return clamp01_expr(tn)


def ease_in_out_expr(tn: str) -> str:
    """Mirror ``easing.ease_in_out`` — quadratic ease-in-out on [0,1]."""
    t = clamp01_expr(tn)
    return f"(if(lt({t},0.5),2*{t}*{t},1-2*(1-{t})*(1-{t})))"


def peak_expr(tn: str) -> str:
    """Mirror ``easing.peak`` — parabola peaking at t=0.5."""
    t = clamp01_expr(tn)
    return f"(4*{t}*(1-{t}))"


def noise1_expr(n_expr: str, seed: int = 0) -> str:
    """Mirror ``easing.noise1`` — deterministic pseudo-noise in [-1, 1].

    The modulo is written with ``floor`` (not FFmpeg ``mod``) so it matches
    Python's ``%`` exactly for the positive operands used here; every
    intermediate stays < 2**53 so ``double`` arithmetic is exact.
    """
    m = f"((({n_expr})+({int(seed)}))*{_HASH})"
    h = f"({m}-floor({m}/{_MOD})*{_MOD})"
    return f"({h}/{_MOD}*2-1)"


def _round_expr(x: str) -> str:
    # FFmpeg has no round(); ``floor(x+0.5)`` matches ``int(round(...))`` for the
    # non-half-integer frame indices produced by ``t*1000`` in practice.
    return f"floor(({x})*1000+0.5)"


# --------------------------------------------------------------------------- #
# Camera kernels -> FFmpeg expression strings (mirror ``kernels.py``).
# --------------------------------------------------------------------------- #
def push_in_zoom_expr(tn: str, *, intensity: float = 0.3) -> str:
    """Mirror ``kernels.push_in`` → the ``zoom`` factor expression."""
    return f"(1+{float(intensity):.9g}*{ease_in_out_expr(tn)})"


class KenBurnsExpr(NamedTuple):
    zoom: str
    x: str
    y: str


def ken_burns_expr(
    tn: str, *, zoom: float = 0.2, pan_x: float = 0.1, pan_y: float = 0.05
) -> KenBurnsExpr:
    """Mirror ``kernels.ken_burns`` → (zoom, x, y) expressions."""
    lin = linear_expr(tn)
    return KenBurnsExpr(
        zoom=f"(1+{float(zoom):.9g}*{lin})",
        x=f"({float(pan_x):.9g}*{lin})",
        y=f"({float(pan_y):.9g}*{lin})",
    )


class HandheldExpr(NamedTuple):
    dx: str
    dy: str
    rot: str


def handheld_expr(tn: str, *, intensity: float = 0.02, seed: int = 1) -> HandheldExpr:
    """Mirror ``kernels.handheld`` → (dx, dy, rot) expressions."""
    n = _round_expr(clamp01_expr(tn))
    i = float(intensity)
    return HandheldExpr(
        dx=f"({i:.9g}*{noise1_expr(n, seed)})",
        dy=f"({i:.9g}*{noise1_expr(n, seed + 7)})",
        rot=f"({i * 0.5:.9g}*{noise1_expr(n, seed + 13)})",
    )


# --------------------------------------------------------------------------- #
# Faithful numeric evaluator for the whitelisted FFmpeg expression subset.
#
# Used by the parity tests to prove an expression built here evaluates to the
# exact ``kernels.py`` value at a given time — i.e. the render path and the
# preview path agree frame-for-frame — without invoking a real FFmpeg process.
# It models FFmpeg's documented semantics for each supported function.
# --------------------------------------------------------------------------- #
def _ff_if(cond: float, a: float, b: float = 0.0) -> float:
    return a if cond != 0 else b


# ``if`` is a Python keyword, so ``ast.parse`` rejects ``if(...)``. The evaluator
# rewrites the FFmpeg function name ``if(`` to this internal name before parsing;
# the emitted strings themselves stay valid FFmpeg (``if(...)``).
_FF_IF = "__ffif__"

_FUNCS = {
    "clip": lambda x, lo, hi: min(max(x, lo), hi),
    _FF_IF: _ff_if,
    "lt": lambda a, b: 1.0 if a < b else 0.0,
    "lte": lambda a, b: 1.0 if a <= b else 0.0,
    "gt": lambda a, b: 1.0 if a > b else 0.0,
    "gte": lambda a, b: 1.0 if a >= b else 0.0,
    "eq": lambda a, b: 1.0 if a == b else 0.0,
    "floor": lambda x: float(math.floor(x)),
    "min": lambda a, b: min(a, b),
    "max": lambda a, b: max(a, b),
    "abs": abs,
}


def evaluate(expr: str, variables: dict[str, float] | None = None) -> float:
    """Evaluate an FFmpeg expression string built by this module.

    Supports only the whitelisted operators/functions (see module docstring) and
    the caller-supplied ``variables`` (e.g. ``{"t": 0.5}``). Raises ``ValueError``
    on anything outside that subset so it can never run arbitrary code.
    """
    vars_ = variables or {}
    tree = ast.parse(re.sub(r"\bif\(", f"{_FF_IF}(", expr), mode="eval")

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError(f"unsupported constant: {node.value!r}")
        if isinstance(node, ast.Name):
            if node.id in vars_:
                return float(vars_[node.id])
            raise ValueError(f"unknown variable: {node.id!r}")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = _eval(node.operand)
            return v if isinstance(node.op, ast.UAdd) else -v
        if isinstance(node, ast.BinOp):
            left, right = _eval(node.left), _eval(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            raise ValueError(f"unsupported operator: {type(node.op).__name__}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = _FUNCS.get(node.func.id)
            if fn is None:
                raise ValueError(f"unsupported function: {node.func.id!r}")
            return float(fn(*[_eval(a) for a in node.args]))
        raise ValueError(f"unsupported syntax: {type(node).__name__}")

    return _eval(tree)
