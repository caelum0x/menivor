"""Canonical billing domain router composed from incremental transport adapters."""
from fastapi import APIRouter
from app.controllers.v1 import billing as billing_controller, credit_packs, invoices, monthly_plans, premium_credits, subscriptions, usage
router = APIRouter()
for _adapter in (billing_controller.router, credit_packs.router, monthly_plans.router, premium_credits.router, subscriptions.router, usage.router, invoices.router):
    router.include_router(_adapter)
