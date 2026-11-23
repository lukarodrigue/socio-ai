import os

import pytest
from fastapi.testclient import TestClient

from socio_ia import ficticia


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCIO_DATABASE_URL", "sqlite://")
    monkeypatch.setenv("SOCIO_AGENDADOR", "0")
    monkeypatch.setenv("SOCIO_API_TOKEN", "segredo")
    from socio_ia.app import contexto
    contexto.cache_clear()
    from socio_ia.api import app
    ficticia.salvar(tmp_path)
    with TestClient(app) as c:
        c.headers["Authorization"] = "Bearer segredo"
        yield c, tmp_path
    contexto.cache_clear()


def test_fluxo_completo_pela_api(cliente):
    c, pasta = cliente
    assert c.get("/aprovacoes", headers={"Authorization": "Bearer errado"}).status_code == 401
    with open(pasta / "titulos.csv", "rb") as f:
        assert c.post("/importar/titulos", files={"arquivo": ("titulos.csv", f)}).json()["novos"] > 1000
    with open(pasta / "extrato.csv", "rb") as f:
        assert c.post("/importar/extrato", files={"arquivo": ("extrato.csv", f)}).json()["novos"] > 1000
    r = c.post("/financeiro/conciliar", params={"data_ref": "2026-11-20"}).json()
    assert r["aprovacoes_criadas"] == 62
    pend = c.get("/aprovacoes").json()
    alvo = pend[0]["id"]
    assert c.post(f"/aprovacoes/{alvo}/aprovar", json={"aprovador": "intruso"}).status_code == 409
    assert c.post(f"/aprovacoes/{alvo}/aprovar", json={"aprovador": "gestor"}).json()["status"] == "aprovada"
    assert c.post(f"/aprovacoes/{alvo}/aprovar", json={"aprovador": "gestor"}).status_code == 409
    assert "Relatório do dia" in c.get("/relatorio").text
