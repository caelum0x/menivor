from fastapi import APIRouter
from app.controllers.v1 import calendar, connections, schedule, social, studio
from app.domains.publishing.native_router import router as native_router
from app.domains.publishing.experiments_router import router as experiments_router
from app.domains.publishing.extended.router import router as extended_router
from app.domains.publishing.extended.channels_router import router as channels_router
from app.domains.social_inbox.autopilot_router import router as autopilot_router
from app.domains.multipost.router import router as multipost_router
router = APIRouter()
# extended_router: Facebook/LinkedIn/X/Threads/Pinterest/Bluesky connect + scheduled posts.
# multipost_router: many TikTok/Instagram/YouTube accounts, paced queue, batch scheduling.
# autopilot_router: social-inbox engagement autopilot, mounted here because this domain
# router is already included by the root API router.
# native_router must precede connections.router: its literal /jobs/{job_id}/publish/native
# would otherwise be shadowed by connections' /jobs/{job_id}/publish/{provider}.
for _adapter in (native_router, studio.router, schedule.router, social.router, connections.router, calendar.router, experiments_router,
                 extended_router, channels_router, autopilot_router, multipost_router):
    router.include_router(_adapter)
