from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class Auditoria(Base):
    __tablename__ = "auditoria"

    id_auditoria = Column(Integer, primary_key=True, autoincrement=True)
    id_usuario = Column(Integer, ForeignKey("usuario.id_usuario", ondelete="SET NULL"), nullable=True, index=True)
    accion = Column(String(100), nullable=False)
    modulo_afectado = Column(String(50), nullable=False)
    fecha_hora = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    detalle = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)

    usuario = relationship("Usuario", back_populates="auditorias")


@event.listens_for(Auditoria, "before_insert")
def sanitize_auditoria_detalle_before_insert(mapper, connection, target):
    if target.detalle:
        from app.core.audit import sanitize_payload
        target.detalle = sanitize_payload(target.detalle)

