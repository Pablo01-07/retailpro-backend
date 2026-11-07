from unittest.mock import MagicMock
from app.core.database import get_db
from app.main import app


def test_root_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "healthy"


def test_api_v1_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "healthy"


def test_health_check_db_failure(client):
    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("Conexión perdida a PostgreSQL")

    def override_broken_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_broken_db
    try:
        response = client.get("/api/v1/health")
        assert response.status_code == 503
        data = response.json()
        assert data["code"] == "HTTP_503"
        assert data["details"]["status"] == "unhealthy"
        assert "Conexión perdida" in data["details"]["database"]
    finally:
        app.dependency_overrides.clear()
