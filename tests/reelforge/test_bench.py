"""The benchmark harness has deterministic percentile and input validation."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _bench_module():
    path = Path(__file__).parents[2] / "scripts" / "reelforge_bench.py"
    spec = importlib.util.spec_from_file_location("reelforge_bench", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_percentile_and_cli_output_for_ten_golden_jobs(tmp_path, capsys):
    bench = _bench_module()
    artifact = tmp_path / "results.json"
    artifact.write_text(
        '[{"duration_s": 1}, {"duration_s": 2}, {"duration_s": 3}, '
        '{"duration_s": 4}, {"duration_s": 5}, {"duration_s": 6}, '
        '{"duration_s": 7}, {"duration_s": 8}, {"duration_s": 9}, '
        '{"duration_s": 10}]',
        encoding="utf-8",
    )

    assert bench.main([str(artifact)]) == 0
    assert capsys.readouterr().out.strip() == (
        "samples=10 p50_s=5.500 p95_s=9.550 max_s=10.000"
    )


def test_cli_rejects_incomplete_golden_run(tmp_path, capsys):
    bench = _bench_module()
    artifact = tmp_path / "partial.json"
    artifact.write_text('[{"duration_s": 1}]', encoding="utf-8")

    assert bench.main([str(artifact)]) == 2
    assert "expected 10 samples, got 1" in capsys.readouterr().err
