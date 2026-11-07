from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'dada780a7b6e'
down_revision: Union[str, Sequence[str], None] = 'ebafef8fd1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint('uq_venta_producto_fecha', 'venta_historica', ['id_producto', 'fecha'])


def downgrade() -> None:
    op.drop_constraint('uq_venta_producto_fecha', 'venta_historica', type_='unique')
