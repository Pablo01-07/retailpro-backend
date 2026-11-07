from fastapi import APIRouter
from app.api.v1 import (
    health,
    auth,
    users,
    audit,
    data,
    processes,
    forecasts,
    models,
    replenishment,
    alerts,
    dashboard,
    reports,
    notifications
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(audit.router)
api_router.include_router(data.router)
api_router.include_router(processes.router)
api_router.include_router(forecasts.router)
api_router.include_router(models.router)
api_router.include_router(replenishment.router)
api_router.include_router(alerts.router)
api_router.include_router(dashboard.router)
api_router.include_router(reports.router)
api_router.include_router(notifications.router)
