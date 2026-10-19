#!/usr/bin/env python3
"""Generate dependency-free TypeScript component types from ReelForge OpenAPI."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
INPUT_PATH = PACKAGE_ROOT / "openapi" / "reelforge-v1.json"
OUTPUT_PATH = PACKAGE_ROOT / "src" / "generated" / "reelforge-v1.ts"

_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def _identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_$]", "_", value)
    return f"_{cleaned}" if cleaned[:1].isdigit() else cleaned


def _property(value: str) -> str:
    return value if _IDENTIFIER.fullmatch(value) else json.dumps(value)


def _literal(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value, ensure_ascii=False)


def _type(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "unknown"
    if "$ref" in schema:
        return _identifier(str(schema["$ref"]).rsplit("/", 1)[-1])
    if "const" in schema:
        return _literal(schema["const"])
    if schema.get("enum"):
        return " | ".join(_literal(value) for value in schema["enum"])
    for key in ("oneOf", "anyOf"):
        if key in schema:
            parts = list(dict.fromkeys(_type(item) for item in schema[key]))
            return " | ".join(parts) if parts else "unknown"
    if "allOf" in schema:
        parts = list(dict.fromkeys(_type(item) for item in schema["allOf"]))
        return " & ".join(parts) if parts else "unknown"

    kind = schema.get("type")
    if isinstance(kind, list):
        return " | ".join(_type({**schema, "type": item}) for item in kind)
    if kind == "string":
        return "string"
    if kind in {"integer", "number"}:
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "null":
        return "null"
    if kind == "array":
        item_type = _type(schema.get("items", {}))
        return f"Array<{item_type}>"
    if kind == "object" or "properties" in schema or "additionalProperties" in schema:
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        members = [
            f"{_property(name)}{'?' if name not in required else ''}: {_type(value)};"
            for name, value in sorted(properties.items())
        ]
        additional = schema.get("additionalProperties")
        if additional is True:
            members.append("[key: string]: unknown;")
        elif isinstance(additional, dict):
            members.append(f"[key: string]: {_type(additional)};")
        return "{ " + " ".join(members) + " }" if members else "Record<string, unknown>"
    return "unknown"


def _render(schema: dict[str, Any]) -> str:
    components = schema.get("components", {}).get("schemas", {})
    lines = [
        "// Generated from openapi/reelforge-v1.json. Do not edit by hand.",
        "// Run `npm --workspace @reelforge/api-contract run contract:export`.",
        "",
    ]
    for raw_name, component in sorted(components.items()):
        name = _identifier(raw_name)
        description = str(component.get("description") or "").strip()
        if description:
            safe_description = description.replace("*/", "* /")
            comment_lines = [
                f" * {line}" if line else " *"
                for line in safe_description.splitlines()
            ]
            lines.extend(["/**", *comment_lines, " */"])

        if component.get("type") == "object" or "properties" in component:
            required = set(component.get("required") or [])
            lines.append(f"export interface {name} {{")
            for prop_name, prop_schema in sorted((component.get("properties") or {}).items()):
                optional = "" if prop_name in required else "?"
                lines.append(
                    f"  {_property(prop_name)}{optional}: {_type(prop_schema)};"
                )
            additional = component.get("additionalProperties")
            if additional is True:
                lines.append("  [key: string]: unknown;")
            elif isinstance(additional, dict):
                lines.append(f"  [key: string]: {_type(additional)};")
            lines.append("}")
        else:
            lines.append(f"export type {name} = {_type(component)};")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    schema = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    rendered = _render(schema)
    if args.check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != rendered:
            raise SystemExit(
                "Generated TypeScript contract is stale; run contract:export"
            )
        print(f"Generated types are current: {OUTPUT_PATH.relative_to(REPOSITORY_ROOT)}")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.relative_to(REPOSITORY_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
