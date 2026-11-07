def test_audit_logs_and_kpis(client, admin_token):
    client.post("/api/v1/auth/login", json={"email": "wrong@retailpro.com", "password": "123"})
    client.post("/api/v1/auth/login", json={"email": "admin@retailpro.com", "password": "Admin123!"})

    response = client.get(
        "/api/v1/auditoria",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "kpis" in data
    assert data["kpis"]["total_actions"] >= 2
    assert data["kpis"]["active_users"] >= 1
    assert data["total"] >= 2


def test_audit_export_csv(client, admin_token):
    client.post("/api/v1/auth/login", json={"email": "admin@retailpro.com", "password": "Admin123!"})

    response = client.get(
        "/api/v1/auditoria/exportar",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "ID,Fecha Hora" in response.text


def test_audit_forbidden_for_analyst(client, analyst_token):
    response = client.get(
        "/api/v1/auditoria",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert response.status_code == 403
