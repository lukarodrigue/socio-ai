from decimal import Decimal

import pytest
from sqlalchemy.exc import DatabaseError

from socio_ia import brain
from socio_ia.auditor import AcaoProposta, Auditor, Decisao, Nivel
from socio_ia.models import Evento


def acao(tipo, valor=None, **kw):
    return AcaoProposta("teste", tipo, f"teste {tipo}", {}, f"k:{tipo}", Decimal(valor) if valor else None, **kw)


def test_acao_desconhecida_e_bloqueada(auditor):
    assert auditor.avaliar(acao("transferir_tudo")).decisao == Decisao.BLOQUEAR


@pytest.mark.parametrize("tipo", ["apagar_banco", "exportar_base_clientes"])
def test_nivel_zero_bloqueia_mesmo_se_playbook_liberar(playbook, tipo):
    playbook.autonomia[tipo] = 4
    assert Auditor(playbook).avaliar(acao(tipo)).decisao == Decisao.BLOQUEAR


def test_mover_dinheiro_nunca_passa_de_aprovacao(playbook):
    playbook.autonomia["pagar_fornecedor"] = 4
    v = Auditor(playbook).avaliar(acao("pagar_fornecedor", "10"))
    assert v.decisao == Decisao.PEDIR_APROVACAO


def test_playbook_nao_fura_teto_em_codigo(playbook):
    playbook.autonomia["baixa_titulo"] = 4  # teto é 3
    v = Auditor(playbook).avaliar(acao("baixa_titulo", "100"))
    assert v.nivel == Nivel.FAZ_E_AVISA
    assert "teto" in v.motivo


def test_baixa_dentro_do_limite_e_automatica(auditor):
    assert auditor.avaliar(acao("baixa_titulo", "4999.99")).decisao == Decisao.EXECUTAR_E_AVISAR


def test_baixa_acima_do_limite_vai_para_aprovacao(auditor):
    assert auditor.avaliar(acao("baixa_titulo", "5000.01")).decisao == Decisao.PEDIR_APROVACAO


def test_agente_so_pode_reduzir_autonomia(auditor):
    assert auditor.avaliar(acao("baixa_titulo", "10", nivel_maximo_pedido=Nivel.APROVA)).decisao == Decisao.PEDIR_APROVACAO
    # pedir MAIS do que o permitido não tem efeito
    assert auditor.avaliar(acao("sugerir_cobranca", nivel_maximo_pedido=Nivel.AUTONOMO)).decisao == Decisao.SUGERIR


def test_segundo_cerebro_recusa_alteracao_e_exclusao(sessao):
    ev = brain.registrar(sessao, "teste", "x", "original")
    sessao.commit()
    with pytest.raises(DatabaseError):
        sessao.execute(Evento.__table__.update().values(resumo="adulterado"))
    sessao.rollback()
    with pytest.raises(DatabaseError):
        sessao.execute(Evento.__table__.delete())
    sessao.rollback()
    assert sessao.get(Evento, ev.id).resumo == "original"
