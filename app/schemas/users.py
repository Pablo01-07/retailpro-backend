import datetime
from typing import Optional, List
from pydantic import EmailStr
from app.schemas.common import RetailProBaseModel


class RoleOption(RetailProBaseModel):
    code: str
    name: str
    description: Optional[str] = None


class UserBase(RetailProBaseModel):
    nombre_completo: str
    correo: EmailStr
    rol: str
    estado: bool = True


class UserCreate(UserBase):
    password: Optional[str] = None


class UserUpdate(RetailProBaseModel):
    nombre_completo: Optional[str] = None
    correo: Optional[EmailStr] = None
    rol: Optional[str] = None
    estado: Optional[bool] = None
    password: Optional[str] = None


class UserResponse(RetailProBaseModel):
    id_usuario: int
    nombre_completo: str
    correo: EmailStr
    rol: str
    estado: bool
    fecha_creacion: datetime.datetime


class UserListResponse(RetailProBaseModel):
    items: List[UserResponse]
    total: int
    page: int
    size: int
    pages: int
