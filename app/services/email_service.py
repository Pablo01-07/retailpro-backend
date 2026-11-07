import os
import re
import smtplib
import logging
from typing import List, Dict, Any, Optional, Tuple, Union
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)

EMAIL_REGEX = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"


class EmailDispatchResult:
    def __init__(self, success: bool, message: str):
        self.success = success
        self.message = message

    def __bool__(self) -> bool:
        return self.success

    def __iter__(self):
        return iter((self.success, self.message))

    def __repr__(self) -> str:
        return f"EmailDispatchResult(success={self.success}, message='{self.message}')"


def parse_emails_destinatarios(raw_val: Union[str, List[str]]) -> List[str]:
    if raw_val is None:
        raise ValueError("Debe proporcionar al menos un correo electrónico.")

    if isinstance(raw_val, list):
        items = [str(x).strip().lower() for x in raw_val if str(x).strip()]
    elif isinstance(raw_val, str):
        items = [x.strip().lower() for x in raw_val.split(",") if x.strip()]
    else:
        raise ValueError("Formato de correos no válido. Debe ser una cadena separada por comas o una lista.")

    if not items:
        raise ValueError("Debe proporcionar al menos un correo electrónico de notificación.")

    if len(items) > 5:
        raise ValueError(f"Se permite un máximo de 5 correos electrónicos de notificación (se enviaron {len(items)}).")

    for email in items:
        if not re.match(EMAIL_REGEX, email):
            raise ValueError(f"El correo electrónico '{email}' no tiene un formato válido.")

    return items


