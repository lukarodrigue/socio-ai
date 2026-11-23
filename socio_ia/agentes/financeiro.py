"""Agente Financeiro: concilia recebimentos e propõe ações. Quem decide se executa é o Auditor."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import brain
from ..auditor import AcaoProposta, Auditor, Nivel
from ..conciliacao import LancamentoIn, TituloIn, brl, conciliar
from ..models import Lancamento, Titulo
from ..pipeline import ResultadoTarefa, nova_tarefa, processar

AGENTE = "financeiro"


def _contexto(sessao: Session) -> tuple[list[TituloIn], list[LancamentoIn]]:
    """Etapa 2 (Contexto): busca no banco o que é preciso para decidir."""
    titulos = [TituloIn(t.id, t.cliente, t.documento, t.valor, t.vencimento, t.meio, t.referencia, t.status)
               for t in sessao.scalars(select(Titulo))]
    lancs = [LancamentoIn(l.id, l.data, l.valor, l.meio, l.pagador_nome, l.pagador_documento, l.referencia)
             for l in sessao.scalars(select(Lancamento).where(Lancamento.conciliado.is_(False)))]
    return titulos, lancs


def executar_conciliacao(sessao: Session, auditor: Auditor, data_ref: date, gatilho: str = "manual") -> ResultadoTarefa:
    res = ResultadoTarefa(tarefa_id=nova_tarefa())
    brain.registrar(sessao, AGENTE, "tarefa_iniciada", f"Conciliação ({gatilho}) com data de referência {data_ref:%d/%m/%Y}",
                    {"gatilho": gatilho, "data_ref": data_ref.isoformat()}, res.tarefa_id)

    titulos, lancs = _contexto(sessao)
    r = conciliar(titulos, lancs, auditor.playbook.financeiro, data_ref)

    for m in r.matches:
        baixa_conf = m.confianca != "alta"
        processar(sessao, auditor, AcaoProposta(
            agente=AGENTE, tipo="baixa_titulo",
            descricao=f"Baixar título {m.titulo.id} ({m.titulo.cliente}, {brl(m.titulo.valor)}) "
                      f"com {m.lancamento.meio} de {m.lancamento.data:%d/%m/%Y} [regra: {m.regra}]",
            payload={"titulo_id": m.titulo.id, "lancamento_id": m.lancamento.id, "regra": m.regra, "confianca": m.confianca},
            chave=f"baixa:{m.titulo.id}:{m.lancamento.id}",
            valor=m.titulo.valor,
            nivel_maximo_pedido=Nivel.APROVA if baixa_conf else None,
            motivo_agente="correspondência de baixa confiança (sem referência nem documento únicos)" if baixa_conf else None,
        ), res)

    for d in r.divergencias:
        processar(sessao, auditor, AcaoProposta(
            agente=AGENTE, tipo="registrar_divergencia", descricao=d.descricao,
            payload={"tipo": d.tipo, "titulo_id": d.titulo_id, "lancamento_id": d.lancamento_id, "descricao": d.descricao},
            chave=f"div:{d.tipo}:{d.titulo_id}:{d.lancamento_id}", valor=d.valor,
        ), res)
        if d.tipo == "titulo_em_atraso":
            processar(sessao, auditor, AcaoProposta(
                agente=AGENTE, tipo="sugerir_cobranca",
                descricao=f"Cobrar: {d.descricao}",
                payload={"titulo_id": d.titulo_id}, chave=f"cobranca:{d.titulo_id}:{data_ref.isoformat()}", valor=d.valor,
            ), res)

    brain.registrar(sessao, AGENTE, "tarefa_concluida",
                    f"Conciliação: {res.executadas} executadas, {res.aprovacoes_criadas} para aprovação, "
                    f"{res.sugestoes} sugestões, {res.bloqueadas} bloqueadas, {len(res.erros)} erros",
                    {"executadas": res.executadas, "aprovacoes": res.aprovacoes_criadas, "sugestoes": res.sugestoes,
                     "bloqueadas": res.bloqueadas, "ignoradas": res.ignoradas, "erros": res.erros}, res.tarefa_id)
    return res
