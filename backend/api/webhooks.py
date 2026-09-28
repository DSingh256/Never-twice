"""GitHub webhook API (M8)."""

from fastapi import APIRouter

webhook_router = APIRouter(tags=["webhooks"])
