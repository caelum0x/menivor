"""Wave 4 CHARACTER identity lock — reference store + IP-Adapter/LoRA conditioning
injected into the render spec + the async LoRA-training route (fake transport).

Covers, per the build contract:
  * a reference image stored (owned-key checked) and reused across shots;
  * the identity conditioning appearing in the compiled render spec;
  * the LoRA route submitting/polling via an injected fake transport;
  * the identity_key rehash folding the reference digest behind a ``v2|`` prefix
    without orphaning image-less (v1) rows;
  * the credit-refund idempotency of the training delegate.
"""

from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.domains.characters.consistency import (
    CharacterProfile,
    build_identity_lock,
    reference_digest,
    shot_seed,
)
from app.models.db import base as db_base
from app.models.db.base import Base
from app.models.db.character_refs import CharacterReference  # noqa: F401 (registers table)
from app.models.db.models import Asset, CreditLedger, User


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def bound_db(monkeypatch):
    """Bind ``db_base.get_session`` to a fresh in-memory DB for delegate tests."""
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    monkeypatch.setattr(db_base, "SessionLocal", factory, raising=False)
    monkeypatch.setattr(db_base, "engine", engine, raising=False)
    return factory


def _profile(refs=("uploads/u1/sheet1.png",)) -> CharacterProfile:
    return CharacterProfile(
        character_id="c1",
        name="Nova",
        descriptors=("silver hair", "red jacket"),
        reference_images=tuple(refs),
        style="3D pixar",
        negative=("blurry", "extra limbs"),
    )


# --------------------------------------------------------------------------- #
# reference_digest + identity_key v2 rehash
# --------------------------------------------------------------------------- #
def test_reference_digest_is_sorted_and_stable():
    a = reference_digest(("uploads/b.png", "uploads/a.png"))
    b = reference_digest(("uploads/a.png", "uploads/b.png"))
    assert a == b and len(a) == 64  # order-independent sha256
    assert reference_digest(()) == ""  # image-less -> empty


def test_identity_key_v2_folds_references_but_v1_unchanged():
    with_refs = _profile()
    no_refs = CharacterProfile("c1", "Nova", descriptors=("silver hair", "red jacket"), style="3D pixar")
    # Image-less character keeps the raw v1 (unprefixed) 64-hex key.
    assert not no_refs.identity_key().startswith("v2|")
    assert len(no_refs.identity_key()) == 64
    # A character WITH references gets a distinct v2 key (the sheet participates).
    assert with_refs.identity_key().startswith("v2|")
    assert with_refs.identity_key() != no_refs.identity_key()


def test_base_seed_survives_v2_prefix():
    p = _profile()
    # base_seed must strip the "v2|" prefix before the hex slice (else ValueError).
    assert 0 <= p.base_seed() < 2**31
    assert p.base_seed() == _profile().base_seed()  # deterministic


def test_adding_a_reference_changes_identity_key():
    one = _profile(("uploads/u1/a.png",))
    two = _profile(("uploads/u1/a.png", "uploads/u1/b.png"))
    assert one.identity_key() != two.identity_key()


# --------------------------------------------------------------------------- #
# build_identity_lock — reused across shots
# --------------------------------------------------------------------------- #
def test_build_identity_lock_reused_across_shots():
    p = _profile()
    lock0 = build_identity_lock(p, shot_index=0)
    lock1 = build_identity_lock(p, shot_index=1)
    # Same reference sheet + identity on every shot...
    assert lock0.reference_images == p.reference_images == lock1.reference_images
    assert lock0.identity_key == lock1.identity_key
    assert lock0.negative_prompt == "blurry, extra limbs"
    # ...but a distinct, deterministic per-shot seed.
    assert lock0.seed == shot_seed(p, 0)
    assert lock0.seed != lock1.seed


# --------------------------------------------------------------------------- #
# references_service — owned-key store, reuse, digest
# --------------------------------------------------------------------------- #
def _make_user(session, uid="u1") -> User:
    user = User(id=uid, email=f"{uid}@x.io")
    session.add(user)
    session.flush()
    return user


def _own_asset(session, uid, key):
    session.add(Asset(user_id=uid, kind="upload", r2_key=key, content_type="image/png"))
    session.flush()


