from datetime import date
from decimal import Decimal as D

from socio_ia.conciliacao import LancamentoIn, TituloIn, conciliar, similaridade

HOJE = date(2026, 11, 20)


def T(id, valor, venc, meio="pix", ref=None, doc="11.111.111/0001-11", cliente="Café Ipê Amarelo Ltda", status="aberto"):
    return TituloIn(id, cliente, doc, D(valor), venc, meio, ref, status)


def L(id, valor, dia, meio="pix", ref=None, doc=None, nome=None):
    return LancamentoIn(id, dia, D(valor), meio, nome, doc, ref)


def test_referencia_bate(playbook):
    r = conciliar([T("t1", "100.00", HOJE, ref="ABC")], [L("l1", "100.00", HOJE, ref="ABC")], playbook.financeiro, HOJE)
    assert [(m.titulo.id, m.lancamento.id, m.confianca) for m in r.matches] == [("t1", "l1", "alta")]
    assert r.divergencias == []


def test_documento_formatado_diferente_ainda_bate(playbook):
    r = conciliar([T("t1", "50.00", HOJE)], [L("l1", "50.00", HOJE, doc="11111111000111")], playbook.financeiro, HOJE)
    assert r.matches[0].regra == "documento+valor"


def test_nome_parecido_vira_baixa_confianca(playbook):
    r = conciliar([T("t1", "77.10", HOJE, doc=None)], [L("l1", "77.10", HOJE, nome="CAFE IPE AMARELO")], playbook.financeiro, HOJE)
    assert r.matches[0].confianca == "baixa"


def test_dois_titulos_iguais_e_ambiguo(playbook):
    ts = [T("t1", "77.10", HOJE, doc=None), T("t2", "77.10", HOJE, doc=None)]
    r = conciliar(ts, [L("l1", "77.10", HOJE, nome="CAFE IPE AMARELO")], playbook.financeiro, HOJE)
    assert r.matches == []
    assert r.divergencias[0].tipo == "credito_nao_identificado"


def test_pagamento_duplicado(playbook):
    r = conciliar([T("t1", "10.00", HOJE, ref="R")],
                  [L("l1", "10.00", HOJE, ref="R"), L("l2", "10.00", HOJE, ref="R")], playbook.financeiro, HOJE)
    assert [d.tipo for d in r.divergencias] == ["pagamento_duplicado"]


def test_cartao_com_taxa_contratada_nao_gera_divergencia(playbook):
    r = conciliar([T("c1", "1000.00", HOJE, meio="cartao", ref="NSU1")],
                  [L("l1", "970.10", HOJE, meio="cartao", ref="NSU1")], playbook.financeiro, HOJE)
    assert len(r.matches) == 1 and r.divergencias == []


def test_cartao_com_taxa_maior_gera_divergencia(playbook):
    r = conciliar([T("c1", "1000.00", HOJE, meio="cartao", ref="NSU1")],
                  [L("l1", "955.00", HOJE, meio="cartao", ref="NSU1")], playbook.financeiro, HOJE)
    assert r.divergencias[0].tipo == "taxa_cartao_acima"
    assert r.divergencias[0].valor == D("15.10")


def test_atraso_respeita_carencia(playbook):
    ts = [T("t1", "1", date(2026, 11, 18)), T("t2", "1", date(2026, 11, 10))]
    r = conciliar(ts, [], playbook.financeiro, HOJE)
    assert [d.titulo_id for d in r.divergencias] == ["t2"]


def test_similaridade_ignora_acento_e_sufixo():
    assert similaridade("Café Ipê Amarelo Ltda", "CAFE IPE AMARELO") == 1.0
