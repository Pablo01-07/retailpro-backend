import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from jose import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    create_password_reset_token,
    get_password_hash_fingerprint,
    verify_password
)
from app.models.usuario import Usuario
from app.models.auditoria import Auditoria


def test_recuperar_usuario_existente_envia_correo(client, db_session):
    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance) as mock_smtp_class:
        mock_smtp_instance.__enter__.return_value = mock_smtp_instance

        resp = client.post(
            "/api/v1/auth/recuperar",
            json={"correo": "admin@retailpro.com"}
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["message"] == "Te enviamos las instrucciones al correo indicado. Revisa tu bandeja de entrada y spam."

        mock_smtp_class.assert_called_once_with(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with(settings.SMTP_USER, settings.SMTP_PASSWORD)
        mock_smtp_instance.send_message.assert_called_once()

        sent_msg = mock_smtp_instance.send_message.call_args[0][0]
        assert sent_msg["To"] == "admin@retailpro.com"
        assert sent_msg["Subject"] == "Restablecimiento de Contraseña - RetailPro"

        body_text = ""
        for part in sent_msg.walk():
            if part.get_content_type() in ["text/plain", "text/html"]:
                payload = part.get_payload(decode=True)
                if payload:
                    body_text += payload.decode("utf-8")
        assert f"{settings.FRONTEND_URL.rstrip('/')}/restablecer-contrasena?token=" in body_text


def test_recuperar_usuario_inexistente_responde_404_sin_enviar_correo(client, db_session):
    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        mock_smtp_instance.__enter__.return_value = mock_smtp_instance

        resp = client.post(
            "/api/v1/auth/recuperar",
            json={"correo": "no_existe_en_bd@retailpro.com"}
        )

        assert resp.status_code == 404
        data = resp.json()
        assert data["detail"] == "No existe una cuenta registrada con ese correo electrónico."

        mock_smtp_instance.send_message.assert_not_called()


def test_recuperar_usuario_inactivo_responde_403_sin_enviar_correo(client, db_session):
    user_inactivo = db_session.query(Usuario).filter(Usuario.correo == "inactivo.test@retailpro.com").first()
    if not user_inactivo:
        user_inactivo = Usuario(
            nombre_completo="Usuario Inactivo Test",
            correo="inactivo.test@retailpro.com",
            clave_hash="$2b$12$DummyHashForInactiveUserTestingOnly1234567890",
            rol="analista",
            estado=False
        )
        db_session.add(user_inactivo)
        db_session.commit()
    else:
        user_inactivo.estado = False
        db_session.commit()

    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        mock_smtp_instance.__enter__.return_value = mock_smtp_instance

        resp = client.post(
            "/api/v1/auth/recuperar",
            json={"correo": "inactivo.test@retailpro.com"}
        )

        assert resp.status_code == 403
        data = resp.json()
        assert data["detail"] == "La cuenta está inactiva. Comunícate con el administrador."

        mock_smtp_instance.send_message.assert_not_called()


def test_restablecer_token_expirado_falla(client, db_session):
    admin = db_session.query(Usuario).filter(Usuario.correo == "admin@retailpro.com").first()
    assert admin is not None

    now_utc = datetime.now(timezone.utc)
    expired_time = now_utc - timedelta(minutes=5)
    huella = get_password_hash_fingerprint(admin.clave_hash)

    payload_expirado = {
        "sub": str(admin.id_usuario),
        "correo": admin.correo,
        "proposito": "reset",
        "huella": huella,
        "iat": int((expired_time - timedelta(minutes=30)).timestamp()),
        "exp": int(expired_time.timestamp()),
        "type": "password_reset"
    }
    expired_token = jwt.encode(payload_expirado, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    resp = client.post(
        "/api/v1/auth/restablecer",
        json={"token": expired_token, "nueva_contrasena": "NuevaClaveSegura2026!"}
    )
    assert resp.status_code == 400
    msg = (resp.json().get("message") or resp.json().get("detail", "")).lower()
    assert "inválido o ha expirado" in msg


def test_restablecer_token_reutilizado_falla(client, db_session):
    admin = db_session.query(Usuario).filter(Usuario.correo == "admin@retailpro.com").first()
    assert admin is not None

    token = create_password_reset_token(admin)

    resp1 = client.post(
        "/api/v1/auth/restablecer",
        json={"token": token, "nueva_contrasena": "PrimeraClave2026!"}
    )
    assert resp1.status_code == 200
    assert resp1.json()["success"] is True

    db_session.refresh(admin)
    assert verify_password("PrimeraClave2026!", admin.clave_hash) is True

    resp2 = client.post(
        "/api/v1/auth/restablecer",
        json={"token": token, "nueva_contrasena": "SegundaClave2026!"}
    )
    assert resp2.status_code == 400
    msg2 = (resp2.json().get("message") or resp2.json().get("detail", "")).lower()
    assert "inválido o ha expirado" in msg2


def test_restablecer_contrasena_debil_falla(client, db_session):
    admin = db_session.query(Usuario).filter(Usuario.correo == "admin@retailpro.com").first()
    token = create_password_reset_token(admin)

    resp_corta = client.post(
        "/api/v1/auth/restablecer",
        json={"token": token, "nueva_contrasena": "corta1"}
    )
    assert resp_corta.status_code == 400
    msg_corta = resp_corta.json().get("message") or resp_corta.json().get("detail", "")
    assert "8 caracteres" in msg_corta

    resp_solo_letras = client.post(
        "/api/v1/auth/restablecer",
        json={"token": token, "nueva_contrasena": "sololetrasynonumero"}
    )
    assert resp_solo_letras.status_code == 400

    resp_solo_num = client.post(
        "/api/v1/auth/restablecer",
        json={"token": token, "nueva_contrasena": "123456789"}
    )
    assert resp_solo_num.status_code == 400


def test_recuperar_limite_de_intentos_por_correo(client, db_session):
    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        mock_smtp_instance.__enter__.return_value = mock_smtp_instance

        correo_test = "analista@retailpro.com"
        for i in range(5):
            resp = client.post("/api/v1/auth/recuperar", json={"correo": correo_test})
            assert resp.status_code == 200, f"La solicitud {i+1} debió ser exitosa (200)"

        resp_bloqueada = client.post("/api/v1/auth/recuperar", json={"correo": correo_test})
        assert resp_bloqueada.status_code == 429
        msg_block = (resp_bloqueada.json().get("detail") or resp_bloqueada.json().get("message", "")).lower()
        assert "límite" in msg_block

        correo_inexistente = "no_existe_limite@retailpro.com"
        for i in range(5):
            resp_inex = client.post("/api/v1/auth/recuperar", json={"correo": correo_inexistente})
            assert resp_inex.status_code == 404, f"La solicitud {i+1} de inexistente debió retornar 404"
            assert resp_inex.json()["detail"] == "No existe una cuenta registrada con ese correo electrónico."

        resp_bloqueada_inex = client.post("/api/v1/auth/recuperar", json={"correo": correo_inexistente})
        assert resp_bloqueada_inex.status_code == 429, "La 6ta solicitud de inexistente debió ser 429 antes de evaluar existencia"
        msg_block_inex = (resp_bloqueada_inex.json().get("detail") or resp_bloqueada_inex.json().get("message", "")).lower()
        assert "límite" in msg_block_inex


def test_auditoria_y_logs_no_contienen_tokens_ni_contrasenas(client, db_session):
    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        mock_smtp_instance.__enter__.return_value = mock_smtp_instance

        client.post("/api/v1/auth/recuperar", json={"correo": "admin@retailpro.com"})

        admin = db_session.query(Usuario).filter(Usuario.correo == "admin@retailpro.com").first()
        token = create_password_reset_token(admin)
        nueva_pass = "SeguraPassword2026!"

        client.post("/api/v1/auth/restablecer", json={"token": token, "nueva_contrasena": nueva_pass})

    logs_auditoria = db_session.query(Auditoria).all()
    assert len(logs_auditoria) > 0

    token_partes = token.split(".")
    assert len(token_partes) == 3
    token_signature = token_partes[2]

    for log in logs_auditoria:
        detalle_str = str(log.detalle or "")
        assert token not in detalle_str, "El token completo fue encontrado en auditoría"
        assert token_signature not in detalle_str, "La firma del token fue encontrada en auditoría"
        assert nueva_pass not in detalle_str, "La contraseña en texto plano fue encontrada en auditoría"
        assert "clave" not in (log.detalle or {}) or log.detalle["clave"] != nueva_pass