def test_bind_reference_requires_owned_uploads_key(session):
    from app.domains.characters import references_service as refs
    from app.domains.media.service import MediaDomainError

    _make_user(session, "u1")
    # A key the caller does NOT own is rejected at the ownership boundary.
    with pytest.raises(MediaDomainError):
        refs.bind_reference(session, user_id="u1", character_id="c1", r2_key="uploads/u2/x.png")
    # A non-uploads/ key is rejected before any ownership check.
    with pytest.raises(refs.ReferenceBindingError):
        refs.bind_reference(session, user_id="u1", character_id="c1", r2_key="jobs/u1/x.png")


def test_bind_and_list_and_digest(session):
    from app.domains.characters import references_service as refs

    _make_user(session, "u1")
    _own_asset(session, "u1", "uploads/u1/face.png")
    _own_asset(session, "u1", "uploads/u1/body.png")

    v1 = refs.bind_reference(session, user_id="u1", character_id="c1", r2_key="uploads/u1/face.png", role="face")
    refs.bind_reference(session, user_id="u1", character_id="c1", r2_key="uploads/u1/body.png", role="body")
    assert v1["role"] == "face" and v1["r2_key"] == "uploads/u1/face.png"

    listed = refs.list_references(session, "c1")
    assert {r["r2_key"] for r in listed} == {"uploads/u1/face.png", "uploads/u1/body.png"}
    # The store's digest matches the pure consistency digest of the same keys.
    assert refs.reference_digest(listed) == reference_digest(
        ("uploads/u1/body.png", "uploads/u1/face.png")
    )


def test_bind_reference_rejects_bad_role(session):
    from app.domains.characters import references_service as refs

    _make_user(session, "u1")
    _own_asset(session, "u1", "uploads/u1/face.png")
    with pytest.raises(refs.ReferenceBindingError):
        refs.bind_reference(session, user_id="u1", character_id="c1", r2_key="uploads/u1/face.png", role="hologram")


def test_binding_a_reference_syncs_character_identity_and_compiled_lock(session):
    """Wave-4 fix: a bound reference folds into the SAME character store the
    compiler + dedupe read (``Character.reference_images`` / ``identity_key``),
    not a disjoint table — so the bound sheet is visible to identity/dedupe/render.
    """
    from app.domains.characters import references_service as refs
    from app.domains.characters.repository import CharacterRepository, to_profile
    from app.domains.templates.compiler import compile_template
    from app.domains.templates.presets import get_template

    _make_user(session, "u1")
    _own_asset(session, "u1", "uploads/u1/face.png")
    repo = CharacterRepository(session)
    row = repo.create(
        user_id="u1",
        profile=CharacterProfile(character_id="", name="Nova", descriptors=("silver hair",), style="3D pixar"),
    )
    # Image-less at creation: raw v1 key, no reference column.
    noref_key = CharacterProfile(
        character_id=row.id, name="Nova", descriptors=("silver hair",), style="3D pixar"
    ).identity_key()
    assert list(row.reference_images or []) == []

    refs.bind_reference(session, user_id="u1", character_id=row.id, r2_key="uploads/u1/face.png", role="face")

    # The bound key is now the character's canonical reference sheet + rehashed key.
    assert row.reference_images == ["uploads/u1/face.png"]
    assert row.identity_key.startswith("v2|") and row.identity_key != noref_key
    # find_duplicate no longer collides with the (still image-less) v1 identity.
    dup_probe = CharacterProfile(
        character_id=row.id, name="Nova", descriptors=("silver hair",), style="3D pixar"
    )
    assert repo.find_duplicate("u1", dup_probe) is None
    # The compiled IdentityLock now carries the bound sheet (reaches the render).
    spec = compile_template(get_template("movie-recap"), {"title": "X"}, duration_s=45, character=to_profile(row))
    assert spec.segments[0].identity_lock.reference_images == ("uploads/u1/face.png",)


# --------------------------------------------------------------------------- #
# render_spec IdentityLock + compiler injection
# --------------------------------------------------------------------------- #
def test_identity_lock_dataclass_is_frozen_and_serializable():
    from app.domains.templates.render_spec import IdentityLock, SegmentSpec

    lock = IdentityLock(character_id="c1", identity_key="k", seed=7, reference_images=("uploads/a.png",))
    # Frozen (asdict recursion contract).
    with pytest.raises(Exception):
        lock.seed = 9  # type: ignore[misc]
    seg = SegmentSpec(role="body", order=0, t_start=0.0, t_end=1.0, track="full")
    assert seg.identity_lock is None  # additive default keeps old specs valid
    d = asdict(SegmentSpec(role="body", order=0, t_start=0.0, t_end=1.0, track="full", identity_lock=lock))
    assert d["identity_lock"]["seed"] == 7
    assert d["identity_lock"]["ip_adapter_weight"] == 0.8


