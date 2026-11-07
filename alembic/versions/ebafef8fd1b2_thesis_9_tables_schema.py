from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'ebafef8fd1b2'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('modelo_version',
    sa.Column('id_modelo', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('version', sa.String(length=20), nullable=False),
    sa.Column('fecha_entrenamiento', sa.DateTime(), nullable=False),
    sa.Column('motivo_entrenamiento', sa.String(length=30), nullable=False),
    sa.Column('mae', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('mape', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('rmse', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('estado', sa.String(length=20), nullable=False),
    sa.PrimaryKeyConstraint('id_modelo'),
    sa.UniqueConstraint('version')
    )
    op.create_table('producto',
    sa.Column('id_producto', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('sku', sa.String(length=20), nullable=False),
    sa.Column('nombre', sa.String(length=150), nullable=False),
    sa.Column('categoria', sa.String(length=50), nullable=False),
    sa.Column('stock_actual', sa.Integer(), nullable=False),
    sa.Column('punto_reorden', sa.Integer(), nullable=False),
    sa.Column('estado', sa.String(length=20), nullable=False),
    sa.Column('fecha_creacion', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id_producto')
    )
    op.create_index(op.f('ix_producto_categoria'), 'producto', ['categoria'], unique=False)
    op.create_index(op.f('ix_producto_sku'), 'producto', ['sku'], unique=True)
    op.create_table('usuario',
    sa.Column('id_usuario', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('nombre_completo', sa.String(length=100), nullable=False),
    sa.Column('correo', sa.String(length=100), nullable=False),
    sa.Column('clave_hash', sa.String(length=200), nullable=False),
    sa.Column('rol', sa.String(length=20), nullable=False),
    sa.Column('fecha_creacion', sa.DateTime(), nullable=False),
    sa.Column('estado', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id_usuario')
    )
    op.create_index(op.f('ix_usuario_correo'), 'usuario', ['correo'], unique=True)
    op.create_table('auditoria',
    sa.Column('id_auditoria', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('id_usuario', sa.Integer(), nullable=True),
    sa.Column('accion', sa.String(length=100), nullable=False),
    sa.Column('modulo_afectado', sa.String(length=50), nullable=False),
    sa.Column('fecha_hora', sa.DateTime(), nullable=False),
    sa.Column('detalle', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.ForeignKeyConstraint(['id_usuario'], ['usuario.id_usuario'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id_auditoria')
    )
    op.create_index(op.f('ix_auditoria_fecha_hora'), 'auditoria', ['fecha_hora'], unique=False)
    op.create_index(op.f('ix_auditoria_id_usuario'), 'auditoria', ['id_usuario'], unique=False)
    op.create_table('carga_datos',
    sa.Column('id_carga', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('id_usuario', sa.Integer(), nullable=True),
    sa.Column('tipo_carga', sa.String(length=20), nullable=False),
    sa.Column('fecha_ejecucion', sa.DateTime(), nullable=False),
    sa.Column('estado', sa.String(length=20), nullable=False),
    sa.Column('registros_procesados', sa.Integer(), nullable=False),
    sa.Column('registros_rechazados', sa.Integer(), nullable=False),
    sa.Column('porcentaje_calidad', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('detalle_error', sa.String(length=300), nullable=True),
    sa.ForeignKeyConstraint(['id_usuario'], ['usuario.id_usuario'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id_carga')
    )
    op.create_index(op.f('ix_carga_datos_id_usuario'), 'carga_datos', ['id_usuario'], unique=False)
    op.create_table('pronostico',
    sa.Column('id_pronostico', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('id_producto', sa.Integer(), nullable=False),
    sa.Column('id_modelo', sa.Integer(), nullable=False),
    sa.Column('fecha_generacion', sa.DateTime(), nullable=False),
    sa.Column('horizonte_dias', sa.Integer(), nullable=False),
    sa.Column('cantidad_proyectada', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('intervalo_confianza_inf', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('intervalo_confianza_sup', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('nivel_incertidumbre', sa.String(length=20), nullable=False),
    sa.Column('explicacion_shap', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('cantidad_sugerida_reposicion', sa.Integer(), nullable=False),
    sa.Column('cantidad_ajustada_reposicion', sa.Integer(), nullable=True),
    sa.Column('fecha_limite_reposicion', sa.Date(), nullable=True),
    sa.ForeignKeyConstraint(['id_modelo'], ['modelo_version.id_modelo'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['id_producto'], ['producto.id_producto'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id_pronostico')
    )
    op.create_index(op.f('ix_pronostico_fecha_generacion'), 'pronostico', ['fecha_generacion'], unique=False)
    op.create_index(op.f('ix_pronostico_id_modelo'), 'pronostico', ['id_modelo'], unique=False)
    op.create_index(op.f('ix_pronostico_id_producto'), 'pronostico', ['id_producto'], unique=False)
    op.create_table('umbral_configuracion',
    sa.Column('id_umbral', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('id_usuario', sa.Integer(), nullable=True),
    sa.Column('tipo_umbral', sa.String(length=30), nullable=False),
    sa.Column('valor', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('fecha_actualizacion', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['id_usuario'], ['usuario.id_usuario'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id_umbral'),
    sa.UniqueConstraint('tipo_umbral')
    )
    op.create_index(op.f('ix_umbral_configuracion_id_usuario'), 'umbral_configuracion', ['id_usuario'], unique=False)
    op.create_table('alerta',
    sa.Column('id_alerta', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('id_producto', sa.Integer(), nullable=False),
    sa.Column('id_pronostico', sa.Integer(), nullable=True),
    sa.Column('tipo_alerta', sa.String(length=20), nullable=False),
    sa.Column('fecha_generacion', sa.DateTime(), nullable=False),
    sa.Column('estado', sa.String(length=20), nullable=False),
    sa.Column('fecha_revision', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['id_producto'], ['producto.id_producto'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['id_pronostico'], ['pronostico.id_pronostico'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id_alerta')
    )
    op.create_index(op.f('ix_alerta_fecha_generacion'), 'alerta', ['fecha_generacion'], unique=False)
    op.create_index(op.f('ix_alerta_id_producto'), 'alerta', ['id_producto'], unique=False)
    op.create_index(op.f('ix_alerta_id_pronostico'), 'alerta', ['id_pronostico'], unique=False)
    op.create_table('venta_historica',
    sa.Column('id_venta', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('id_producto', sa.Integer(), nullable=False),
    sa.Column('id_carga', sa.Integer(), nullable=False),
    sa.Column('fecha', sa.Date(), nullable=False),
    sa.Column('cantidad_vendida', sa.Integer(), nullable=False),
    sa.Column('precio_unitario', sa.Numeric(precision=8, scale=2), nullable=False),
    sa.ForeignKeyConstraint(['id_carga'], ['carga_datos.id_carga'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['id_producto'], ['producto.id_producto'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id_venta')
    )
    op.create_index(op.f('ix_venta_historica_fecha'), 'venta_historica', ['fecha'], unique=False)
    op.create_index(op.f('ix_venta_historica_id_carga'), 'venta_historica', ['id_carga'], unique=False)
    op.create_index(op.f('ix_venta_historica_id_producto'), 'venta_historica', ['id_producto'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_venta_historica_id_producto'), table_name='venta_historica')
    op.drop_index(op.f('ix_venta_historica_id_carga'), table_name='venta_historica')
    op.drop_index(op.f('ix_venta_historica_fecha'), table_name='venta_historica')
    op.drop_table('venta_historica')
    op.drop_index(op.f('ix_alerta_id_pronostico'), table_name='alerta')
    op.drop_index(op.f('ix_alerta_id_producto'), table_name='alerta')
    op.drop_index(op.f('ix_alerta_fecha_generacion'), table_name='alerta')
    op.drop_table('alerta')
    op.drop_index(op.f('ix_umbral_configuracion_id_usuario'), table_name='umbral_configuracion')
    op.drop_table('umbral_configuracion')
    op.drop_index(op.f('ix_pronostico_id_producto'), table_name='pronostico')
    op.drop_index(op.f('ix_pronostico_id_modelo'), table_name='pronostico')
    op.drop_index(op.f('ix_pronostico_fecha_generacion'), table_name='pronostico')
    op.drop_table('pronostico')
    op.drop_index(op.f('ix_carga_datos_id_usuario'), table_name='carga_datos')
    op.drop_table('carga_datos')
    op.drop_index(op.f('ix_auditoria_id_usuario'), table_name='auditoria')
    op.drop_index(op.f('ix_auditoria_fecha_hora'), table_name='auditoria')
    op.drop_table('auditoria')
    op.drop_index(op.f('ix_usuario_correo'), table_name='usuario')
    op.drop_table('usuario')
    op.drop_index(op.f('ix_producto_sku'), table_name='producto')
    op.drop_index(op.f('ix_producto_categoria'), table_name='producto')
    op.drop_table('producto')
    op.drop_table('modelo_version')
