import os
import json
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.encoders import ENCODERS_BY_TYPE, jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.orm import Session

ENCODERS_BY_TYPE[datetime] = lambda dt: dt.strftime('%Y-%m-%dT%H:%M:%SZ') if dt.tzinfo is None else dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class UTCJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        def custom_serializer(obj):
            if isinstance(obj, datetime):
                if obj.tzinfo is None:
                    return obj.strftime('%Y-%m-%dT%H:%M:%SZ')
                return obj.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            raise TypeError(f'Type {type(obj)} not serializable')
        return json.dumps(content, ensure_ascii=False, allow_nan=False, indent=None, separators=(',', ':'), default=custom_serializer).encode('utf-8')


from app.core.config import settings
from app.core.database import get_db
from app.api.v1.api import api_router
from app.api.v1.health import health_check, set_scheduler_instance
from app.services.scheduler import start_scheduler, stop_scheduler, scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("ENVIRONMENT") != "testing":
        start_scheduler()
        set_scheduler_instance(scheduler)
    yield
    if os.environ.get("ENVIRONMENT") != "testing":
        stop_scheduler()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend API de RetailPro: Plataforma web de predicción de volumen de ventas (XGBoost) para optimización de inventarios.",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    default_response_class=UTCJSONResponse,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": f"HTTP_{exc.status_code}",
            "message": exc.detail if isinstance(exc.detail, str) else "Error del servidor",
            "detail": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
            "details": exc.detail if isinstance(exc.detail, dict) else None
        }
    )

from fastapi.encoders import jsonable_encoder

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Los datos enviados no superaron las validaciones requeridas",
            "details": jsonable_encoder(exc.errors())
        }
    )

@app.get("/health", tags=["Health"])
def root_health(db: Session = Depends(get_db)):
    return health_check(db)

app.include_router(api_router, prefix=settings.API_V1_STR)