def test_compiler_character_none_is_byte_identical():
    from app.domains.templates.compiler import compile_template
    from app.domains.templates.presets import get_template

    template = get_template("movie-recap")
    inputs = {"title": "Inception"}
    a = compile_template(template, inputs, duration_s=45)
    b = compile_template(template, inputs, duration_s=45, character=None)
    assert a.to_dict() == b.to_dict()
    assert all(seg.identity_lock is None for seg in a.segments)


def test_compiler_attaches_identity_lock_when_character_bound():
    from app.domains.templates.compiler import compile_template
    from app.domains.templates.presets import get_template

    template = get_template("movie-recap")
    profile = _profile()
    spec = compile_template(template, {"title": "Inception"}, duration_s=45, character=profile)
    assert spec.segments  # non-empty
    for seg in spec.segments:
        lock = seg.identity_lock
        assert lock is not None
        assert lock.character_id == "c1"
        assert lock.reference_images == profile.reference_images
        assert lock.seed == shot_seed(profile, seg.order)
    # Distinct per-shot seeds across at least two segments (variety without drift).
    seeds = {seg.identity_lock.seed for seg in spec.segments}
    assert len(seeds) == len(spec.segments)


# --------------------------------------------------------------------------- #
# lora_train provider adapter (fake transport, no network)
# --------------------------------------------------------------------------- #
class FakeTransport:
    def __init__(self, responses: dict) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method: str, path: str, *, json: dict | None = None) -> dict:
        self.calls.append((method, path, json))
        value = self.responses.get((method, path))
        if value is None:
            for (m, p), v in self.responses.items():
                if m == method and path.startswith(p):
                    value = v
                    break
        if isinstance(value, Exception):
            raise value
        return value or {}


PRICE_STEPS = SimpleNamespace(
    id="pv", unit_price_micros=10, min_charge_micros=0, flat_fee_micros=0,
    quote_rules={"default_units": 1000},
)


def test_lora_train_adapter_protocol_and_catalog():
    from app.domains.routing.base import ProviderAdapter
    from app.domains.routing.providers.lora_train import LoRATrainAdapter

    a = LoRATrainAdapter(api_key="k", request_fn=FakeTransport({}))
    assert isinstance(a, ProviderAdapter)
    assert a.provider_key == "lora_train"
    listing = a.catalog()[0]
    assert listing.capability == "lora_train" and listing.metering_unit == "steps"


def test_lora_train_submit_requires_min_references():
    from app.domains.routing.base import ProviderError
    from app.domains.routing.providers.lora_train import LoRATrainAdapter

    a = LoRATrainAdapter(api_key="k", min_references=1, request_fn=FakeTransport({}))
    with pytest.raises(ProviderError):
        a.submit({"reference_urls": []}, {}, "corr")


def test_lora_train_submit_then_poll_via_fake_transport():
    from app.domains.routing.base import RUN_COMPLETED, RUN_QUEUED
    from app.domains.routing.providers.lora_train import LoRATrainAdapter

    t = FakeTransport(
        {
            ("POST", "/run"): {"run_id": "train1", "state": "queued"},
            ("GET", "/status/train1"): {
                "state": "succeeded",
                "steps": 1000,
                "weights_url": "https://cdn/lora.safetensors",
            },
        }
    )
    a = LoRATrainAdapter(api_key="k", request_fn=t)
    q = a.quote({"steps": 1000}, PRICE_STEPS)
    assert q.max_cost_micros == 10 * 1000
    run = a.submit(
        {"reference_urls": ["https://sig/a.png", "https://sig/b.png"], "steps": 1000, "rank": 16},
        {},
        "corr",
    )
    assert run.state == RUN_QUEUED and run.run_id == "train1"
    polled = a.poll(run)
    assert polled.state == RUN_COMPLETED
    assert polled.result_ref == "https://cdn/lora.safetensors"
    assert polled.usage.unit == "steps" and polled.usage.quantity_units == 1000


# --------------------------------------------------------------------------- #
# registry — lora_train credential gate + build_adapter
# --------------------------------------------------------------------------- #
def test_registry_registers_lora_train_when_gated():
    from app.domains.routing.base import ProviderRegistry
    from app.domains.routing.providers.registry import register_available_adapters

    reg = ProviderRegistry()
    keys = register_available_adapters(reg, env={"REPLICATE_API_TOKEN": "r"})
    assert "lora_train" in keys and reg.has("lora_train")

    reg2 = ProviderRegistry()
    keys2 = register_available_adapters(reg2, env={"COMFY_DEPLOY_TOKEN": "c"})
    assert "lora_train" in keys2

    reg3 = ProviderRegistry()
    assert "lora_train" not in register_available_adapters(reg3, env={})


