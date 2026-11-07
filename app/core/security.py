import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Union, Any
import bcrypt
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.usuario import Usuario
from app.models.auditoria import Auditoria


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8")[:72],
            hashed_password.encode("utf-8")
        )
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def create_access_token(subject: Union[str, Any], role: str, expires_delta: Optional[timedelta] = None) -> str:
    now_utc = datetime.now(timezone.utc)
    if expires_delta:
        expire = now_utc + expires_delta
    else:
        expire = now_utc + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {
        "iat": int(now_utc.timestamp()),
        "exp": int(expire.timestamp()),
        "sub": str(subject),
        "role": role,
        "type": "access"
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: Union[str, Any], role: str, expires_delta: Optional[timedelta] = None) -> str:
    now_utc = datetime.now(timezone.utc)
    if expires_delta:
        expire = now_utc + expires_delta
    else:
        expire = now_utc + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode = {
        "iat": int(now_utc.timestamp()),
        "exp": int(expire.timestamp()),
        "sub": str(subject),
        "role": role,
        "type": "refresh"
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_and_consume_refresh_token(raw_token: str, db: Session) -> Optional[Usuario]:
    try:
        payload = jwt.decode(raw_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id_str: str = payload.get("sub")
        token_type: str = payload.get("type")
        token_iat: Optional[int] = payload.get("iat")

        if user_id_str is None or token_type != "refresh":
            return None
        user_id = int(user_id_str)
    except (JWTError, ValueError):
        return None

    user = db.query(Usuario).filter(Usuario.id_usuario == user_id, Usuario.estado == True).first()
    if not user:
        return None

    if token_iat:
        issued_datetime = datetime.fromtimestamp(token_iat, timezone.utc).replace(tzinfo=None)
        logout_exists = db.query(Auditoria).filter(
            Auditoria.id_usuario == user.id_usuario,
            Auditoria.accion == "logout",
            Auditoria.fecha_hora >= issued_datetime - timedelta(seconds=2)
        ).first()
        if logout_exists:
            return None

    return user


def revoke_refresh_token(user_id: int, db: Session) -> bool:
    logout_entry = Auditoria(
        id_usuario=user_id,
        accion="logout",
        modulo_afectado="auth",
        fecha_hora=get_utc_now(),
        detalle={"motivo": "logout_sesion"}
    )
    db.add(logout_entry)
    db.commit()
    return True


def get_password_hash_fingerprint(clave_hash: str) -> str:
    return hashlib.sha256(clave_hash.encode("utf-8")).hexdigest()[:16]


def create_password_reset_token(user: Usuario) -> str:
    now_utc = datetime.now(timezone.utc)
    expire = now_utc + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES)
    huella = get_password_hash_fingerprint(user.clave_hash)
    to_encode = {
        "iat": int(now_utc.timestamp()),
        "exp": int(expire.timestamp()),
        "sub": str(user.id_usuario),
        "correo": user.correo,
        "proposito": "reset",
        "propósito": "reset",
        "purpose": "reset",
        "huella": huella,
        "pwh": user.clave_hash[-10:],
        "type": "password_reset"
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_password_reset_token(raw_token: str, db: Session) -> Optional[Usuario]:
    try:
        payload = jwt.decode(raw_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id_str: str = payload.get("sub")
        proposito = payload.get("propósito") or payload.get("proposito") or payload.get("purpose")
        token_huella = payload.get("huella")
        token_pwh = payload.get("pwh")
        token_type = payload.get("type")

        if not user_id_str or (proposito != "reset" and token_type != "password_reset"):
            return None
        user_id = int(user_id_str)
    except (JWTError, ValueError):
        return None

    user = db.query(Usuario).filter(Usuario.id_usuario == user_id, Usuario.estado == True).first()
    if not user:
        return None

    expected_huella = get_password_hash_fingerprint(user.clave_hash)
    if token_huella:
        if token_huella != expected_huella:
            return None
    elif token_pwh:
        if user.clave_hash[-10:] != token_pwh:
            return None
    else:
        return None

    return user


def mark_password_reset_used(raw_token: str, db: Session):
    pass
