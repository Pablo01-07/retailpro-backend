import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    verify_and_consume_refresh_token,
    revoke_refresh_token,
    create_password_reset_token,
    verify_password_reset_token,
)
from app.core.dependencies import get_current_user
from app.core.audit import create_audit_log, get_client_ip
from app.models.usuario import Usuario
from app.models.auditoria import Auditoria
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    RefreshRequest,
    PasswordRecoveryRequest,
    PasswordResetConfirmRequest,
    UserProfileResponse,
    ActionStatusResponse
)
from app.services.email_service import EmailService

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/login", response_model=TokenResponse)
def login(
    login_data: LoginRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """Autentica a un usuario y emite tokens JWT. Bloquea la cuenta tras N intentos fallidos trazados en auditoría."""
    client_ip = get_client_ip(request)
    user = db.query(Usuario).filter(Usuario.correo == login_data.email).first()

    if not user:
        create_audit_log(
            db=db,
            accion="login_fallido",
            modulo_afectado="auth",
            detalle={"correo": login_data.email, "ip": client_ip, "motivo": "correo_inexistente"}
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo electrónico o contraseña incorrectos"
        )

    window_start = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(minutes=settings.ACCOUNT_LOCK_MINUTES)
    recent_failures = db.query(Auditoria).filter(
        Auditoria.accion == "login_fallido",
        Auditoria.modulo_afectado == "auth",
        Auditoria.fecha_hora >= window_start
    ).all()
    failed_count = sum(
        1 for f in recent_failures
        if f.detalle and f.detalle.get("correo") == user.correo
    )

    if failed_count >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
        create_audit_log(
            db=db,
            accion="bloqueo_cuenta",
            modulo_afectado="auth",
            user=user,
            detalle={"correo": user.correo, "ip": client_ip, "intentos": failed_count}
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cuenta bloqueada temporalmente por múltiples intentos fallidos. Intente nuevamente en {settings.ACCOUNT_LOCK_MINUTES} minutos."
        )

    if not user.estado:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta de usuario inactiva. Contacte al administrador del sistema."
        )

    if not verify_password(login_data.password, user.clave_hash):
        create_audit_log(
            db=db,
            accion="login_fallido",
            modulo_afectado="auth",
            user=user,
            detalle={"correo": user.correo, "ip": client_ip, "motivo": "clave_incorrecta"}
        )
        if failed_count + 1 >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
            create_audit_log(
                db=db,
                accion="bloqueo_cuenta",
                modulo_afectado="auth",
                user=user,
                detalle={"correo": user.correo, "ip": client_ip, "intentos": failed_count + 1}
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Ha superado el número máximo de intentos fallidos. Su cuenta ha sido bloqueada temporalmente por {settings.ACCOUNT_LOCK_MINUTES} minutos."
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo electrónico o contraseña incorrectos"
        )

    access_token = create_access_token(subject=user.id_usuario, role=user.rol)
    refresh_token = create_refresh_token(subject=user.id_usuario, role=user.rol)

    create_audit_log(
        db=db,
        accion="login_exitoso",
        modulo_afectado="auth",
        user=user,
        detalle={"ip": client_ip, "rol": user.rol}
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserProfileResponse.model_validate(user)
    )


@router.post("/refresh")
def refresh_token(
    refresh_data: RefreshRequest,
    db: Session = Depends(get_db)
):
    """Genera un nuevo access token utilizando un refresh token JWT válido."""
    user = verify_and_consume_refresh_token(refresh_data.refresh_token, db=db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido o expirado"
        )

    new_access_token = create_access_token(subject=user.id_usuario, role=user.rol)
    new_refresh_token = create_refresh_token(subject=user.id_usuario, role=user.rol)

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