def test_build_adapter_returns_lora_train():
    from app.domains.routing.providers.lora_train import LoRATrainAdapter
    from app.domains.routing.providers.registry import build_adapter

    assert isinstance(build_adapter("lora_train", "k"), LoRATrainAdapter)


# --------------------------------------------------------------------------- #
# wan_camera + wan_replicate — identity conditioning reaches the provider request
# --------------------------------------------------------------------------- #
def test_wan_camera_build_inputs_copies_identity_lock():
    from app.domains.routing.providers.wan_camera import _build_inputs

    req = {
        "prompt": "nova walks",
        "num_frames": 48,
        "identity_lock": {
            "ip_reference_url": "https://sig/face.png",
            "ip_weight": 0.8,
            "lora_url": "https://sig/lora.safetensors",
            "lora_weight": 0.9,
            "ignored": {"not": "scalar"},
        },
    }
    inputs = _build_inputs(req)
    assert inputs["ip_reference_url"] == "https://sig/face.png"
    assert inputs["ip_weight"] == 0.8
    assert inputs["lora_url"] == "https://sig/lora.safetensors"
    assert inputs["lora_weight"] == 0.9
    assert "ignored" not in inputs  # non-scalar silently dropped


def test_wan_camera_build_inputs_without_identity_lock_is_silent():
    from app.domains.routing.providers.wan_camera import _build_inputs

    inputs = _build_inputs({"prompt": "x", "num_frames": 16})
    assert "ip_reference_url" not in inputs and "lora_url" not in inputs


def test_bound_reference_presigned_url_reaches_provider_across_shots():
    """End-to-end identity loop: compile a bound character reel, then bridge each
    shot's IdentityLock into the wan_camera provider request. The SAME presigned
    reference (+ LoRA) reaches the provider inputs on EVERY shot, while the seed
    varies per shot — the reference, not just the RNG, drives the pixels.
    """
    from app.domains.characters.render_bridge import build_shot_request
    from app.domains.routing.providers.wan_camera import _build_inputs
    from app.domains.templates.compiler import compile_template
    from app.domains.templates.presets import get_template

    profile = CharacterProfile(
        character_id="c1",
        name="Nova",
        descriptors=("silver hair",),
        reference_images=("uploads/u1/face.png",),
        style="3D pixar",
        lora_ref="loras/u1/nova.safetensors",
        negative=("blurry",),
    )
    spec = compile_template(get_template("movie-recap"), {"title": "X"}, duration_s=45, character=profile)
    assert len(spec.segments) > 1  # need >1 shot to prove reuse across shots

    def fake_presign(key: str) -> str:
        return f"https://sig/{key}?token=abc"

    seen_ref_urls: set[str] = set()
    seen_lora_urls: set[str] = set()
    seeds: set[int] = set()
    for seg in spec.segments:
        req = build_shot_request(seg.identity_lock, presign=fake_presign, prompt="nova walks", num_frames=48)
        seeds.add(req["seed"])
        inputs = _build_inputs(req)
        assert inputs["ip_reference_url"] == "https://sig/uploads/u1/face.png?token=abc"
        assert inputs["lora_url"] == "https://sig/loras/u1/nova.safetensors?token=abc"
        seen_ref_urls.add(inputs["ip_reference_url"])
        seen_lora_urls.add(inputs["lora_url"])

    # Identity conditioning is IDENTICAL across every shot (the consistency moat)...
    assert seen_ref_urls == {"https://sig/uploads/u1/face.png?token=abc"}
    assert seen_lora_urls == {"https://sig/loras/u1/nova.safetensors?token=abc"}
    # ...but the per-shot seed varies (variety without identity drift).
    assert len(seeds) == len(spec.segments)


