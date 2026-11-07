from app.models.usuario import Usuario


def test_list_users_as_admin(client, admin_token):
    response = client.get(
        "/api/v1/usuarios",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] >= 3


def test_list_users_as_analyst_forbidden(client, analyst_token):
    response = client.get(
        "/api/v1/usuarios",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert response.status_code == 403
    assert "Acceso denegado" in response.json()["message"]


def test_create_user_as_admin(client, admin_token):
    response = client.post(
        "/api/v1/usuarios",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "nombre_completo": "Nuevo Usuario Operativo",
            "correo": "nuevo.usuario@retailpro.com",
            "rol": "analista",
            "estado": True,
            "password": "Password123!"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["correo"] == "nuevo.usuario@retailpro.com"
    assert data["nombre_completo"] == "Nuevo Usuario Operativo"
    assert data["rol"] == "analista"
    assert data["estado"] is True


def test_create_user_duplicate_email(client, admin_token):
    response = client.post(
        "/api/v1/usuarios",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "nombre_completo": "Duplicado",
            "correo": "admin@retailpro.com",
            "rol": "administrador"
        }
    )
    assert response.status_code == 400
    assert "ya existe" in response.json()["message"].lower()


def test_update_user(client, admin_token, db_session):
    analyst = db_session.query(Usuario).filter(Usuario.correo == "analista@retailpro.com").first()

    response = client.put(
        f"/api/v1/usuarios/{analyst.id_usuario}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"nombre_completo": "María Mendoza Actualizada"}
    )
    assert response.status_code == 200
    assert response.json()["nombre_completo"] == "María Mendoza Actualizada"


def test_deactivate_user(client, admin_token, db_session):
    analyst = db_session.query(Usuario).filter(Usuario.correo == "analista@retailpro.com").first()

    response = client.delete(
        f"/api/v1/usuarios/{analyst.id_usuario}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    assert response.json()["estado"] is False
