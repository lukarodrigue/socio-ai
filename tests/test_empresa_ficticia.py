"""Teste ponta a ponta: 12 meses da empresa fictícia.

Critério de aceite do Beta:
  - encontra 100% dos erros plantados
  - não inventa nenhuma divergência além deles
  - toda baixa liga o lançamento ao título certo
  - pagamentos acima do limite vão para aprovação, nunca são baixados sozinhos
  - rodar de novo (18h) não duplica nada
"""
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from socio_ia import ficticia
from socio_ia.agentes import dono, financeiro
from socio_ia.importadores import importar_extrato_csv, importar_titulos_csv
from socio_ia.models import Aprovacao, Evento, Titulo
from socio_ia.pipeline import decidir_aprovacao


@pytest.fixture
def cenario(sessao, auditor, tmp_path: Path):
    ficticia.salvar(tmp_path)
    importar_titulos_csv(sessao, (tmp_path / "titulos.csv").read_text(encoding="utf-8"))
    importar_extrato_csv(sessao, (tmp_path / "extrato.csv").read_text(encoding="utf-8"))
    import json
    gab = json.loads((tmp_path / "gabarito.json").read_text(encoding="utf-8"))
    data_ref = date.fromisoformat(gab["data_ref"])
    res = financeiro.executar_conciliacao(sessao, auditor, data_ref, gatilho="teste")
    sessao.commit()
    return gab, data_ref, res


def _divergencias(sessao):
    evs = sessao.scalars(select(Evento).where(Evento.tipo == "divergencia"))
    return {(e.dados["payload"]["tipo"], e.dados["payload"]["titulo_id"], e.dados["payload"]["lancamento_id"]) for e in evs}


def test_encontra_todos_os_erros_e_nenhum_a_mais(sessao, cenario):
    gab, _, res = cenario
    esperado = {(d["tipo"], d["titulo_id"], d["lancamento_id"]) for d in gab["divergencias"]}
    encontrado = _divergencias(sessao)
    assert esperado - encontrado == set(), f"erros não encontrados: {esperado - encontrado}"
    assert encontrado - esperado == set(), f"falsos positivos: {encontrado - esperado}"
    assert res.erros == []


def test_toda_baixa_e_aprovacao_ligam_o_titulo_certo(sessao, cenario):
    gab, _, _ = cenario
    legit = gab["pagamentos_legitimos"]
    for t in sessao.scalars(select(Titulo).where(Titulo.status == "baixado")):
        assert legit.get(t.lancamento_id) == t.id
    for a in sessao.scalars(select(Aprovacao)):
        assert legit.get(a.payload["lancamento_id"]) == a.payload["titulo_id"]


def test_acima_do_limite_espera_aprovacao(sessao, auditor, cenario):
    gab, _, _ = cenario
    for tid in gab["aprovacao_por_limite"]:
        assert sessao.get(Titulo, tid).status == "aberto"
        ap = sessao.scalar(select(Aprovacao).where(Aprovacao.payload["titulo_id"].as_string() == tid))
        assert ap is not None and "limite" in ap.motivo
        decidir_aprovacao(sessao, auditor, ap.id, "gestor", aprovar=True)
        assert sessao.get(Titulo, tid).status == "baixado"


def test_aprovador_fora_do_playbook_e_recusado(sessao, auditor, cenario):
    from socio_ia.pipeline import ErroAprovacao
    ap = sessao.scalar(select(Aprovacao).limit(1))
    with pytest.raises(ErroAprovacao):
        decidir_aprovacao(sessao, auditor, ap.id, "estagiario", aprovar=True)


def test_segunda_rodada_nao_duplica(sessao, auditor, cenario):
    _, data_ref, primeira = cenario
    n_aprov = len(list(sessao.scalars(select(Aprovacao))))
    n_div = len(_divergencias(sessao))
    segunda = financeiro.executar_conciliacao(sessao, auditor, data_ref, gatilho="18h")
    assert segunda.executadas == 0 and segunda.aprovacoes_criadas == 0
    assert len(list(sessao.scalars(select(Aprovacao)))) == n_aprov
    assert len(_divergencias(sessao)) == n_div


def test_relatorio_do_dono(sessao, auditor, cenario):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    hoje = datetime.now(ZoneInfo(auditor.playbook.empresa.fuso)).date()
    rel = dono.relatorio_do_dia(sessao, auditor, hoje)
    assert rel["dados"]["baixas_automaticas"]["quantidade"] > 0
    assert rel["dados"]["divergencias"]["pagamento_duplicado"] == 3
    assert "Precisa da sua aprovação" in rel["markdown"]
