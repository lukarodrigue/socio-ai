"""As cinco etapas de toda tarefa: Gatilho → Contexto → Auditor → Ação → Relatório.

Gatilho e Contexto ficam no agente (ele recebe o gatilho e monta o contexto).
Daqui para frente o caminho é único: toda ação proposta passa por `processar`,
que consulta o Auditor e só então executa, enfileira, sugere ou bloqueia.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import brain
from .auditor import AcaoProposta, Auditor, Decisao
from .models import Aprovacao, Lancamento, Titulo

Executor = Callable[[Session, dict], str]


class ErroExecucao(Exception):
    pass


# ---------------------------------------------------------------- executores
def _exec_baixa_titulo(sessao: Session, payload: dict) -> str:
    titulo = sessao.get(Titulo, payload["titulo_id"])
    lanc = sessao.get(Lancamento, payload["lancamento_id"])
    if titulo is None or lanc is None:
        raise ErroExecucao("título ou lançamento não existe mais")
    if titulo.status != "aberto":
        raise ErroExecucao(f"título {titulo.id} já está {titulo.status}")
    if lanc.conciliado:
        raise ErroExecucao(f"lançamento {lanc.id} já foi conciliado")
    titulo.status = "baixado"
    titulo.lancamento_id = lanc.id
    lanc.conciliado = True
    return f"título {titulo.id} baixado com o lançamento {lanc.id}"


def _exec_registro(_sessao: Session, payload: dict) -> str:
    # Registrar divergência ou resumo: o próprio evento no Segundo Cérebro é o efeito.
    return payload.get("descricao", "registrado")


EXECUTORES: dict[str, Executor] = {
    "baixa_titulo": _exec_baixa_titulo,
    "registrar_divergencia": _exec_registro,
    "resumir_dia": _exec_registro,
}


# ---------------------------------------------------------------- processamento
@dataclass
class ResultadoTarefa:
    tarefa_id: str
    executadas: int = 0
    aprovacoes_criadas: int = 0
    sugestoes: int = 0
    bloqueadas: int = 0
    ignoradas: int = 0  # já tratadas em rodada anterior
    erros: list[str] = field(default_factory=list)


def nova_tarefa() -> str:
    return uuid.uuid4().hex[:12]


def processar(sessao: Session, auditor: Auditor, acao: AcaoProposta, res: ResultadoTarefa) -> None:
    # Idempotência: a conciliação roda 2x por dia sobre os mesmos dados.
    if sessao.scalar(select(Aprovacao.id).where(Aprovacao.chave == acao.chave)) or brain.ja_registrado(sessao, acao.chave):
        res.ignoradas += 1
        return

    v = auditor.avaliar(acao)
    base = {"acao": acao.tipo, "payload": acao.payload, "valor": str(acao.valor) if acao.valor is not None else None,
            "nivel": int(v.nivel), "decisao": v.decisao.value, "motivo": v.motivo}

    if v.decisao == Decisao.BLOQUEAR:
        brain.registrar(sessao, "auditor", "acao_bloqueada", f"Bloqueado: {acao.descricao}", base, res.tarefa_id, acao.chave)
        res.bloqueadas += 1
    elif v.decisao == Decisao.SUGERIR:
        brain.registrar(sessao, acao.agente, "sugestao", acao.descricao, base, res.tarefa_id, acao.chave)
        res.sugestoes += 1
    elif v.decisao == Decisao.PEDIR_APROVACAO:
        sessao.add(Aprovacao(agente=acao.agente, acao=acao.tipo, descricao=acao.descricao, payload=acao.payload,
                             valor=acao.valor, motivo=v.motivo, chave=acao.chave))
        brain.registrar(sessao, "auditor", "aprovacao_solicitada", acao.descricao, base, res.tarefa_id)
        res.aprovacoes_criadas += 1
    else:
        executor = EXECUTORES.get(acao.tipo)
        if executor is None:
            brain.registrar(sessao, "auditor", "acao_bloqueada", f"Sem executor: {acao.descricao}", base, res.tarefa_id)
            res.bloqueadas += 1
            return
        try:
            with sessao.begin_nested():
                resultado = executor(sessao, acao.payload)
        except ErroExecucao as e:
            brain.registrar(sessao, acao.agente, "erro_execucao", f"{acao.descricao}: {e}", base, res.tarefa_id)
            res.erros.append(str(e))
            return
        tipo_ev = "divergencia" if acao.tipo == "registrar_divergencia" else "acao_executada"
        brain.registrar(sessao, acao.agente, tipo_ev, acao.descricao,
                        {**base, "resultado": resultado, "avisar": v.decisao == Decisao.EXECUTAR_E_AVISAR},
                        res.tarefa_id, acao.chave)
        res.executadas += 1


# ---------------------------------------------------------------- aprovação humana
class ErroAprovacao(Exception):
    pass


def decidir_aprovacao(sessao: Session, auditor: Auditor, aprovacao_id: int, aprovador: str,
                      aprovar: bool, observacao: str = "") -> Aprovacao:
    ap = sessao.get(Aprovacao, aprovacao_id)
    if ap is None:
        raise ErroAprovacao("aprovação não encontrada")
    if ap.status != "pendente":
        raise ErroAprovacao(f"aprovação já está {ap.status}")
    if aprovador not in auditor.playbook.aprovadores:
        raise ErroAprovacao(f"'{aprovador}' não está na lista de aprovadores do Playbook")

    # Reavalia: se o Playbook ou o código mudaram e a ação virou proibida, não executa.
    reav = auditor.avaliar(AcaoProposta(ap.agente, ap.acao, ap.descricao, ap.payload, ap.chave, ap.valor))
    if reav.decisao == Decisao.BLOQUEAR:
        raise ErroAprovacao(f"ação agora é proibida: {reav.motivo}")

    dados = {"aprovacao_id": ap.id, "acao": ap.acao, "payload": ap.payload, "aprovador": aprovador, "observacao": observacao}
    if aprovar:
        executor = EXECUTORES.get(ap.acao)
        if executor is None:
            raise ErroAprovacao(f"ação '{ap.acao}' não tem executor no Beta")
        try:
            with sessao.begin_nested():
                resultado = executor(sessao, ap.payload)
        except ErroExecucao as e:
            raise ErroAprovacao(f"não foi possível executar: {e}") from e
        ap.status = "aprovada"
        brain.registrar(sessao, ap.agente, "acao_executada", f"{ap.descricao} (aprovado por {aprovador})",
                        {**dados, "resultado": resultado, "valor": str(ap.valor) if ap.valor is not None else None},
                        chave=ap.chave)
    else:
        ap.status = "rejeitada"
        brain.registrar(sessao, "gestor", "aprovacao_rejeitada", f"{ap.descricao} (rejeitado por {aprovador})", dados)
    ap.decidido_por = aprovador
    ap.decidido_em = datetime.now(timezone.utc)
    return ap
