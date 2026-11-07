from typing import Optional
from pydantic import BaseModel, EmailStr


class UserProfileResponse(BaseModel):
    id_usuario: int
    nombre_completo: str
    correo: EmailStr
    rol: str
    estado: bool

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: Optional[bool] = False


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserProfileResponse


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordRecoveryRequest(BaseModel):
    correo: Optional[EmailStr] = None
    email: Optional[EmailStr] = None

    @property
    def correo_destino(self) -> str:
        addr = self.correo or self.email
        return str(addr).strip().lower() if addr else ""


class PasswordResetConfirmRequest(BaseModel):
    token: str
    nueva_contrasena: Optional[str] = None
    new_password: Optional[str] = None

    @property
    def password_valida(self) -> str:
        return self.nueva_contrasena or self.new_password or ""


class ActionStatusResponse(BaseModel):
    success: bool
    message: str
