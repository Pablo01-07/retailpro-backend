from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base


class Usuario(Base):
    __tablename__ = "usuario"

    id_usuario = Column(Integer, primary_key=True, autoincrement=True)
    nombre_completo = Column(String(100), nullable=False)
    correo = Column(String(100), unique=True, nullable=False, index=True)
    clave_hash = Column(String(200), nullable=False)
    rol = Column(String(20), nullable=False)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)
    estado = Column(Boolean, default=True, nullable=False)

    auditorias = relationship("Auditoria", back_populates="usuario")
    umbrales = relationship("UmbralConfiguracion", back_populates="usuario")
    cargas = relationship("CargaDatos", back_populates="usuario")
