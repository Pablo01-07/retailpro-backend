from datetime import datetime
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class CargaDatos(Base):
    __tablename__ = "carga_datos"

    id_carga = Column(Integer, primary_key=True, autoincrement=True)
    id_usuario = Column(Integer, ForeignKey("usuario.id_usuario", ondelete="SET NULL"), nullable=True, index=True)
    tipo_carga = Column(String(20), nullable=False)
    fecha_ejecucion = Column(DateTime, default=datetime.utcnow, nullable=False)
    estado = Column(String(20), nullable=False)
    registros_procesados = Column(Integer, default=0, nullable=False)
    registros_rechazados = Column(Integer, default=0, nullable=False)
    porcentaje_calidad = Column(Numeric(5, 2), default=0.00, nullable=False)
    detalle_error = Column(String(300), nullable=True)

    usuario = relationship("Usuario", back_populates="cargas")
    ventas = relationship("VentaHistorica", back_populates="carga", cascade="all, delete-orphan")