def test_instantiate_draft_carries_identity_sidecar_for_bound_character():
    """The instantiate bridge no longer DISCARDS the compiled identity lock: a
    bound reel draft carries the per-shot locks into Job params (character-less
    drafts stay byte-identical)."""
    from app.domains.templates import service as tmpl_service

    profile = CharacterProfile(
        character_id="c1", name="Nova", descriptors=("silver hair",),
        reference_images=("uploads/u1/face.png",), style="3D pixar",
    )
    bound = tmpl_service.instantiate_draft("movie-recap", {"title": "X"}, duration_s=45, character=profile)
    sidecar = bound["reel_draft"].get("character")
    assert sidecar is not None
    assert sidecar["character_id"] == "c1"
    assert sidecar["shots"] and all(
        list(s["reference_images"]) == ["uploads/u1/face.png"] for s in sidecar["shots"]
    )
    # No character -> no sidecar (classic draft unchanged).
    plain = tmpl_service.instantiate_draft("movie-recap", {"title": "X"}, duration_s=45)
    assert "character" not in plain["reel_draft"]


def test_wan_replicate_build_input_maps_image_and_lora():
    from app.domains.routing.providers.wan_replicate import _build_input

    inp = _build_input(
        prompt="nova",
        seconds=5,
        image_url="https://sig/face.png",
        lora_url="https://sig/lora.safetensors",
        lora_scale=0.9,
    )
    assert inp["image"] == "https://sig/face.png"  # primary reference -> init frame
    assert inp["lora_weights"] == "https://sig/lora.safetensors"
    assert inp["lora_scale"] == 0.9


# --------------------------------------------------------------------------- #
# training_service — driver + refund idempotency
# --------------------------------------------------------------------------- #
class FakeAdapter:
    """A tiny submit->poll adapter that terminates completed after N polls."""

    provider_key = "lora_train"

    def __init__(self, polls_to_done=1, result_ref="https://cdn/lora.safetensors"):
        self._polls_to_done = polls_to_done
        self._result_ref = result_ref
        self.submitted = None

    def submit(self, request, snapshot, correlation_id):
        from app.domains.routing.base import RUN_QUEUED, ProviderRun

        self.submitted = request
        return ProviderRun(provider_key="lora_train", run_id="r1", state=RUN_QUEUED, raw={"n": 0})

    def poll(self, run):
        from app.domains.routing.base import RUN_COMPLETED, RUN_RUNNING, ProviderRun

        n = int(run.raw.get("n", 0)) + 1
        done = n >= self._polls_to_done
        return ProviderRun(
            provider_key="lora_train",
            run_id=run.run_id,
            state=RUN_COMPLETED if done else RUN_RUNNING,
            result_ref=self._result_ref if done else "",
            raw={"n": n},
        )


def test_drive_training_reaches_terminal_completed():
    from app.domains.characters.training_service import drive_training

    adapter = FakeAdapter(polls_to_done=2)
    run = drive_training(
        adapter,
        {"reference_urls": ["https://sig/a.png"]},
        {},
        "corr",
        sleep_fn=lambda *_: None,
    )
    assert run.state == "completed"
    assert run.result_ref == "https://cdn/lora.safetensors"
    assert adapter.submitted["reference_urls"] == ["https://sig/a.png"]


def test_drive_training_raises_when_no_weights():
    from app.domains.characters.training_service import drive_training

    adapter = FakeAdapter(polls_to_done=1, result_ref="")
    with pytest.raises(RuntimeError):
        drive_training(adapter, {}, {}, "corr", sleep_fn=lambda *_: None)


def test_refund_character_lora_training_is_idempotent(bound_db):
    from app.domains.characters.training_service import refund_character_lora_training
    from app.models.db.repositories import CreditRepository, JobRepository

    factory = bound_db
    with factory() as s:
        s.add(User(id="u1", email="u1@x.io"))
        s.flush()
        CreditRepository(s).grant("u1", 100, "seed")
        job = JobRepository(s).create(
            user_id="u1", kind="character_lora",
            params={"character_id": "c1", "credits_cost": 40},
        )
        CreditRepository(s).debit("u1", 40, job.id, "character_lora_debit")
        job_id = job.id
        s.commit()

    # First refund restores the 40 credits and stamps refunded=True.
    refund_character_lora_training(job_id)
    with factory() as s:
        job = JobRepository(s).get(job_id)
        assert job.params.get("refunded") is True
        ledger = s.query(CreditLedger).filter(CreditLedger.user_id == "u1").all()
        assert sum(e.delta for e in ledger) == 100  # 100 - 40 + 40

    # Second refund is a no-op (never double-refunds).
    refund_character_lora_training(job_id)
    with factory() as s:
        ledger = s.query(CreditLedger).filter(CreditLedger.user_id == "u1").all()
        assert sum(e.delta for e in ledger) == 100