class EmailService:
    @classmethod
    def is_notifications_disabled(cls) -> bool:
        return os.environ.get("SKIP_EMAIL_NOTIFICATIONS", "").lower() in ["true", "1", "yes"]

    @classmethod
    def is_smtp_configured(cls) -> bool:
        return bool(
            settings.SMTP_HOST
            and settings.SMTP_USER
            and settings.SMTP_PASSWORD
            and settings.SMTP_HOST.strip()
            and settings.SMTP_USER.strip()
            and settings.SMTP_PASSWORD.strip()
        )

    @classmethod
    def _sanitizar_error(cls, err: Exception) -> str:
        err_msg = str(err)
        if settings.SMTP_PASSWORD and settings.SMTP_PASSWORD in err_msg:
            err_msg = err_msg.replace(settings.SMTP_PASSWORD, "******")
        return err_msg

    @classmethod
    def enviar_correo_recuperacion(
        cls,
        destinatario: str,
        nombre_usuario: str,
        enlace_restablecimiento: str
    ) -> bool:
        if cls.is_notifications_disabled():
            logger.info("Envío de correo omitido (SKIP_EMAIL_NOTIFICATIONS activo) a %s.", destinatario)
            return True

        if not cls.is_smtp_configured():
            logger.error(
                "Configuración SMTP incompleta (SMTP_HOST, SMTP_USER o SMTP_PASSWORD ausentes). "
                "No se pudo enviar correo de recuperación a %s.",
                destinatario
            )
            return False

        remitente = settings.SMTP_FROM or settings.SMTP_USER
        asunto = "Restablecimiento de Contraseña - RetailPro"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"] = remitente
        msg["To"] = destinatario

        texto_plano = (
            f"Estimado(a) {nombre_usuario},\n\n"
            f"Hemos recibido una solicitud para restablecer la contraseña de su cuenta en RetailPro.\n\n"
            f"Para definir una nueva contraseña, por favor ingrese al siguiente enlace:\n"
            f"{enlace_restablecimiento}\n\n"
            f"Este enlace tiene una validez de {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutos y solo puede ser utilizado una vez.\n\n"
            f"Si usted no solicitó este cambio, puede ignorar este mensaje; su cuenta se encuentra segura.\n\n"
            f"Atentamente,\n"
            f"Equipo de Soporte RetailPro"
        )

        texto_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f7fafc; margin: 0; padding: 20px; color: #2d3748; }}
    .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; padding: 30px; }}
    .header {{ text-align: center; border-bottom: 2px solid #3182ce; padding-bottom: 16px; margin-bottom: 24px; }}
    .header h1 {{ color: #1a365d; font-size: 22px; margin: 0; }}
    .btn {{ display: inline-block; background-color: #3182ce; color: #ffffff !important; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; margin: 20px 0; }}
    .footer {{ font-size: 12px; color: #718096; margin-top: 30px; border-top: 1px solid #e2e8f0; padding-top: 12px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>RetailPro - Plataforma de Demanda e Inventarios</h1>
    </div>
    <p>Estimado(a) <strong>{nombre_usuario}</strong>,</p>
    <p>Hemos recibido una solicitud para restablecer la contraseña de acceso a su cuenta en RetailPro.</p>
    <div style="text-align: center;">
      <a href="{enlace_restablecimiento}" class="btn" target="_blank">Restablecer Contraseña</a>
    </div>
    <p>O copie y pegue el siguiente enlace en su navegador:</p>
    <p style="word-break: break-all; font-size: 13px; color: #3182ce;">{enlace_restablecimiento}</p>
    <p>Este enlace es de uso único y tiene una vigencia estricta de <strong>{settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutos</strong>.</p>
    <p>Si usted no realizó esta solicitud, puede desestimar este mensaje de forma segura.</p>
    <div class="footer">
      <p>Este es un correo automático generado por RetailPro. Por favor no responda a este mensaje.</p>
    </div>
  </div>
</body>
</html>"""

        msg.attach(MIMEText(texto_plano, "plain", "utf-8"))
        msg.attach(MIMEText(texto_html, "html", "utf-8"))

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
            logger.info("Correo de recuperación de contraseña enviado exitosamente a %s.", destinatario)
            return True
        except Exception as e:
            logger.error("Error al enviar correo SMTP a %s: %s", destinatario, cls._sanitizar_error(e))
            return False

    @classmethod
    def construir_frase_apertura_alertas(cls, alertas: List[Dict[str, Any]]) -> str:
        n = len(alertas)
        criticas = sum(1 for a in alertas if (a.get("prioridad") or "").upper() == "ALTA")
        preventivas = n - criticas

        if criticas > 0 and preventivas > 0:
            return f"Se identificaron {n} alerta(s): {criticas} crítica(s) que requieren acción inmediata y {preventivas} preventiva(s) a vigilar."
        elif criticas > 0 and preventivas == 0:
            return f"Se identificaron {n} alerta(s): {criticas} crítica(s) que requieren acción inmediata."
        elif criticas == 0 and preventivas > 0:
            return f"Se identificaron {n} alerta(s): {preventivas} preventiva(s) a vigilar."
        else:
            return f"Se identificaron {n} alerta(s)."

    @classmethod
    def enviar_resumen_alertas(
        cls,
        destinatarios: List[str],
        alertas: List[Dict[str, Any]],
        db: Optional[Session] = None,
        asunto: Optional[str] = None,
        accion: str = "Notificación de alerta enviada",
        tipo_auditoria: str = "resumen_alertas",
        user: Optional[Any] = None
    ) -> EmailDispatchResult:
        dest_str = ", ".join(destinatarios) if destinatarios else ""
        if not destinatarios or not alertas:
            return EmailDispatchResult(True, "Sin alertas o destinatarios para despachar.")

        if db:
            try:
                from app.core.audit import create_audit_log
                create_audit_log(
                    db=db,
                    accion=accion,
                    modulo_afectado="notificaciones",
                    user=user,
                    detalle={
                        "tipo": tipo_auditoria,
                        "cantidad_alertas": len(alertas),
                        "cantidad_destinatarios": len(destinatarios),
                        "destinatarios": destinatarios
                    }
                )
            except Exception as e:
                logger.error("Error al registrar auditoría de notificación: %s", str(e))

        if cls.is_notifications_disabled():
            logger.info("Envío de resumen de alertas omitido (SKIP_EMAIL_NOTIFICATIONS activo) a %s.", dest_str)
            return EmailDispatchResult(True, f"Resumen enviado a {dest_str}")

        if not cls.is_smtp_configured():
            logger.warning(
                "Configuración SMTP incompleta o ausente. Omitiendo despacho de correo de alertas a: %s",
                dest_str
            )
            return EmailDispatchResult(False, "Configuración SMTP incompleta o ausente en el servidor (SMTP_HOST, SMTP_USER o SMTP_PASSWORD ausentes en .env).")

        remitente = settings.SMTP_FROM or settings.SMTP_USER
        asunto_efectivo = asunto or "Resumen de alertas – RetailPro"
        frontend_alertas_url = f"{settings.FRONTEND_URL.rstrip('/')}/alertas"

        def _alert_sort_key(a: Dict[str, Any]):
            prio = (a.get("prioridad") or "MEDIA").upper()
            prio_rank = 0 if prio == "ALTA" else (1 if prio == "MEDIA" else 2)
            dias_cob = a.get("dias_cobertura")
            cob_val = float(dias_cob) if dias_cob is not None else float("inf")
            return (prio_rank, cob_val)

        alertas_ordenadas = sorted(alertas, key=_alert_sort_key)
        frase_apertura = cls.construir_frase_apertura_alertas(alertas_ordenadas)

        lineas_plano = [
            "Estimado equipo,\n",
            f"{frase_apertura}\n"
        ]
        for a in alertas_ordenadas:
            sku = a.get("sku", "-")
            nom = a.get("nombre_producto", "-")
            tipo = a.get("tipo_alerta", "-")
            prio = a.get("prioridad", "MEDIA")
            dias_cob = a.get("dias_cobertura")
            cob_str = f"{dias_cob:.1f} días" if dias_cob is not None else "Sin dato"
            prob = a.get("probabilidad_quiebre")
            prob_str = f" | Prob. de quiebre: {prob:.1f} %" if prob is not None else ""
            lineas_plano.append(f"- SKU: {sku} ({nom}) | Tipo: {tipo} | Prioridad: {prio} | Cobertura: {cob_str}{prob_str}")

        lineas_plano.append(f"\nPuede revisar y gestionar estas alertas en el Centro de Alertas:\n{frontend_alertas_url}\n")
        lineas_plano.append("Atentamente,\nSistema de Demanda e Inventarios RetailPro")
        texto_plano = "\n".join(lineas_plano)

        filas_html = []
        for a in alertas_ordenadas:
            sku = a.get("sku", "-")
            nom = a.get("nombre_producto", "-")
            tipo = a.get("tipo_alerta", "-")
            prio = a.get("prioridad", "MEDIA")
            prio_color = "#e53e3e" if prio.upper() == "ALTA" else "#dd6b20"
            tipo_color = "#c53030" if tipo.upper() == "QUIEBRE" else "#d69e2e"
            dias_cob = a.get("dias_cobertura")
            cob_str = f"{dias_cob:.1f} d" if dias_cob is not None else "-"
            prob = a.get("probabilidad_quiebre")
            prob_str = f"<br><small style='color:#718096;'>Prob. de quiebre: {prob:.1f} %</small>" if prob is not None else ""

            filas_html.append(f"""<tr>
              <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; font-weight: bold;">{sku}</td>
              <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{nom}</td>
              <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;"><span style="color: {tipo_color}; font-weight: bold;">{tipo}</span></td>
              <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;"><span style="background: {prio_color}; color: #fff; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: bold;">{prio}</span></td>
              <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{cob_str}{prob_str}</td>
            </tr>""")

        tabla_rows = "\n".join(filas_html)

        texto_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f7fafc; margin: 0; padding: 20px; color: #2d3748; }}
    .container {{ max-width: 680px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; padding: 25px; }}
    .header {{ border-bottom: 2px solid #e53e3e; padding-bottom: 14px; margin-bottom: 20px; }}
    .header h1 {{ color: #1a365d; font-size: 20px; margin: 0; }}
    table {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 13px; }}
    th {{ background-color: #edf2f7; text-align: left; padding: 10px; border-bottom: 2px solid #cbd5e0; color: #4a5568; }}
    .btn {{ display: inline-block; background-color: #3182ce; color: #ffffff !important; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; margin: 15px 0; font-size: 14px; }}
    .footer {{ font-size: 12px; color: #718096; margin-top: 25px; border-top: 1px solid #e2e8f0; padding-top: 10px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>RetailPro – Resumen de Alertas de Inventario</h1>
    </div>
    <p>{frase_apertura}</p>
    <table>
      <thead>
        <tr>
          <th>SKU</th>
          <th>Producto</th>
          <th>Tipo</th>
          <th>Prioridad</th>
          <th>Cobertura</th>
        </tr>
      </thead>
      <tbody>
        {tabla_rows}
      </tbody>
    </table>
    <div style="text-align: center;">
      <a href="{frontend_alertas_url}" class="btn" target="_blank">Ir al Centro de Alertas</a>
    </div>
    <p style="font-size: 12px; color: #718096; word-break: break-all;">Enlace directo: {frontend_alertas_url}</p>
    <div class="footer">
      <p>Notificación automática del Centro de Monitoreo RetailPro. Por favor no responda a este correo.</p>
    </div>
  </div>
</body>
</html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto_efectivo
        msg["From"] = remitente
        msg["To"] = dest_str

        msg.attach(MIMEText(texto_plano, "plain", "utf-8"))
        msg.attach(MIMEText(texto_html, "html", "utf-8"))

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg, to_addrs=destinatarios)
            logger.info("Correo resumen de alertas (%d alertas) enviado exitosamente a: %s", len(alertas), dest_str)
            return EmailDispatchResult(True, f"Resumen enviado a {dest_str}")
        except Exception as e:
            err_sanitizado = cls._sanitizar_error(e)
            logger.error("Error al enviar correo de alertas por SMTP: %s", err_sanitizado)
            return EmailDispatchResult(False, f"Fallo al conectar con servidor SMTP: {err_sanitizado}")

    @classmethod
    def enviar_alerta_calidad(
        cls,
        destinatarios: List[str],
        filename: str,
        calidad_obtenida: float,
        umbral_requerido: float,
        total_procesados: int,
        total_rechazados: int,
        db: Optional[Session] = None
    ) -> bool:
        if not destinatarios:
            return True

        if db:
            try:
                from app.core.audit import create_audit_log
                create_audit_log(
                    db=db,
                    accion="Notificación de alerta enviada",
                    modulo_afectado="notificaciones",
                    detalle={
                        "tipo": "calidad_bajo_umbral",
                        "archivo": filename,
                        "calidad_obtenida": calidad_obtenida,
                        "umbral_requerido": umbral_requerido,
                        "cantidad_alertas": 1,
                        "cantidad_destinatarios": len(destinatarios),
                        "destinatarios": destinatarios
                    }
                )
            except Exception as e:
                logger.error("Error al registrar auditoría de calidad: %s", str(e))

        if cls.is_notifications_disabled():
            logger.info("Envío de alerta de calidad omitido (SKIP_EMAIL_NOTIFICATIONS activo) a %s.", destinatarios)
            return True

        if not cls.is_smtp_configured():
            logger.warning("Configuración SMTP incompleta o ausente. Omitiendo alerta de calidad para %s.", filename)
            return False

        remitente = settings.SMTP_FROM or settings.SMTP_USER
        asunto = f"Alerta de Calidad de Datos - RetailPro: Archivo '{filename}' bajo umbral ({calidad_obtenida:.1f}%)"
        frontend_calidad_url = f"{settings.FRONTEND_URL.rstrip('/')}/datos"

        texto_plano = (
            f"Alerta de Calidad de Datos - RetailPro\n\n"
            f"Se ha rechazado la ingesta del archivo '{filename}' debido a que su índice de calidad no superó el umbral mínimo exigido.\n\n"
            f"- Archivo: {filename}\n"
            f"- Calidad Obtenida: {calidad_obtenida:.2f}%\n"
            f"- Umbral Mínimo Requerido: {umbral_requerido:.2f}%\n"
            f"- Registros Procesados: {total_procesados}\n"
            f"- Registros Rechazados: {total_rechazados}\n\n"
            f"Consulte el detalle de incidencias y rechazos en la plataforma:\n{frontend_calidad_url}\n\n"
            f"Atentamente,\nEquipo de Calidad de Datos RetailPro"
        )

        texto_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f7fafc; margin: 0; padding: 20px; color: #2d3748; }}
    .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; padding: 25px; }}
    .header {{ border-bottom: 2px solid #e53e3e; padding-bottom: 12px; margin-bottom: 20px; }}
    .header h1 {{ color: #c53030; font-size: 20px; margin: 0; }}
    .metric-box {{ background-color: #fff5f5; border: 1px solid #feb2b2; border-radius: 6px; padding: 15px; margin: 20px 0; }}
    .btn {{ display: inline-block; background-color: #3182ce; color: #ffffff !important; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; margin: 15px 0; font-size: 14px; }}
    .footer {{ font-size: 12px; color: #718096; margin-top: 25px; border-top: 1px solid #e2e8f0; padding-top: 10px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Alerta de Calidad de Datos Insuficiente</h1>
    </div>
    <p>La carga del archivo <strong>{filename}</strong> ha sido clasificada como <strong>FALLIDA</strong> debido a un índice de calidad por debajo del umbral mínimo configurado.</p>
    <div class="metric-box">
      <p style="margin: 5px 0;"><strong>Calidad Obtenida:</strong> <span style="color: #e53e3e; font-size: 18px; font-weight: bold;">{calidad_obtenida:.2f}%</span></p>
      <p style="margin: 5px 0;"><strong>Umbral Mínimo Requerido:</strong> <span>{umbral_requerido:.2f}%</span></p>
      <p style="margin: 5px 0;"><strong>Total Procesados:</strong> <span>{total_procesados}</span></p>
      <p style="margin: 5px 0;"><strong>Total Rechazados:</strong> <span>{total_rechazados}</span></p>
    </div>
    <div style="text-align: center;">
      <a href="{frontend_calidad_url}" class="btn" target="_blank">Revisar Incidencias de Calidad</a>
    </div>
    <div class="footer">
      <p>Notificación automática del subsistema ETL RetailPro. Por favor no responda a este mensaje.</p>
    </div>
  </div>
</body>
</html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"] = remitente
        msg["To"] = ", ".join(destinatarios)

        msg.attach(MIMEText(texto_plano, "plain", "utf-8"))
        msg.attach(MIMEText(texto_html, "html", "utf-8"))

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg, to_addrs=destinatarios)
            logger.info("Correo de alerta de calidad de datos enviado exitosamente a: %s", ", ".join(destinatarios))
            return True
        except Exception as e:
            logger.error("Error al enviar alerta de calidad por SMTP: %s", cls._sanitizar_error(e))
            return False

    @classmethod
    def enviar_correo_prueba(
        cls,
        destinatarios: List[str],
        current_user: Optional[Any] = None,
        db: Optional[Session] = None
    ) -> Tuple[bool, str]:
        if not destinatarios:
            return False, "No se proporcionaron destinatarios para el correo de prueba."

        if cls.is_notifications_disabled():
            msg_ok = f"Modo prueba sin envío real (SKIP_EMAIL_NOTIFICATIONS activo). Destinatarios verificados: {', '.join(destinatarios)}."
            if db:
                try:
                    from app.core.audit import create_audit_log
                    create_audit_log(
                        db=db,
                        accion="Notificación de alerta enviada",
                        modulo_afectado="notificaciones",
                        user=current_user,
                        detalle={
                            "tipo": "prueba",
                            "cantidad_alertas": 0,
                            "cantidad_destinatarios": len(destinatarios),
                            "destinatarios": destinatarios,
                            "modo": "simulado"
                        }
                    )
                except Exception:
                    pass
            return True, msg_ok

        if not cls.is_smtp_configured():
            return False, "Configuración SMTP incompleta en el servidor (SMTP_HOST, SMTP_USER o SMTP_PASSWORD ausentes en .env)."

        remitente = settings.SMTP_FROM or settings.SMTP_USER
        asunto = "Notificación de Prueba - RetailPro Alertas"

        texto_plano = (
            "Notificación de Prueba - RetailPro\n\n"
            "Este es un correo de prueba enviado desde la consola de configuración de procesos de RetailPro (Mockup 09).\n"
            "El servidor SMTP se encuentra correctamente vinculado y listo para el despacho de alertas operativas.\n\n"
            "Atentamente,\nEquipo de Administración RetailPro"
        )

        texto_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f7fafc; margin: 0; padding: 20px; color: #2d3748; }}
    .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; padding: 25px; }}
    .header {{ border-bottom: 2px solid #38a169; padding-bottom: 12px; margin-bottom: 20px; }}
    .header h1 {{ color: #22543d; font-size: 20px; margin: 0; }}
    .footer {{ font-size: 12px; color: #718096; margin-top: 25px; border-top: 1px solid #e2e8f0; padding-top: 10px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>✓ Prueba de Notificaciones SMTP Exitosa</h1>
    </div>
    <p>Este es un correo de prueba generado desde la configuración de procesos de <strong>RetailPro</strong>.</p>
    <p>El canal de correo electrónico SMTP está operativo y listo para emitir alertas de inventario y calidad de datos.</p>
    <div class="footer">
      <p>Notificación de prueba RetailPro. No es necesario responder.</p>
    </div>
  </div>
</body>
</html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"] = remitente
        msg["To"] = ", ".join(destinatarios)

        msg.attach(MIMEText(texto_plano, "plain", "utf-8"))
        msg.attach(MIMEText(texto_html, "html", "utf-8"))

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg, to_addrs=destinatarios)

            if db:
                try:
                    from app.core.audit import create_audit_log
                    create_audit_log(
                        db=db,
                        accion="Notificación de alerta enviada",
                        modulo_afectado="notificaciones",
                        user=current_user,
                        detalle={
                            "tipo": "prueba",
                            "cantidad_alertas": 0,
                            "cantidad_destinatarios": len(destinatarios),
                            "destinatarios": destinatarios
                        }
                    )
                except Exception:
                    pass

            return True, f"Correo de prueba enviado exitosamente a: {', '.join(destinatarios)}"
        except Exception as e:
            err_sanitizado = cls._sanitizar_error(e)
            logger.error("Error al enviar correo de prueba SMTP: %s", err_sanitizado)
            return False, f"Fallo al conectar con servidor SMTP: {err_sanitizado}"
