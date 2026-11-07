from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class Alerta(Base):
    __tablename__ = "alerta"

    id_alerta = Column(Integer, primary_key=True, autoincrement=True)
    id_producto = Column(Integer, ForeignKey("producto.id_producto", ondelete="CASCADE"), nullable=False, index=True)
    id_pronostico = Column(Integer, ForeignKey("pronostico.id_pronostico", ondelete="SET NULL"), nullable=True, index=True)
    tipo_alerta = Column(String(20), nullable=False)
    fecha_generacion = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    estado = Column(String(20), default="ACTIVA", nullable=False)
    fecha_revision = Column(DateTime, nullable=True)

    producto = relationship("Producto", back_populates="alertas")
    pronostico = relationship("Pronostico", back_populates="alertas")
