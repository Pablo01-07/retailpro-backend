from app.models.usuario import Usuario
from app.core.security import create_password_reset_token


def test_login_success(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@retailpro.com", "password": "Admin123!"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["correo"] == "admin@retailpro.com"
    assert data["user"]["rol"] == "administrador"


def test_login_invalid_password(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@retailpro.com", "password": "WrongPassword!"}
    )
    assert response.status_code == 401
    assert "incorrectos" in response.json()["message"]


def test_login_account_lockout(client, db_session):
    for i in range(5):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "analista@retailpro.com", "password": f"WrongPwd{i}"}
        )
        if i < 4:
            assert resp.status_code == 401
        else:
            assert resp.status_code == 403
            assert "bloqueada" in resp.json()["message"]

    resp_locked = client.post(
        "/api/v1/auth/login",
        json={"email": "analista@retailpro.com", "password": "Analista123!"}
    )
    assert resp_locked.status_code == 403
    assert "bloqueada temporalmente" in resp_locked.json()["message"]


def test_refresh_token(client):
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@retailpro.com", "password": "Admin123!"}
    )
    refresh_token = login_resp.json()["refresh_token"]

    refresh_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token}
    )
    assert refresh_resp.status_code == 200
    new_data = refresh_resp.json()
    assert "access_token" in new_data
    assert "refresh_token" in new_data


def test_logout_revokes_token(client):
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@retailpro.com", "password": "Admin123!"}
    )
    access_token = login_resp.json()["access_token"]
    refresh_token = login_resp.json()["refresh_token"]

    logout_resp = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert logout_resp.status_code == 200
    assert logout_resp.json()["success"] is True

    refresh_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token}
    )
    assert refresh_resp.status_code == 401


def test_password_recovery_and_reset(client, db_session):
    req_resp = client.post(
        "/api/v1/auth/password-recovery",
        json={"email": "admin@retailpro.com"}
    )
    assert req_resp.status_code == 200

    admin = db_session.query(Usuario).filter(Usuario.correo == "admin@retailpro.com").first()
    raw_token = create_password_reset_token(admin)

    confirm_resp = client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "NewSecretPass2026!"}
    )
    assert confirm_resp.status_code == 200

    login_new = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@retailpro.com", "password": "NewSecretPass2026!"}
    )
    assert login_new.status_code == 200


def test_get_current_user_me(client, admin_token):
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["correo"] == "admin@retailpro.com"
    assert data["rol"] == "administrador"
