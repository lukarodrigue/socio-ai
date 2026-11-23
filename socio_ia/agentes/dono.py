"""Agente Dono: confere o dia e entrega o relatório.

Os números do relatório são montados por código a partir do Segundo Cérebro.
A IA (se configurada) só escreve um parágrafo de abertura no tom do Playbook,
e recebe apenas os números já calculados — não tem como inventar valores.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import brain, llm
from ..auditor import AcaoProposta, Auditor
from ..conciliacao import brl
from ..models import Aprovacao
from ..pipeline import ResultadoTarefa, nova_tarefa, processar

AGENTE = "dono"

ROTULOS = {
    "pagamento_duplicado": "Pagamentos em duplicidade",
    "valor_divergente": "Valores diferentes do título",
    "credito_nao_identificado": "Créditos sem título",
    "titulo_em_atraso": "Títulos em atraso (novos)",
    "taxa_cartao_acima": "Taxa de cartão acima da contratada",
}


def _intervalo_utc(dia: date, fuso: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(fuso)
    ini = datetime.combine(dia, time.min, tz)
    return ini, ini + timedelta(days=1)


def montar_relatorio(sessao: Session, auditor: Auditor, dia: date, llm_url: str = "", llm_modelo: str = "") -> dict:
    pb = auditor.playbook
    ini, fim = _intervalo_utc(dia, pb.empresa.fuso)
    eventos = brain.consultar(sessao, desde=ini, ate=fim, limite=100_000)

    baixas_auto, baixas_aprovadas = [], []
    divergencias: dict[str, list[str]] = defaultdict(list)
    sugestoes, bloqueios, erros = [], [], []
    for e in eventos:
        if e.tipo == "acao_executada" and e.dados.get("acao") == "baixa_titulo":
            (baixas_aprovadas if e.dados.get("aprovador") else baixas_auto).append(e)
        elif e.tipo == "divergencia":
            divergencias[e.dados.get("payload", {}).get("tipo", "outra")].append(e.resumo)
        elif e.tipo == "sugestao":
            sugestoes.append(e.resumo)
        elif e.tipo == "acao_bloqueada":
            bloqueios.append(e.resumo)
        elif e.tipo == "erro_execucao":
            erros.append(e.resumo)

    pendentes = list(sessao.scalars(select(Aprovacao).where(Aprovacao.status == "pendente").order_by(Aprovacao.id)))

    def soma(evs):
        return sum((Decimal(e.dados["valor"]) for e in evs if e.dados.get("valor")), Decimal(0))

    dados = {
        "empresa": pb.empresa.nome,
        "dia": dia.isoformat(),
        "baixas_automaticas": {"quantidade": len(baixas_auto), "total": str(soma(baixas_auto))},
        "baixas_aprovadas": {"quantidade": len(baixas_aprovadas), "total": str(soma(baixas_aprovadas))},
        "divergencias": {k: len(v) for k, v in divergencias.items()},
        "aguardando_aprovacao": len(pendentes),
        "sugestoes_cobranca": len(sugestoes),
        "bloqueios": len(bloqueios),
        "erros": len(erros),
    }

    L = [f"# Relatório do dia — {pb.empresa.nome}", f"**{dia:%d/%m/%Y}**", ""]
    abertura = None
    if llm_url:
        abertura = llm.gerar_texto(llm_url, llm_modelo,
            f"Escreva 2 frases de abertura para o relatório diário de uma empresa, em português, tom: {pb.tom_de_voz}. "
            f"Use SOMENTE estes números, sem inventar nenhum outro: {dados}")
    if abertura:
        L += [abertura, ""]

    L += ["## Resumo",
          f"- Baixas automáticas: **{len(baixas_auto)}** ({brl(soma(baixas_auto))})",
          f"- Baixas aprovadas pelo gestor: **{len(baixas_aprovadas)}** ({brl(soma(baixas_aprovadas))})",
          f"- Aguardando sua aprovação: **{len(pendentes)}**",
          f"- Divergências novas: **{sum(len(v) for v in divergencias.values())}**",
          f"- Clientes para cobrar: **{len(sugestoes)}**", ""]

    if pendentes:
        L.append("## Precisa da sua aprovação")
        for a in pendentes[:30]:
            L.append(f"- [#{a.id}] {a.descricao} — *{a.motivo}*")
        if len(pendentes) > 30:
            L.append(f"- … e mais {len(pendentes) - 30}")
        L.append("")
    if divergencias:
        L.append("## Divergências encontradas")
        for tipo, itens in sorted(divergencias.items()):
            L.append(f"### {ROTULOS.get(tipo, tipo)} ({len(itens)})")
            L += [f"- {x}" for x in itens[:20]]
            if len(itens) > 20:
                L.append(f"- … e mais {len(itens) - 20}")
        L.append("")
    if sugestoes:
        L.append("## Sugestões de cobrança (nada foi enviado ao cliente)")
        L += [f"- {s}" for s in sugestoes[:20]]
        L.append("")
    if bloqueios or erros:
        L.append("## Bloqueios e erros")
        L += [f"- {x}" for x in bloqueios + erros]
        L.append("")

    return {"dados": dados, "markdown": "\n".join(L)}


def relatorio_do_dia(sessao: Session, auditor: Auditor, dia: date, llm_url: str = "", llm_modelo: str = "") -> dict:
    rel = montar_relatorio(sessao, auditor, dia, llm_url, llm_modelo)
    res = ResultadoTarefa(tarefa_id=nova_tarefa())
    processar(sessao, auditor, AcaoProposta(
        agente=AGENTE, tipo="resumir_dia", descricao=f"Relatório do dia {dia:%d/%m/%Y}",
        payload={"descricao": f"Relatório do dia {dia:%d/%m/%Y}", **rel["dados"]},
        chave=f"relatorio:{dia.isoformat()}:{datetime.now().isoformat(timespec='minutes')}",
    ), res)
    return rel


def inicio_do_dia(sessao: Session, auditor: Auditor) -> dict:
    """07:00 — lê as pendências e registra o que precisa de atenção hoje."""
    pend = Counter(a.acao for a in sessao.scalars(select(Aprovacao).where(Aprovacao.status == "pendente")))
    resumo = f"Início do dia: {sum(pend.values())} aprovações pendentes" + (f" ({dict(pend)})" if pend else "")
    brain.registrar(sessao, AGENTE, "inicio_do_dia", resumo, {"pendentes": dict(pend)})
    return {"pendentes": dict(pend)}
