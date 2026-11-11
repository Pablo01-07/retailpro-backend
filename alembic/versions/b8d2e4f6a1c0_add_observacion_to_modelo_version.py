from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8d2e4f6a1c0'
down_revision: Union[str, Sequence[str], None] = 'c7a31b9e8f42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('modelo_version', sa.Column('observacion', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('modelo_version', 'observacion')
