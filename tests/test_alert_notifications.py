import os
import json
import pytest
from datetime import datetime, date, timedelta
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.models.producto import Producto
from app.models.modelo_version import ModeloVersion
from app.models.pronostico import Pronostico
from app.models.alerta import Alerta
from app.models.carga_datos import CargaDatos
from app.models.umbral_configuracion import UmbralConfiguracion
from app.models.auditoria import Auditoria
from app.services.alert_service import AlertService
from app.services.etl_service import validate_file_content
from app.services.scheduler import get_procesos_config, save_procesos_config


def _get_message_text(msg) -> str:
    text = ""
    for part in msg.walk():
        if part.get_content_type() in ["text/plain", "text/html"]:
            payload = part.get_payload(decode=True)
            if payload:
                text += payload.decode("utf-8")
    return text


@pytest.fixture
def alert_notif_seed(db_session):
    cfg = get_procesos_config()
    cfg["correo_alertas"] = "alertas@fasretail.com, supervisor@fasretail.com"
    cfg["alertas_notificacion_email"] = "alertas@fasretail.com, supervisor@fasretail.com"
    cfg["quiebre_critico"] = True
    cfg["notificar_quiebre"] = True
    cfg["calidad_bajo_umbral"] = True
    cfg["notificar_calidad_baja"] = True
    cfg["sobrestock_prolongado"] = True
    cfg["notificar_sobrestock"] = True
    save_procesos_config(cfg)

    prod = Producto(
        sku="SKU-ALERT-01",
        nombre="Arroz Superior 1kg",
        categoria="Abarrotes",
        stock_actual=0,
        punto_reorden=50,
        estado="activo"
    )
    db_session.add(prod)
    db_session.commit()
    db_session.refresh(prod)

    modelo = ModeloVersion(
        version="v1.0.0-alert-test",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="INICIAL",
        mape=12.0,
        mae=5.0,
        rmse=8.0,
        estado="ACTIVA"
    )
    db_session.add(modelo)
    db_session.commit()
    db_session.refresh(modelo)

    ahora = datetime.utcnow()
    pron = Pronostico(
        id_producto=prod.id_producto,
        id_modelo=modelo.id_modelo,
        fecha_generacion=ahora,
        horizonte_dias=1,
        cantidad_proyectada=20.0,
        intervalo_confianza_inf=15.0,
        intervalo_confianza_sup=25.0,
        nivel_incertidumbre="BAJO",
        explicacion_shap={"probabilidad_quiebre": 95.0, "dias_cobertura_stock": 0.0},
        cantidad_sugerida_reposicion=50,
        fecha_limite_reposicion=date.today() + timedelta(days=2)
    )
    db_session.add(pron)
    db_session.commit()
    db_session.refresh(pron)

    return {"prod": prod, "modelo": modelo, "pron": pron}


