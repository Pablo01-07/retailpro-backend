import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ["ENVIRONMENT"] = "testing"
os.environ["DEBUG"] = "false"

from app.core.database import Base, get_db
from app.core.security import get_password_hash, create_access_token
from app.models.usuario import Usuario
from app.models.producto import Producto
from app.models.venta_historica import VentaHistorica
from app.models.carga_datos import CargaDatos
from app.models.pronostico import Pronostico
from app.models.modelo_version import ModeloVersion
from app.models.alerta import Alerta
from app.models.umbral_configuracion import UmbralConfiguracion
from app.models.auditoria import Auditoria
from app.main import app

POSTGRES_TEST_DATABASE_URL = "postgresql+psycopg://retailpro_app:retailpro_app_pwd_2026@localhost:5432/retailpro_test"

engine_test = create_engine(
    POSTGRES_TEST_DATABASE_URL,
    pool_pre_ping=True
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    Base.metadata.create_all(bind=engine_test)
    yield


@pytest.fixture(scope="function")
def db_session():
    db = TestingSessionLocal()

    table_names = [f'"{table.name}"' for table in Base.metadata.sorted_tables]
    if table_names:
        db.execute(text(f"TRUNCATE TABLE {', '.join(table_names)} RESTART IDENTITY CASCADE;"))
        db.commit()

    admin_user = Usuario(
        nombre_completo="Admin Test",
        correo="admin@retailpro.com",
        clave_hash=get_password_hash("Admin123!"),
        rol="administrador",
        estado=True
    )
    analyst_user = Usuario(
        nombre_completo="Analyst Test",
        correo="analista@retailpro.com",
        clave_hash=get_password_hash("Analista123!"),
        rol="analista",
        estado=True
    )
    logistics_user = Usuario(
        nombre_completo="Logistics Test",
        correo="logistica@retailpro.com",
        clave_hash=get_password_hash("Logistica123!"),
        rol="jefe_logistica",
        estado=True
    )
    db.add_all([admin_user, analyst_user, logistics_user])
    db.commit()

    thresholds = [
        UmbralConfiguracion(id_usuario=admin_user.id_usuario, tipo_umbral="quiebre_prob_min", valor=5.00),
        UmbralConfiguracion(id_usuario=admin_user.id_usuario, tipo_umbral="quiebre_dias_cobertura", valor=7.00),
        UmbralConfiguracion(id_usuario=admin_user.id_usuario, tipo_umbral="sobrestock_pct", valor=150.00),
        UmbralConfiguracion(id_usuario=admin_user.id_usuario, tipo_umbral="sobrestock_dias", valor=90.00),
        UmbralConfiguracion(id_usuario=admin_user.id_usuario, tipo_umbral="calidad_min", valor=98.00),
        UmbralConfiguracion(id_usuario=admin_user.id_usuario, tipo_umbral="mape_max", valor=15.00),
        UmbralConfiguracion(id_usuario=admin_user.id_usuario, tipo_umbral="nivel_servicio_ref", valor=95.00),
    ]
    db.add_all(thresholds)
    db.commit()

    yield db
    db.close()


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def admin_token(db_session):
    admin = db_session.query(Usuario).filter(Usuario.correo == "admin@retailpro.com").first()
    return create_access_token(subject=admin.id_usuario, role=admin.rol)


@pytest.fixture
def analyst_token(db_session):
    analyst = db_session.query(Usuario).filter(Usuario.correo == "analista@retailpro.com").first()
    return create_access_token(subject=analyst.id_usuario, role=analyst.rol)


@pytest.fixture
def logistics_token(db_session):
    logistics = db_session.query(Usuario).filter(Usuario.correo == "logistica@retailpro.com").first()
    return create_access_token(subject=logistics.id_usuario, role=logistics.rol)


@pytest.fixture(autouse=True)
def default_mock_smtp():
    from unittest.mock import MagicMock, patch
    mock_smtp_inst = MagicMock()
    mock_smtp_inst.__enter__.return_value = mock_smtp_inst
    with patch("smtplib.SMTP", return_value=mock_smtp_inst):
        yield mock_smtp_inst
