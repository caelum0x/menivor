"""Write pip constraints from the pins in upstream's pyproject.toml (build-time helper).

Usage: python make_constraints.py /app/pyproject.toml > /tmp/constraints.txt
Later entries win, so ``[tool.uv] override-dependencies`` beat the main list.
torch/torchaudio are installed separately from the CPU index and are skipped.
"""

import re
import sys

PIN = re.compile(r'"([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==([^";\s]+)"')
SKIP = {"torch", "torchaudio"}


def constraints(text: str) -> str:
    pins: dict[str, str] = {}
    for name, version in PIN.findall(text):
        pins[name.lower()] = version
    return "".join(f"{n}=={v}\n" for n, v in sorted(pins.items()) if n not in SKIP)


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as fh:
        sys.stdout.write(constraints(fh.read()))
