"""The node side of the transcode lanes (MV2): heartbeat, claim, upload URLs, finish.

A Mac (or burst) node authenticates with its bearer token and pulls work. A
claim is refused unless the node's heartbeat is fresh and (for the Mac) more
than 10 GB is free; burst nodes only get paid-plan jobs. The claim hands the
node a presigned source URL, the output prefix and, for a protected title, the
tier-1 key over the authenticated channel. Uploads go straight to R2 through
presigned PUT URLs for the files the node lists (inside its job prefix only).
"""

from __future__ import annotations

import posixpath
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.ott.models import OttTitle

from . import nodes, service
from .models import CLAIMED, DONE, LANE_BURST, LANE_MAC, QUEUED, OttEncodeJob, OttNode
from .pipeline import content_type

SOURCE_URL_TTL_S = 6 * 3600
PUT_URL_TTL_S = 6 * 3600
MAX_FILES = 20000


def claim(session: Session, node: OttNode, storage: Any, *, api_base: str) -> dict[str, Any] | None:
    if not nodes.is_live(node):
        raise service.TranscodeError(409, "node_not_ready", "send a heartbeat with enough free space first")
    query = select(OttEncodeJob).where(OttEncodeJob.lane == node.kind, OttEncodeJob.status == QUEUED)
    if node.kind == LANE_BURST:
        query = query.where(OttEncodeJob.paid_plan.is_(True))
    job = session.execute(query.order_by(OttEncodeJob.created_at).limit(1).with_for_update(skip_locked=True)
                          if session.get_bind().dialect.name != "sqlite" else
                          query.order_by(OttEncodeJob.created_at).limit(1)).scalars().first()
    if job is None:
        return None
    job.status, job.node_id = CLAIMED, node.id
    job.claimed_at = job.heartbeat_at = datetime.now(timezone.utc)
    title = session.get(OttTitle, job.title_id)
    protection = service.protection_for(session, title, api_base) if title is not None else None
    session.flush()
    return {
        "job_id": job.id, "title_id": job.title_id, "source_url": storage.presign_get(job.source_key,
                                                                                      SOURCE_URL_TTL_S),
        "output_prefix": job.output_prefix, "encoder": "h264_videotoolbox" if node.kind == LANE_MAC else "libx264",
        "protection": None if protection is None else {"key_hex": protection.key_hex, "iv_hex": protection.iv_hex,
                                                       "key_uri": protection.key_uri},
    }


def _owned_job(session: Session, node: OttNode, job_id: str) -> OttEncodeJob:
    job = session.get(OttEncodeJob, job_id)
    if job is None or job.node_id != node.id or job.status != CLAIMED:
        raise service.TranscodeError(404, "not_found", "no such claimed job for this node")
    return job


def progress(session: Session, node: OttNode, job_id: str) -> None:
    job = _owned_job(session, node, job_id)
    job.heartbeat_at = datetime.now(timezone.utc)
    session.flush()


def upload_urls(session: Session, node: OttNode, job_id: str, files: Sequence[str], storage: Any) -> dict[str, str]:
    job = _owned_job(session, node, job_id)
    if len(files) > MAX_FILES:
        raise service.TranscodeError(400, "too_many_files", "too many output files")
    urls = {}
    for rel in files:
        clean = posixpath.normpath(str(rel))
        if clean.startswith(("/", "..")) or "/../" in f"/{clean}/":
            raise service.TranscodeError(400, "bad_path", "output paths stay inside the job folder")
        urls[clean] = storage.presign_put(f"{job.output_prefix}/{clean}", content_type(clean), PUT_URL_TTL_S)
    job.heartbeat_at = datetime.now(timezone.utc)
    session.flush()
    return urls


def complete(session: Session, node: OttNode, job_id: str, *, cpu_seconds: float, packager_sha256: str,
             files: Sequence[str], measured_seconds: float | None = None) -> dict[str, Any]:
    """Finish a claimed job; ``measured_seconds`` (the probed source length) is what gets billed.

    A repeated report for a job this node already finished returns the job unchanged, so a
    retried request never bills twice or moves the billed length.
    """
    from app.services.ott_package.packager import MASTER

    done = session.get(OttEncodeJob, job_id)
    if done is not None and done.status == DONE and done.node_id == node.id:
        return service.job_view(done)
    job = _owned_job(session, node, job_id)
    if MASTER not in set(files):
        raise service.TranscodeError(400, "no_master", "the upload has no master playlist")
    service.finish(session, job, cpu_seconds=cpu_seconds, packager_sha256=packager_sha256, node_id=node.id,
                   measured_seconds=measured_seconds)
    return service.job_view(job)


def failed(session: Session, node: OttNode, job_id: str, error: str) -> dict[str, Any]:
    job = _owned_job(session, node, job_id)
    service.fail(session, job, f"{node.name}: {error}")
    return service.job_view(job)


__all__ = ["claim", "complete", "failed", "progress", "upload_urls"]