def test_get_configuracion_procesos_retorna_smtp_configurado(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = client.get("/api/v1/procesos/configuracion", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "smtp_configurado" in data
    assert isinstance(data["smtp_configurado"], bool)
    assert "correo_alertas" in data
    assert "quiebre_critico" in data
    assert "calidad_bajo_umbral" in data
    assert "sobrestock_prolongado" in data
    assert "umbral_calidad" in data
    assert "calidad_min" in data


def test_put_configuracion_procesos_actualiza_db_y_auditoria(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}
    payload = {
        "correo_alertas": "operaciones@fasretail.com, bodega@fasretail.com",
        "quiebre_critico": True,
        "calidad_bajo_umbral": False,
        "sobrestock_prolongado": True,
        "umbral_calidad": 92.5
    }

    resp = client.put("/api/v1/procesos/configuracion", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "operaciones@fasretail.com" in data["correo_alertas"]
    assert "bodega@fasretail.com" in data["correo_alertas"]
    assert data["calidad_min"] == 92.5
    assert data["umbral_calidad"] == 92.5
    assert data["calidad_bajo_umbral"] is False

    u_db = db_session.query(UmbralConfiguracion).filter(
        UmbralConfiguracion.tipo_umbral == "calidad_min"
    ).first()
    assert u_db is not None
    assert float(u_db.valor) == 92.5

    logs = db_session.query(Auditoria).filter(
        Auditoria.accion == "Configuración de proceso modificada",
        Auditoria.modulo_afectado == "procesos"
    ).all()
    assert len(logs) > 0
    descripciones = [log.detalle.get("descripcion", "") for log in logs if log.detalle]
    assert any("Configuración:" in d for d in descripciones)


def test_configuracion_validacion_errores_422(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}

    r1 = client.put("/api/v1/procesos/configuracion", json={"correo_alertas": "correo-invalido"}, headers=headers)
    assert r1.status_code == 422

    seis_correos = "c1@fas.com, c2@fas.com, c3@fas.com, c4@fas.com, c5@fas.com, c6@fas.com"
    r2 = client.put("/api/v1/procesos/configuracion", json={"correo_alertas": seis_correos}, headers=headers)
    assert r2.status_code == 422

    r3 = client.put("/api/v1/procesos/configuracion", json={"umbral_calidad": 35.0}, headers=headers)
    assert r3.status_code == 422

    r4 = client.put("/api/v1/procesos/configuracion", json={"umbral_calidad": 105.0}, headers=headers)
    assert r4.status_code == 422


def test_endpoint_resumen_alertas_rbac(client, admin_token, analyst_token, logistics_token, alert_notif_seed, db_session):
    headers_adm = {"Authorization": f"Bearer {admin_token}"}
    headers_ana = {"Authorization": f"Bearer {analyst_token}"}
    headers_log = {"Authorization": f"Bearer {logistics_token}"}

    assert client.post("/api/v1/notificaciones/resumen-alertas", headers=headers_ana).status_code == 403
    assert client.post("/api/v1/notificaciones/prueba", headers=headers_ana).status_code == 403

    assert client.post("/api/v1/notificaciones/resumen-alertas", headers=headers_log).status_code == 403
    assert client.post("/api/v1/notificaciones/prueba", headers=headers_log).status_code == 403

    r_resumen = client.post("/api/v1/notificaciones/resumen-alertas", headers=headers_adm)
    assert r_resumen.status_code == 200

    r_alias = client.post("/api/v1/notificaciones/prueba", headers=headers_adm)
    assert r_alias.status_code == 200


def test_endpoint_resumen_alertas_con_alertas_activas_envia_correo(client, admin_token, alert_notif_seed, db_session):
    headers_adm = {"Authorization": f"Bearer {admin_token}"}

    alerta = Alerta(
        id_producto=alert_notif_seed["prod"].id_producto,
        id_pronostico=alert_notif_seed["pron"].id_pronostico,
        tipo_alerta="QUIEBRE",
        estado="ACTIVA",
        fecha_generacion=datetime.utcnow()
    )
    db_session.add(alerta)
    db_session.commit()

    mock_smtp_inst = MagicMock()
    mock_smtp_inst.__enter__.return_value = mock_smtp_inst

    with patch("smtplib.SMTP", return_value=mock_smtp_inst):
        resp = client.post("/api/v1/notificaciones/resumen-alertas", headers=headers_adm)
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is True
        assert data["enviado"] is True
        assert data["cantidad_alertas"] >= 1
        assert len(data["destinatarios"]) >= 1
        assert "Resumen enviado a" in data["message"]
        assert "prueba" not in data["message"].lower()

        assert mock_smtp_inst.send_message.call_count == 1
        sent_msg = mock_smtp_inst.send_message.call_args[0][0]
        assert sent_msg["Subject"] == "Resumen de alertas – RetailPro"
        assert "prueba" not in sent_msg["Subject"].lower()

        body = _get_message_text(sent_msg)
        assert "prueba" not in body.lower()
        assert "SKU-ALERT-01" in body
        assert "Se identificaron 1 alerta(s): 1 crítica(s) que requieren acción inmediata." in body
        assert "Prob. de quiebre: 95.0 %" in body
        assert "P(Q):" not in body

        audit_log = db_session.query(Auditoria).filter(
            Auditoria.accion == "Notificación de alertas enviada",
            Auditoria.modulo_afectado == "notificaciones"
        ).order_by(Auditoria.id_auditoria.desc()).first()
        assert audit_log is not None
        assert audit_log.detalle.get("tipo") == "manual"
        assert audit_log.detalle.get("cantidad_alertas") >= 1
        assert audit_log.detalle.get("cantidad_destinatarios") >= 1


def test_endpoint_resumen_alertas_sin_alertas_no_envia_correo(client, admin_token, db_session):
    headers_adm = {"Authorization": f"Bearer {admin_token}"}

    db_session.query(Alerta).delete()
    db_session.commit()

    mock_smtp_inst = MagicMock()
    mock_smtp_inst.__enter__.return_value = mock_smtp_inst

    with patch("smtplib.SMTP", return_value=mock_smtp_inst):
        resp = client.post("/api/v1/notificaciones/resumen-alertas", headers=headers_adm)
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is True
        assert data["enviado"] is False
        assert data["message"] == "No hay alertas activas de los tipos seleccionados."
        assert "prueba" not in data["message"].lower()

        assert mock_smtp_inst.send_message.call_count == 0


def test_nueva_alerta_envia_un_correo_resumen(alert_notif_seed, db_session):
    mock_smtp_inst = MagicMock()
    mock_smtp_inst.__enter__.return_value = mock_smtp_inst

    with patch("smtplib.SMTP", return_value=mock_smtp_inst):
        creadas = AlertService.sincronizar_alertas(db_session, notificar=True)
        assert creadas >= 1

        assert mock_smtp_inst.send_message.call_count == 1

        sent_msg = mock_smtp_inst.send_message.call_args[0][0]
        assert sent_msg["Subject"] == "Resumen de alertas – RetailPro"
        assert "prueba" not in sent_msg["Subject"].lower()
        body = _get_message_text(sent_msg)
        assert "prueba" not in body.lower()
        assert "SKU-ALERT-01" in body
        assert "Se identificaron 1 alerta(s): 1 crítica(s) que requieren acción inmediata." in body
        assert "Prob. de quiebre: 95.0 %" in body
        assert "P(Q):" not in body
        assert "QUIEBRE" in body
        assert f"{settings.FRONTEND_URL.rstrip('/')}/alertas" in body

        audit_notif = db_session.query(Auditoria).filter(
            Auditoria.accion == "Notificación de alerta enviada",
            Auditoria.modulo_afectado == "notificaciones"
        ).first()
        assert audit_notif is not None
        assert audit_notif.detalle.get("tipo") == "resumen_alertas"
        assert audit_notif.detalle.get("cantidad_alertas") >= 1


def test_tipo_desactivado_no_envia_correo(alert_notif_seed, db_session):
    cfg = get_procesos_config()
    cfg["quiebre_critico"] = False
    cfg["notificar_quiebre"] = False
    save_procesos_config(cfg)

    mock_smtp_inst = MagicMock()
    mock_smtp_inst.__enter__.return_value = mock_smtp_inst

    with patch("smtplib.SMTP", return_value=mock_smtp_inst):
        creadas = AlertService.sincronizar_alertas(db_session, notificar=True)
        assert creadas >= 1
        assert mock_smtp_inst.send_message.call_count == 0


def test_alerta_existente_no_reenvia_correo(alert_notif_seed, db_session):
    mock_smtp_inst = MagicMock()
    mock_smtp_inst.__enter__.return_value = mock_smtp_inst

    with patch("smtplib.SMTP", return_value=mock_smtp_inst):
        creadas_1 = AlertService.sincronizar_alertas(db_session, notificar=True)
        assert creadas_1 >= 1
        assert mock_smtp_inst.send_message.call_count == 1

        creadas_2 = AlertService.sincronizar_alertas(db_session, notificar=True)
        assert creadas_2 == 0
        assert mock_smtp_inst.send_message.call_count == 1


def test_falla_smtp_no_rompe_ejecucion(alert_notif_seed, db_session):
    mock_smtp_inst = MagicMock()
    mock_smtp_inst.__enter__.side_effect = Exception("SMTP connection timed out error")

    with patch("smtplib.SMTP", return_value=mock_smtp_inst):
        creadas = AlertService.sincronizar_alertas(db_session, notificar=True)
        assert creadas >= 1

        alertas_db = db_session.query(Alerta).filter(Alerta.tipo_alerta == "QUIEBRE").all()
        assert len(alertas_db) >= 1


def test_calidad_baja_envia_correo_calidad(db_session):
    u = db_session.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "calidad_min").first()
    if u:
        u.valor = 90.0
    else:
        db_session.add(UmbralConfiguracion(tipo_umbral="calidad_min", valor=90.0))
    db_session.commit()

    cfg = get_procesos_config()
    cfg["calidad_bajo_umbral"] = True
    cfg["notificar_calidad_baja"] = True
    cfg["correo_alertas"] = "calidad@fasretail.com"
    save_procesos_config(cfg)

    csv_invalido = (
        "fecha,sku,cantidad_vendida,precio_unitario\n"
        "2026-10-01,,10,15.5\n"
        "fecha-invalida,PRD-999,-5,20.0\n"
        "2026-10-01,PRD-888,5,0.0\n"
        "2026-10-01,PRD-001,10,12.0\n"
    ).encode("utf-8")

    mock_smtp_inst = MagicMock()
    mock_smtp_inst.__enter__.return_value = mock_smtp_inst

    with patch("smtplib.SMTP", return_value=mock_smtp_inst):
        carga, resumen = validate_file_content(
            db=db_session,
            file_bytes=csv_invalido,
            filename="ventas_baja_calidad.csv",
            tipo_carga="ventas",
            user_id=1
        )

        assert carga.estado == "FALLIDO"
        assert float(carga.porcentaje_calidad) < 90.0

        assert mock_smtp_inst.send_message.call_count == 1
        sent_msg = mock_smtp_inst.send_message.call_args[0][0]
        body = _get_message_text(sent_msg)
        assert "ventas_baja_calidad.csv" in body
        assert f"{settings.FRONTEND_URL.rstrip('/')}/datos" in body

        audit_calidad = db_session.query(Auditoria).filter(
            Auditoria.accion == "Notificación de alerta enviada",
            Auditoria.modulo_afectado == "notificaciones"
        ).first()
        assert audit_calidad is not None
        assert audit_calidad.detalle.get("tipo") == "calidad_bajo_umbral"
        assert audit_calidad.detalle.get("archivo") == "ventas_baja_calidad.csv"


def test_plantilla_ordenamiento_y_frase_apertura_correo():
    from app.services.email_service import EmailService

    alertas_prueba = [
        {"sku": "SKU-MED-15", "nombre_producto": "Prod Media 15d", "tipo_alerta": "SOBRESTOCK", "prioridad": "MEDIA", "dias_cobertura": 15.0, "probabilidad_quiebre": None},
        {"sku": "SKU-ALT-2", "nombre_producto": "Prod Alta 2d", "tipo_alerta": "QUIEBRE", "prioridad": "ALTA", "dias_cobertura": 2.0, "probabilidad_quiebre": 80.0},
        {"sku": "SKU-ALT-05", "nombre_producto": "Prod Alta 0.5d", "tipo_alerta": "QUIEBRE", "prioridad": "ALTA", "dias_cobertura": 0.5, "probabilidad_quiebre": 98.0},
        {"sku": "SKU-MED-1", "nombre_producto": "Prod Media 1d", "tipo_alerta": "SOBRESTOCK", "prioridad": "MEDIA", "dias_cobertura": 1.0, "probabilidad_quiebre": None},
    ]

    mock_smtp_inst = MagicMock()
    mock_smtp_inst.__enter__.return_value = mock_smtp_inst

    with patch("smtplib.SMTP", return_value=mock_smtp_inst):
        EmailService.enviar_resumen_alertas(
            destinatarios=["test@fasretail.com"],
            alertas=alertas_prueba
        )

        assert mock_smtp_inst.send_message.call_count == 1
        sent_msg = mock_smtp_inst.send_message.call_args[0][0]
        body = _get_message_text(sent_msg)

        assert "Se identificaron 4 alerta(s): 2 crítica(s) que requieren acción inmediata y 2 preventiva(s) a vigilar." in body

        assert "Prob. de quiebre: 98.0 %" in body
        assert "Prob. de quiebre: 80.0 %" in body
        assert "P(Q):" not in body

        pos_alt_05 = body.find("SKU-ALT-05")
        pos_alt_2 = body.find("SKU-ALT-2")
        pos_med_1 = body.find("SKU-MED-1")
        pos_med_15 = body.find("SKU-MED-15")

        assert pos_alt_05 != -1 and pos_alt_2 != -1 and pos_med_1 != -1 and pos_med_15 != -1
        assert pos_alt_05 < pos_alt_2 < pos_med_1 < pos_med_15, "Las filas deben estar ordenadas por ALTA primero y cobertura ascendente"

    frase_solo_crit = EmailService.construir_frase_apertura_alertas([
        {"prioridad": "ALTA"}, {"prioridad": "ALTA"}
    ])
    assert frase_solo_crit == "Se identificaron 2 alerta(s): 2 crítica(s) que requieren acción inmediata."

    frase_solo_prev = EmailService.construir_frase_apertura_alertas([
        {"prioridad": "MEDIA"}, {"prioridad": "BAJA"}
    ])
    assert frase_solo_prev == "Se identificaron 2 alerta(s): 2 preventiva(s) a vigilar."


def test_alertas_sin_smtp_se_omiten_sin_error(client, admin_token, alert_notif_seed, db_session):
    al_creadas = AlertService.sincronizar_alertas(db=db_session, notificar=False)
    assert al_creadas > 0

    with patch("app.services.email_service.EmailService.is_smtp_configured", return_value=False):
        with patch("smtplib.SMTP") as mock_smtp:
            resp = client.post(
                "/api/v1/notificaciones/resumen-alertas",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["enviado"] is False
            assert "incompleta o ausente" in data["message"]
            mock_smtp.assert_not_called()

            db_session.query(Alerta).delete()
            db_session.commit()

            al_nuevas = AlertService.sincronizar_alertas(db=db_session, notificar=True)
            assert al_nuevas > 0
            mock_smtp.assert_not_called()

