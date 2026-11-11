from typing import Sequence, Union
import os
import json
import re
from alembic import op
import sqlalchemy as sa
from app.core.config import settings

revision: str = 'd9e3f5a2b1c4'
down_revision: Union[str, Sequence[str], None] = 'b8d2e4f6a1c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('modelo_version', sa.Column('umbral_mape_evaluacion', sa.Float(), nullable=True))
    op.add_column('modelo_version', sa.Column('wape', sa.Float(), nullable=True))

    bind = op.get_bind()
    try:
        rows = bind.execute(sa.text("SELECT id_modelo, version, observacion FROM modelo_version")).fetchall()
        for row in rows:
            id_m = row[0]
            v_str = row[1]
            obs = row[2] or ""

            u_val = None
            m_disc = re.search(r"umbral de\s+([\d\.]+)%", obs)
            if m_disc:
                try:
                    u_val = float(m_disc.group(1))
                except Exception:
                    pass
            else:
                m_apt = re.search(r"≤\s*([\d\.]+)%\)", obs)
                if m_apt:
                    try:
                        u_val = float(m_apt.group(1))
                    except Exception:
                        pass

            w_val = None
            eval_path = os.path.join(settings.STORAGE_DIR, "modelos", f"evaluacion_modelo_{id_m}.json")
            if os.path.exists(eval_path):
                try:
                    with open(eval_path, "r", encoding="utf-8") as f:
                        edata = json.load(f)
                        if "wape" in edata and edata["wape"] is not None:
                            w_val = float(edata["wape"])
                except Exception:
                    pass

            if w_val is None:
                met_path = os.path.join(settings.STORAGE_DIR, "modelos", "metricas_modelo.json")
                if os.path.exists(met_path):
                    try:
                        with open(met_path, "r", encoding="utf-8") as f:
                            mdata = json.load(f)
                            if mdata.get("id_modelo") == id_m or mdata.get("version") == v_str:
                                if "wape" in mdata and mdata["wape"] is not None:
                                    w_val = float(mdata["wape"])
                    except Exception:
                        pass

            if u_val is not None and w_val is not None:
                bind.execute(
                    sa.text("UPDATE modelo_version SET umbral_mape_evaluacion = :u, wape = :w WHERE id_modelo = :id"),
                    {"u": u_val, "w": w_val, "id": id_m}
                )
            elif u_val is not None:
                bind.execute(
                    sa.text("UPDATE modelo_version SET umbral_mape_evaluacion = :u WHERE id_modelo = :id"),
                    {"u": u_val, "id": id_m}
                )
            elif w_val is not None:
                bind.execute(
                    sa.text("UPDATE modelo_version SET wape = :w WHERE id_modelo = :id"),
                    {"w": w_val, "id": id_m}
                )
    except Exception:
        pass


def downgrade() -> None:
    op.drop_column('modelo_version', 'wape')
    op.drop_column('modelo_version', 'umbral_mape_evaluacion')
