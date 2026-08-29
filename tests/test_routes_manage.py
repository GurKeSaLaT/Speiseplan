"""Tests für routes/manage.py: die statische Verwaltungs-Übersichtsseite."""


def test_manage_page_renders(client):
    resp = client.get("/manage")
    assert resp.status_code == 200
    assert "Datenverwaltung".encode("utf-8") in resp.data
