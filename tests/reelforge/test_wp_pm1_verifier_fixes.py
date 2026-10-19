"""Wave P P1 verifier fixes for the Menivor lane (PM1.4 money paths).

* A second "Train" tap while a hub training is still running is refused, so
  the AI-video credits are debited once, not twice.
* The failed-training refund sweep reaches every failed paid hub training,
  however many old failed trainings (already refunded, or legacy) exist.
"""

from __future__ import annotations

from app.domains.characters import hub
from app.models.db.models import Job
from app.services.billing import premium_credits as pc

from tests.reelforge.test_wp_pm1_4_characters_hub import H, _client, _funded, _real_face, _uid, maker  # noqa: F401


def _quote(client, cid) -> int:
    return client.post(f"/api/v1/my/characters/{cid}/train/quote", headers=H).json()["data"]["credits"]


def test_second_train_tap_while_running_is_refused_and_charged_once(maker, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CHARACTER_LORA_PROVIDER_USD", "1.00")
    client = _client()
    cid = _real_face(client, monkeypatch).json()["data"]["id"]
    credits = _quote(client, cid)
    _funded(maker, credits * 2)
    first = client.post(f"/api/v1/my/characters/{cid}/train", json={"quoted_credits": credits}, headers=H)
    assert first.status_code == 200, first.text
    second = client.post(f"/api/v1/my/characters/{cid}/train", json={"quoted_credits": credits}, headers=H)
    assert second.status_code == 409
    assert second.json()["data"]["code"] == "training_in_progress"
    with maker() as s:
        assert pc.balance(s, _uid(maker), pc.KIND_AI_VIDEO) == credits
        assert s.query(Job).filter_by(kind="character_lora").count() == 1
    # Once the first run has failed, a new training can start.
    with maker() as s:
        s.get(Job, first.json()["data"]["job_id"]).state = -1
        s.commit()
    third = client.post(f"/api/v1/my/characters/{cid}/train", json={"quoted_credits": credits}, headers=H)
    assert third.status_code == 200, third.text


def test_refund_sweep_is_not_starved_by_old_failed_trainings(maker, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CHARACTER_LORA_PROVIDER_USD", "1.00")
    client = _client()
    uid = _uid(maker)
    with maker() as s:
        for n in range(30):
            s.add(Job(user_id=uid, kind="character_lora", state=-1,
                      params={"credits_cost": 0, "refunded": True, "legacy": n}))
            s.add(Job(user_id=uid, kind="character_lora", state=-1,
                      params={"hub_funding": "ai_video", "hub_refunded": True}))
        s.commit()
    cid = _real_face(client, monkeypatch).json()["data"]["id"]
    credits = _quote(client, cid)
    _funded(maker, credits)
    job_id = client.post(f"/api/v1/my/characters/{cid}/train", json={"quoted_credits": credits},
                         headers=H).json()["data"]["job_id"]
    with maker() as s:
        s.get(Job, job_id).state = -1
        s.commit()
    with maker() as s:
        assert hub.refund_failed_trainings(s, limit=10) == 1
        s.commit()
    with maker() as s:
        assert hub.refund_failed_trainings(s, limit=10) == 0
        s.commit()
    with maker() as s:
        assert pc.balance(s, uid, pc.KIND_AI_VIDEO) == credits
        assert s.get(Job, job_id).params["hub_refunded"] is True
