from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7a31b9e8f42'
down_revision: Union[str, Sequence[str], None] = 'dada780a7b6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('modelo_version', sa.Column('mape_14d', sa.Numeric(precision=5, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column('modelo_version', 'mape_14d')
