"""Read-only client capability document for the controlled internal pilot."""

from fastapi import Request

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.schema import PilotCapabilitiesResponse
from app.core.capabilities.service import capabilities_for_user
from app.utils import utils

router = new_router()


@router.get(
    "/pilot/capabilities",
    response_model=PilotCapabilitiesResponse,
    summary="Get generation capabilities for this client",
)
def pilot_capabilities(request: Request):
    """Expose feature availability without exposing the allowlist or secrets."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        data = capabilities_for_user(user.id, session)
    return utils.get_response(200, data)
