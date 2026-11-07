from datetime import datetime
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class UmbralConfiguracion(Base):
    __tablename__ = "umbral_configuracion"

    id_umbral = Column(Integer, primary_key=True, autoincrement=True)
    id_usuario = Column(Integer, ForeignKey("usuario.id_usuario", ondelete="SET NULL"), nullable=True, index=True)
    tipo_umbral = Column(String(30), unique=True, nullable=False)
    valor = Column(Numeric(5, 2), nullable=False)
    fecha_actualizacion = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    usuario = relationship("Usuario", back_populates="umbrales")
