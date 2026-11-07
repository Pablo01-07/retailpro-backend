from datetime import datetime
from sqlalchemy import Column, Integer, String, Numeric, DateTime, Date, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class Pronostico(Base):
    __tablename__ = "pronostico"

    id_pronostico = Column(Integer, primary_key=True, autoincrement=True)
    id_producto = Column(Integer, ForeignKey("producto.id_producto", ondelete="CASCADE"), nullable=False, index=True)
    id_modelo = Column(Integer, ForeignKey("modelo_version.id_modelo", ondelete="CASCADE"), nullable=False, index=True)
    fecha_generacion = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    horizonte_dias = Column(Integer, nullable=False)
    cantidad_proyectada = Column(Numeric(10, 2), nullable=False)
    intervalo_confianza_inf = Column(Numeric(10, 2), nullable=False)
    intervalo_confianza_sup = Column(Numeric(10, 2), nullable=False)
    nivel_incertidumbre = Column(String(20), nullable=False)
    explicacion_shap = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    cantidad_sugerida_reposicion = Column(Integer, default=0, nullable=False)
    cantidad_ajustada_reposicion = Column(Integer, nullable=True)
    fecha_limite_reposicion = Column(Date, nullable=True)

    producto = relationship("Producto", back_populates="pronosticos")
    modelo = relationship("ModeloVersion", back_populates="pronosticos")
    alertas = relationship("Alerta", back_populates="pronostico")
