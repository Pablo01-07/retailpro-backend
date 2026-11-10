from datetime import datetime
from sqlalchemy import Column, Integer, String, Numeric, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base


class ModeloVersion(Base):
    __tablename__ = "modelo_version"

    id_modelo = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(20), unique=True, nullable=False)
    fecha_entrenamiento = Column(DateTime, default=datetime.utcnow, nullable=False)
    motivo_entrenamiento = Column(String(30), nullable=False)
    mae = Column(Numeric(8, 4), nullable=True)
    mape = Column(Numeric(5, 2), nullable=True)
    rmse = Column(Numeric(8, 4), nullable=True)
    mape_14d = Column(Numeric(5, 2), nullable=True)
    estado = Column(String(20), nullable=False)

    pronosticos = relationship("Pronostico", back_populates="modelo", cascade="all, delete-orphan")
