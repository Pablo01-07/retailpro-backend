from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.database import get_db

router = APIRouter()

_scheduler_instance = None


def set_scheduler_instance(scheduler):
    global _scheduler_instance
    _scheduler_instance = scheduler


def get_scheduler_instance():
    return _scheduler_instance


@router.get("/health", tags=["Health"])
def health_check(db: Session = Depends(get_db)):
    """Verifica de verdad la conexión a PostgreSQL y el estado del scheduler. Devuelve HTTP 503 si falla."""
    db_ok = False
    db_detail = "healthy"

    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        db_detail = f"Database connection failed: {str(e)}"

    scheduler_status = "not_started"
    if _scheduler_instance is not None:
        scheduler_status = "running" if _scheduler_instance.running else "stopped"

    if not db_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unhealthy",
                "database": db_detail,
                "scheduler": scheduler_status
            }
        )

    return {
        "status": "healthy",
        "database": "healthy",
        "scheduler": scheduler_status
    }
