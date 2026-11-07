import os
from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "RetailPro API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    SECRET_KEY: str = "retailpro_super_secret_jwt_key_upc_2026_development_only"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    MAX_FAILED_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCK_MINUTES: int = 15

    DATABASE_URL: str = "postgresql+psycopg://retailpro_app:retailpro_app_pwd_2026@localhost:5432/retailpro_db"
    POSTGRES_SUPERUSER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "retailpro_db"

    POWERBI_READER_USER: str = "powerbi_reader"
    POWERBI_READER_PASSWORD: str = "powerbi_reader_pwd_2026"

    BACKEND_CORS_ORIGINS: Union[str, List[str]] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
        return []

    STORAGE_DIR: str = "storage"
    STORAGE_REPORTES_DIR: str = "storage/reportes"
    STORAGE_ENTRADA_DIR: str = "storage/entrada"
    ARTIFACTS_DIR: str = "artifacts"

    POWERBI_EMBED_URL: str = ""

    DEFAULT_DATA_QUALITY_THRESHOLD: float = 98.0
    DEFAULT_STOCKOUT_MIN_PROBABILITY: float = 5.0
    DEFAULT_STOCKOUT_MIN_COVERAGE_DAYS: int = 7
    DEFAULT_OVERSTOCK_MAX_DEMAND_PCT: float = 150.0
    DEFAULT_OVERSTOCK_MAX_COVERAGE_DAYS: int = 90
    DEFAULT_LEAD_TIME_DAYS: int = 3

    ALERT_CRITICAL_STOCKOUT_PROB_MIN: float = 50.0
    ALERT_CRITICAL_COVERAGE_FACTOR: float = 0.5
    ALERT_CRITICAL_REORDER_POINT_FACTOR: float = 0.5

    UNCERTAINTY_THRESHOLD_LOW: float = 0.95
    UNCERTAINTY_THRESHOLD_MEDIUM: float = 1.10

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@retailpro.com"
    FRONTEND_URL: str = "http://localhost:5173"
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30
    PASSWORD_RECOVERY_MAX_REQUESTS_PER_HOUR: int = 5

    SEED_ADMIN_EMAIL: str = "admin@retailpro.com"
    SEED_ADMIN_PASSWORD: str = ""
    SEED_ANALYST_EMAIL: str = "carlos.lopez@retailpro.com"
    SEED_ANALYST_PASSWORD: str = ""
    SEED_LOGISTICS_EMAIL: str = "roberto.sanchez@retailpro.com"
    SEED_LOGISTICS_PASSWORD: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
