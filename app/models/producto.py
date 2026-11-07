from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base


class Producto(Base):
    __tablename__ = "producto"

    id_producto = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String(20), unique=True, nullable=False, index=True)
    nombre = Column(String(150), nullable=False)
    categoria = Column(String(50), nullable=False, index=True)
    stock_actual = Column(Integer, default=0, nullable=False)
    punto_reorden = Column(Integer, default=0, nullable=False)
    estado = Column(String(20), default="activo", nullable=False)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)

    ventas = relationship("VentaHistorica", back_populates="producto", cascade="all, delete-orphan")
    pronosticos = relationship("Pronostico", back_populates="producto", cascade="all, delete-orphan")
    alertas = relationship("Alerta", back_populates="producto", cascade="all, delete-orphan")
