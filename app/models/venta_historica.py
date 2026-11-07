from sqlalchemy import Column, Integer, Numeric, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base


class VentaHistorica(Base):
    __tablename__ = "venta_historica"

    id_venta = Column(Integer, primary_key=True, autoincrement=True)
    id_producto = Column(Integer, ForeignKey("producto.id_producto", ondelete="CASCADE"), nullable=False, index=True)
    id_carga = Column(Integer, ForeignKey("carga_datos.id_carga", ondelete="CASCADE"), nullable=False, index=True)
    fecha = Column(Date, nullable=False, index=True)
    cantidad_vendida = Column(Integer, nullable=False)
    precio_unitario = Column(Numeric(8, 2), nullable=False)

    __table_args__ = (
        UniqueConstraint("id_producto", "fecha", name="uq_venta_producto_fecha"),
    )

    producto = relationship("Producto", back_populates="ventas")
    carga = relationship("CargaDatos", back_populates="ventas")
