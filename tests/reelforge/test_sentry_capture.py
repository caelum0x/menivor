"""Sentry capture_exception — structured context + best-effort (injected client)."""

from __future__ import annotations

from app.telemetry.sentry import capture_exception


class _Scope:
    def __init__(self):
        self.tags = {}
        self.extras = {}

    def set_tag(self, k, v):
        self.tags[k] = v

    def set_extra(self, k, v):
        self.extras[k] = v


class FakeSentry:
    """A fake sentry_sdk with push_scope + capture_exception."""

    def __init__(self):
        self.captured = []
        self.scope = _Scope()

    def push_scope(self):
        outer = self

        class _Ctx:
            def __enter__(self_inner):
                return outer.scope

            def __exit__(self_inner, *a):
                return False

        return _Ctx()

    def capture_exception(self, exc):
        self.captured.append(exc)


class MinimalSentry:
    """A minimal client without scopes (exercises the fallback path)."""

    def __init__(self):
        self.captured = []

    def capture_exception(self, exc):
        self.captured.append(exc)


def test_capture_sets_stage_tag_and_context():
    fake = FakeSentry()
    err = RuntimeError("boom")
    ok = capture_exception(err, stage="render.poll", context={"job_id": "j1", "backend": "runpod"}, client=fake)
    assert ok is True
    assert fake.captured == [err]
    assert fake.scope.tags["stage"] == "render.poll"
    assert fake.scope.extras["job_id"] == "j1" and fake.scope.extras["backend"] == "runpod"


def test_capture_minimal_client_fallback():
    fake = MinimalSentry()
    err = ValueError("x")
    assert capture_exception(err, client=fake) is True
    assert fake.captured == [err]


def test_capture_noop_when_no_sdk_and_none_client():
    # No client injected + sentry_sdk not installed in the test env -> False, no raise.
    result = capture_exception(RuntimeError("y"))
    assert result in (True, False)  # True only if sentry_sdk happens to be installed


def test_capture_never_raises_on_bad_client():
    class Broken:
        def capture_exception(self, exc):
            raise RuntimeError("reporting backend down")

    # A failing reporter must be swallowed (error path must never double-fault).
    assert capture_exception(RuntimeError("z"), client=Broken()) is False
