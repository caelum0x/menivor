"""Reviewed public value shapes corresponding to the OpenAPI contract."""

from typing import List, TypedDict


class Job(TypedDict, total=False):
    job_id: str
    state: int
    progress: int
    error: str
    result_url: str
    correlation_id: str
    retry_eligible: bool
    job_ids: List[str]
    batch_id: str


class PresignRequest(TypedDict):
    filename: str
    content_type: str
    size: int


class EditorExportRequest(TypedDict):
    in_point: float
    out_point: float


class BrollGenerateRequest(TypedDict, total=False):
    prompt: str
    mode: str
    image_key: str
    aspect: str
    workflow_id: str
    seed: int


class BrollGeneration(TypedDict, total=False):
    generation_id: str
    state: int
    progress: int
    broll_key: str
    result_url: str
    duration: float
    error: str
    retry_eligible: bool
    correlation_id: str