@router.post("/logout", response_model=ActionStatusResponse)
def logout(
    request: Request,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cierra la sesión e invalida la vigencia de tokens del usuario."""
    client_ip = get_client_ip(request)
    revoke_refresh_token(current_user.id_usuario, db=db)

    create_audit_log(
        db=db,
        accion="logout",
        modulo_afectado="auth",
        user=current_user,
        detalle={"ip": client_ip, "motivo": "cierre_sesion"}
    )

    return ActionStatusResponse(
        success=True,
        message="Sesión finalizada exitosamente"
    )


@router.post("/recuperar", response_model=ActionStatusResponse)
@router.post("/password-recovery", response_model=ActionStatusResponse)
def request_password_recovery(
    recovery_data: PasswordRecoveryRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Solicita un enlace para restablecer contraseña (Mockup 02).
    Genera un token JWT (claim propósito='reset', exp 30 min, huella de sha256 del hash actual)
    y envía un correo electrónico en español con STARTTLS.
    Límite: 5 solicitudes por correo por hora (evaluado para todos los casos antes de verificar existencia).
    Respuestas explícitas:
    - 404 si el correo no existe.
    - 403 si el usuario está inactivo.
    - 200 si el usuario existe y está activo.
    """
    if not EmailService.is_smtp_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El envío de correos no está disponible en este momento. Comunícate con el administrador."
        )

    correo_destino = recovery_data.correo_destino
    if not correo_destino:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe proporcionar un correo electrónico válido."
        )

    client_ip = get_client_ip(request)

    one_hour_ago = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(hours=1)
    recent_solicitudes = db.query(Auditoria).filter(
        Auditoria.accion == "solicitud_recuperacion_clave",
        Auditoria.modulo_afectado == "auth",
        Auditoria.fecha_hora >= one_hour_ago
    ).all()
    solicitudes_correo = sum(
        1 for a in recent_solicitudes
        if a.detalle and str(a.detalle.get("correo", "")).strip().lower() == correo_destino
    )

    if solicitudes_correo >= settings.PASSWORD_RECOVERY_MAX_REQUESTS_PER_HOUR:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Ha superado el límite de {settings.PASSWORD_RECOVERY_MAX_REQUESTS_PER_HOUR} solicitudes por hora para este correo. Intente más tarde."
        )

    user = db.query(Usuario).filter(Usuario.correo == correo_destino).first()
    create_audit_log(
        db=db,
        accion="solicitud_recuperacion_clave",
        modulo_afectado="auth",
        user=user,
        detalle={"ip": client_ip, "correo": correo_destino}
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No existe una cuenta registrada con ese correo electrónico."
        )

    if not user.estado:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta está inactiva. Comunícate con el administrador."
        )

    raw_token = create_password_reset_token(user)
    reset_link = f"{settings.FRONTEND_URL.rstrip('/')}/restablecer-contrasena?token={raw_token}"
    EmailService.enviar_correo_recuperacion(
        destinatario=user.correo,
        nombre_usuario=user.nombre_completo,
        enlace_restablecimiento=reset_link
    )

    return ActionStatusResponse(
        success=True,
        message="Te enviamos las instrucciones al correo indicado. Revisa tu bandeja de entrada y spam."
    )


@router.post("/restablecer", response_model=ActionStatusResponse)
@router.post("/reset-password", response_model=ActionStatusResponse)
def confirm_password_reset(
    reset_data: PasswordResetConfirmRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Restablece la contraseña utilizando el token firmado.
    Valida firma, expiración, propósito ('reset') y huella (asegurando un solo uso).
    Aplica las reglas de contraseña del sistema y audita sin tokens ni contraseñas.
    """
    nueva_contrasena = reset_data.password_valida
    if not reset_data.token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El enlace de restablecimiento de contraseña es inválido o ha expirado."
        )

    user = verify_password_reset_token(reset_data.token, db=db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El enlace de restablecimiento de contraseña es inválido o ha expirado."
        )

    if len(nueva_contrasena) < 8 or not (any(c.isalpha() for c in nueva_contrasena) and any(c.isdigit() for c in nueva_contrasena)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña debe tener al menos 8 caracteres y contener letras y números."
        )

    user.clave_hash = get_password_hash(nueva_contrasena)
    db.commit()

    client_ip = get_client_ip(request)
    create_audit_log(
        db=db,
        accion="cambio_clave_exitoso",
        modulo_afectado="auth",
        user=user,
        detalle={"ip": client_ip, "correo": user.correo}
    )

    return ActionStatusResponse(
        success=True,
        message="Contraseña restablecida exitosamente. Ahora puede iniciar sesión con su nueva contraseña."
    )


@router.get("/me", response_model=UserProfileResponse)
def get_current_user_profile(
    current_user: Usuario = Depends(get_current_user)
):
    """Devuelve los datos del perfil del usuario actualmente autenticado."""
    return current_user
