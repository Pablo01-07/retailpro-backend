from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import Request
from sqlalchemy.orm import Session
from app.models.auditoria import Auditoria
from app.models.usuario import Usuario

SENSITIVE_KEYS = {
    "password", "contrasena", "contraseña", "clave", "token", "secret",
    "authorization", "clave_hash", "refresh_token", "access_token",
    "jwt", "new_password", "old_password", "hashed_password"
}


def sanitize_payload(data: Any) -> Any:
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(sensitive in k_lower for sensitive in SENSITIVE_KEYS):
                continue
            elif isinstance(v, (dict, list)):
                sanitized[k] = sanitize_payload(v)
            elif isinstance(v, str):
                v_strip = v.strip()
                if (v_strip.startswith("eyJ") and len(v_strip) > 30) or v_strip.startswith("$2b$") or v_strip.startswith("$argon2"):
                    sanitized[k] = "[REDACTADO]"
                else:
                    sanitized[k] = v
            else:
                sanitized[k] = v
        return sanitized
    elif isinstance(data, list):
        return [sanitize_payload(item) for item in data]
    elif isinstance(data, str):
        v_strip = data.strip()
        if (v_strip.startswith("eyJ") and len(v_strip) > 30) or v_strip.startswith("$2b$") or v_strip.startswith("$argon2"):
            return "[REDACTADO]"
    return data


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def create_audit_log(
    db: Session,
    accion: str,
    modulo_afectado: str,
    user: Optional[Usuario] = None,
    id_usuario: Optional[int] = None,
    detalle: Optional[Dict[str, Any]] = None
) -> Auditoria:
    uid = user.id_usuario if user else id_usuario
    sanitized_detalle = sanitize_payload(detalle) if detalle else {}

    log_entry = Auditoria(
        id_usuario=uid,
        accion=accion,
        modulo_afectado=modulo_afectado,
        fecha_hora=datetime.utcnow(),
        detalle=sanitized_detalle
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)
    return log_entry
