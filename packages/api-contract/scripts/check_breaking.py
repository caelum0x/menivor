#!/usr/bin/env python3
"""Detect breaking changes between reviewed and current ReelForge OpenAPI."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "openapi" / "reelforge-v1.baseline.json"
DEFAULT_CURRENT = ROOT / "openapi" / "reelforge-v1.json"
HTTP_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
)


class ContractDiff:
    """Conservative, dependency-free compatibility comparison for OpenAPI 3.1."""

    def __init__(self, old: dict[str, Any], new: dict[str, Any]) -> None:
        self.old = old
        self.new = new
        self.issues: list[str] = []
        self._visited: set[tuple[int, int, str, str]] = set()

    @staticmethod
    def _pointer(document: dict[str, Any], reference: str) -> Any:
        if not reference.startswith("#/"):
            raise ValueError(f"external OpenAPI reference is unsupported: {reference}")
        value: Any = document
        for token in reference[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            value = value[token]
        return value

    def _resolve(self, document: dict[str, Any], value: Any) -> Any:
        seen: set[str] = set()
        while isinstance(value, dict) and "$ref" in value:
            reference = str(value["$ref"])
            if reference in seen:
                break
            seen.add(reference)
            target = self._pointer(document, reference)
            siblings = {key: item for key, item in value.items() if key != "$ref"}
            value = {**target, **siblings} if isinstance(target, dict) else target
        return value

    @staticmethod
    def _types(schema: dict[str, Any]) -> set[str]:
        raw = schema.get("type")
        if isinstance(raw, str):
            return {raw}
        if isinstance(raw, list):
            return {str(item) for item in raw}
        result: set[str] = set()
        for keyword in ("anyOf", "oneOf"):
            for branch in schema.get(keyword, []):
                if isinstance(branch, dict):
                    result.update(ContractDiff._types(branch))
        return result

    def _issue(self, location: str, message: str) -> None:
        self.issues.append(f"{location}: {message}")

    def compare_schema(
        self,
        old_value: Any,
        new_value: Any,
        *,
        location: str,
        direction: str,
    ) -> None:
        old = self._resolve(self.old, old_value)
        new = self._resolve(self.new, new_value)
        if not isinstance(old, dict) or not isinstance(new, dict):
            if old != new:
                self._issue(location, "schema changed incompatibly")
            return

        visit = (id(old), id(new), location, direction)
        if visit in self._visited:
            return
        self._visited.add(visit)

        old_types = self._types(old)
        new_types = self._types(new)
        if old_types and new_types and not old_types.issubset(new_types):
            self._issue(
                location,
                f"allowed type narrowed from {sorted(old_types)} to {sorted(new_types)}",
            )

        old_enum = old.get("enum")
        new_enum = new.get("enum")
        if isinstance(old_enum, list) and isinstance(new_enum, list):
            removed = [item for item in old_enum if item not in new_enum]
            if removed:
                self._issue(location, f"enum values removed: {removed!r}")

        self._compare_constraints(old, new, location)

        old_properties = old.get("properties", {})
        new_properties = new.get("properties", {})
        if isinstance(old_properties, dict) and isinstance(new_properties, dict):
            for name, old_property in old_properties.items():
                if name not in new_properties:
                    label = "response field" if direction == "response" else "request field"
                    self._issue(f"{location}.{name}", f"{label} removed")
                    continue
                self.compare_schema(
                    old_property,
                    new_properties[name],
                    location=f"{location}.{name}",
                    direction=direction,
                )

            old_required = set(old.get("required", []))
            new_required = set(new.get("required", []))
            if direction == "request":
                for name in sorted(new_required - old_required):
                    self._issue(f"{location}.{name}", "new required request field")
            else:
                for name in sorted(old_required - new_required):
                    self._issue(
                        f"{location}.{name}", "response field is no longer guaranteed"
                    )

        if "items" in old:
            if "items" not in new:
                self._issue(location, "array item schema removed")
            else:
                self.compare_schema(
                    old["items"],
                    new["items"],
                    location=f"{location}[]",
                    direction=direction,
                )

    def _compare_constraints(
        self, old: dict[str, Any], new: dict[str, Any], location: str
    ) -> None:
        for name in ("minimum", "exclusiveMinimum", "minLength", "minItems"):
            if name in old and name in new and new[name] > old[name]:
                self._issue(location, f"{name} tightened from {old[name]} to {new[name]}")
        for name in ("maximum", "exclusiveMaximum", "maxLength", "maxItems"):
            if name in old and name in new and new[name] < old[name]:
                self._issue(location, f"{name} tightened from {old[name]} to {new[name]}")
        if old.get("additionalProperties", True) is not False and new.get(
            "additionalProperties", True
        ) is False:
            self._issue(location, "additional properties are no longer accepted")

    def compare_security(self) -> None:
        if self.old.get("security") != self.new.get("security"):
            self._issue("security", "global authentication requirements changed")
        old_schemes = self.old.get("components", {}).get("securitySchemes", {})
        new_schemes = self.new.get("components", {}).get("securitySchemes", {})
        for name, scheme in old_schemes.items():
            if name not in new_schemes:
                self._issue(f"securitySchemes.{name}", "authentication scheme removed")
            elif scheme != new_schemes[name]:
                self._issue(f"securitySchemes.{name}", "authentication scheme changed")

    def compare_operation(
        self, path: str, method: str, old_op: dict[str, Any], new_op: dict[str, Any]
    ) -> None:
        location = f"{method.upper()} {path}"
        if old_op.get("security", self.old.get("security")) != new_op.get(
            "security", self.new.get("security")
        ):
            self._issue(location, "authentication requirements changed")
        self._compare_parameters(old_op, new_op, location)
        self._compare_request_body(old_op, new_op, location)
        self._compare_responses(old_op, new_op, location)

    def _compare_parameters(
        self, old_op: dict[str, Any], new_op: dict[str, Any], location: str
    ) -> None:
        def parameters(
            document: dict[str, Any], operation: dict[str, Any]
        ) -> dict[tuple[str, str], dict[str, Any]]:
            result: dict[tuple[str, str], dict[str, Any]] = {}
            for raw in operation.get("parameters", []):
                parameter = self._resolve(document, raw)
                if isinstance(parameter, dict):
                    key = (str(parameter.get("in")), str(parameter.get("name")))
                    result[key] = parameter
            return result

        old_params = parameters(self.old, old_op)
        new_params = parameters(self.new, new_op)
        for key, old_parameter in old_params.items():
            parameter_location = f"{location} parameter {key[0]}:{key[1]}"
            if key not in new_params:
                self._issue(parameter_location, "parameter removed")
                continue
            new_parameter = new_params[key]
            if not old_parameter.get("required", False) and new_parameter.get(
                "required", False
            ):
                self._issue(parameter_location, "parameter became required")
            self.compare_schema(
                old_parameter.get("schema", {}),
                new_parameter.get("schema", {}),
                location=parameter_location,
                direction="request",
            )
        for key, new_parameter in new_params.items():
            if key not in old_params and new_parameter.get("required", False):
                self._issue(
                    f"{location} parameter {key[0]}:{key[1]}",
                    "new required parameter",
                )

    def _compare_request_body(
        self, old_op: dict[str, Any], new_op: dict[str, Any], location: str
    ) -> None:
        old_body = self._resolve(self.old, old_op.get("requestBody", {}))
        new_body = self._resolve(self.new, new_op.get("requestBody", {}))
        if not isinstance(old_body, dict) or not old_body:
            if isinstance(new_body, dict) and new_body.get("required", False):
                self._issue(location, "new required request body")
            return
        if not isinstance(new_body, dict) or not new_body:
            self._issue(location, "request body removed")
            return
        if not old_body.get("required", False) and new_body.get("required", False):
            self._issue(location, "request body became required")
        old_content = old_body.get("content", {})
        new_content = new_body.get("content", {})
        for media_type, old_media in old_content.items():
            if media_type not in new_content:
                self._issue(location, f"request media type removed: {media_type}")
                continue
            self.compare_schema(
                old_media.get("schema", {}),
                new_content[media_type].get("schema", {}),
                location=f"{location} request {media_type}",
                direction="request",
            )

    def _compare_responses(
        self, old_op: dict[str, Any], new_op: dict[str, Any], location: str
    ) -> None:
        old_responses = old_op.get("responses", {})
        new_responses = new_op.get("responses", {})
        for status, old_response_value in old_responses.items():
            response_location = f"{location} response {status}"
            if status not in new_responses:
                self._issue(response_location, "response status removed")
                continue
            old_response = self._resolve(self.old, old_response_value)
            new_response = self._resolve(self.new, new_responses[status])
            if not isinstance(old_response, dict) or not isinstance(new_response, dict):
                continue
            old_content = old_response.get("content", {})
            new_content = new_response.get("content", {})
            for media_type, old_media in old_content.items():
                if media_type not in new_content:
                    self._issue(
                        response_location, f"response media type removed: {media_type}"
                    )
                    continue
                self.compare_schema(
                    old_media.get("schema", {}),
                    new_content[media_type].get("schema", {}),
                    location=f"{response_location} {media_type}",
                    direction="response",
                )

    def run(self) -> list[str]:
        self.compare_security()
        old_paths = self.old.get("paths", {})
        new_paths = self.new.get("paths", {})
        for path, old_item in old_paths.items():
            if path not in new_paths:
                self._issue(path, "path removed")
                continue
            new_item = new_paths[path]
            for method, old_operation in old_item.items():
                if method.lower() not in HTTP_METHODS:
                    continue
                if method not in new_item:
                    self._issue(f"{method.upper()} {path}", "method removed")
                    continue
                self.compare_operation(path, method, old_operation, new_item[method])
        return sorted(set(self.issues))


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SystemExit(f"OpenAPI file not found: {path}") from error
    if not isinstance(value, dict) or "paths" not in value:
        raise SystemExit(f"Invalid OpenAPI document: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument(
        "--accept",
        action="store_true",
        help="replace the reviewed baseline with the current schema",
    )
    args = parser.parse_args()

    if args.accept:
        load(args.current)
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.current, args.baseline)
        print(f"Accepted OpenAPI baseline: {args.baseline}")
        return 0

    diff = ContractDiff(load(args.baseline), load(args.current)).run()
    if diff:
        print("Breaking OpenAPI changes detected:", file=sys.stderr)
        for issue in diff:
            print(f"  - {issue}", file=sys.stderr)
        print(
            "Restore compatibility or complete the approved deprecation process. "
            "Only then run `npm run contract:baseline`.",
            file=sys.stderr,
        )
        return 1
    print("No breaking OpenAPI changes detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
