from datetime import datetime, timezone
from typing import Generic, TypeVar, List, Optional
from pydantic import BaseModel, ConfigDict, field_serializer

T = TypeVar("T")


class RetailProBaseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer('*', mode='plain', check_fields=False)
    def serialize_datetimes_utc(self, v, info):
        if isinstance(v, datetime):
            if v.tzinfo is None:
                return v.strftime('%Y-%m-%dT%H:%M:%SZ')
            return v.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        return v


class ErrorResponse(RetailProBaseModel):
    code: str
    message: str
    details: Optional[dict] = None


class PaginatedResponse(RetailProBaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    size: int
    pages: int

